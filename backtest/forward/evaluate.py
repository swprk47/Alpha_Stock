"""후보별 평가: 신호 -> 목표 비중 -> 엔진 -> 통계를 한 평가 구간에 대해 이어 붙인다.

신호는 항상 자료의 첫 달부터 계산해 제외 상태를 이어 가고, 평가 구간은 수익률을 재는 거래일만 정한다.
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from backtest.forward import registry
from backtest.forward.costs import CostModel
from backtest.forward.engine import monthly_returns, run_portfolio
from backtest.forward.gate import gate_states
from backtest.forward.lottery import composite, month_stats, select
from backtest.forward.months import in_window, periods
from backtest.forward.registry import BENCHMARK
from backtest.forward.stats import (
    Stat, drawdown_episodes, max_drawdown, mdd_diff_stat, mean_stat, window_drawdown,
)


# ------------------------------------------------------------------ 목표 비중
def lottery_targets(frames, bench, all_periods, order, *, reentry_pct):
    """(tilt_targets, base_targets, log). 키는 교체일.

    base = 그달 대상 종목 전체 같은 비중, tilt = select의 held 같은 비중. 대상이 없으면 둘 다 {}.
    """
    tilt, base, log = {}, {}, {}
    prev_excluded = set()
    for p in all_periods:
        stats = {}
        for code, frame in frames.items():
            s = month_stats(frame, bench, p.signal_day, min_days=registry.LOTTERY.min_days)
            if s is not None:
                stats[code] = s
        held, excluded = select(composite(stats), prev_excluded, order,
                                exclude_pct=registry.LOTTERY.exclude_pct, reentry_pct=reentry_pct)
        eligible = sorted(stats, key=lambda c: (order.index(c) if c in order else len(order), c))
        base[p.trade_day] = {c: 1.0 / len(eligible) for c in eligible}
        tilt[p.trade_day] = {c: 1.0 / len(held) for c in held} if held else {}
        log[p.trade_day] = {"signal_day": p.signal_day, "eligible": len(eligible),
                            "excluded": sorted(excluded)}
        prev_excluded = set(excluded)
    return tilt, base, log


def gate_targets(bench, all_periods):
    """(gate_targets, hold_targets). 보유면 {BENCHMARK: 1.0}, 현금이면 {}. hold는 항상 보유."""
    states = gate_states(bench, all_periods, months=registry.GATE.months)
    gate = {p.trade_day: ({BENCHMARK: 1.0} if states[p.signal_day] else {}) for p in all_periods}
    hold = {p.trade_day: {BENCHMARK: 1.0} for p in all_periods}
    return gate, hold


# ------------------------------------------------------------------ 후보 ①
@dataclass
class LotteryEval:
    diff: dict               # 비용 배수 -> 월 차이(회피 - 전체)의 mean_stat
    monthly_diff: pd.Series  # 배수 1 기준, 교체일 인덱스
    turnover_tilt: float
    turnover_base: float
    excluded_mean: float
    yearly_diff: dict        # 연도 -> 월 차이 합(배수 1)
    vs_kodex_annual: float
    n_months: int
    first_month: "pd.Timestamp | None" = None   # 측정한 첫 교체일
    last_month: "pd.Timestamp | None" = None    # 측정한 마지막 교체일
    eligible_min: "int | None" = None           # 측정한 달의 대상 종목 수 최소·중앙값·최대
    eligible_median: "float | None" = None
    eligible_max: "int | None" = None
    eligible_by_year: dict = field(default_factory=dict)  # 교체일 연도 -> 대상 종목 수 중앙값


def _empty_stat():
    return mean_stat([], block=registry.BLOCK_MONTHS)


def _empty_lottery():
    return LotteryEval({m: _empty_stat() for m in registry.COST_MULTIPLIERS},
                       pd.Series(dtype=float), 0.0, 0.0, 0.0, {}, 0.0, 0)


def _mean_turnover(result, trade_days):
    """첫 교체일(초기 매수)을 뺀 교체일들의 평균 회전율. 없으면 0.0."""
    vals = [float(result.turnover[d]) for d in trade_days[1:] if d in result.turnover.index]
    return float(np.mean(vals)) if vals else 0.0


def _closing_boundary(all_periods, last_trade_day, end):
    """마지막 교체일 t_k 의 달이 end 안에서 끝났으면 그 달을 닫는 경계, 아니면 None.

    (a) t_k 다음 기간의 신호일(그달 마지막 거래일)이 end 이하면 그 기간의 교체일.
    (b) end 가 t_k 달의 달력상 월말 이상이면 end 다음 날(학습처럼 달력을 월말에서 자른 경우).
    """
    nxt = next((p for p in all_periods if p.trade_day > last_trade_day), None)
    if nxt is not None and nxt.signal_day <= end:
        return nxt.trade_day
    if end >= last_trade_day + pd.offsets.MonthEnd(0):
        return end + pd.Timedelta(days=1)
    return None


def evaluate_lottery(frames, bench, calendar, order, *, start, end, reentry_pct,
                     draws: int = registry.DRAWS) -> LotteryEval:
    """측정은 구간 안에서 기준(전체 보유) 대상 종목이 처음 생긴 교체일부터 시작한다.

    그 전 교체일(대상 없음, 현금)은 월 차이·회전율·제외 수 어디에도 넣지 않는다.
    마지막 교체일의 달은 end 안에서 끝났을 때만 넣는다(_closing_boundary).
    """
    all_periods = periods(calendar)
    end = pd.Timestamp(end)
    window = in_window(all_periods, start, end)
    if not window:
        return _empty_lottery()
    tilt_t, base_t, log = lottery_targets(frames, bench, all_periods, order, reentry_pct=reentry_pct)
    days = [p.trade_day for p in window]
    k0 = next((i for i, d in enumerate(days) if base_t[d]), None)
    if k0 is None:
        return _empty_lottery()
    trade_days = days[k0:]
    first = trade_days[0]
    closing = _closing_boundary(all_periods, trade_days[-1], end)
    bounds = trade_days + ([closing] if closing is not None else [])

    diff, runs = {}, {}
    for mult in registry.COST_MULTIPLIERS:
        cost = CostModel(mult)
        tilt = run_portfolio(frames, calendar, tilt_t, cost, start=first, end=end)
        base = run_portfolio(frames, calendar, base_t, cost, start=first, end=end)
        tm, bm = monthly_returns(tilt.daily, bounds), monthly_returns(base.daily, bounds)
        runs[mult] = (tilt, base, tm, bm)
        diff[mult] = mean_stat((tm - bm).to_numpy(), block=registry.BLOCK_MONTHS,
                               draws=draws, seed=registry.SEED)

    tilt, base, tm, bm = runs[1.0]
    monthly_diff = (tm - bm).astype(float)
    yearly = {}
    for day, v in monthly_diff.items():
        yearly[day.year] = yearly.get(day.year, 0.0) + float(v)

    kodex = run_portfolio({BENCHMARK: bench}, calendar, {d: {BENCHMARK: 1.0} for d in trade_days},
                          CostModel(1.0), start=first, end=end, etf_codes=frozenset({BENCHMARK}))
    km = monthly_returns(kodex.daily, bounds)
    vs_kodex = float((tm.mean() - km.mean()) * 12) if len(tm) else 0.0
    excluded_mean = float(np.mean([len(log[d]["excluded"]) for d in trade_days]))

    measured = list(monthly_diff.index)
    counts = [log[d]["eligible"] for d in measured]
    by_year = {}
    for d, c in zip(measured, counts):
        by_year.setdefault(d.year, []).append(c)
    return LotteryEval(diff=diff, monthly_diff=monthly_diff,
                       turnover_tilt=_mean_turnover(tilt, trade_days),
                       turnover_base=_mean_turnover(base, trade_days),
                       excluded_mean=excluded_mean, yearly_diff=yearly,
                       vs_kodex_annual=vs_kodex, n_months=len(monthly_diff),
                       first_month=measured[0] if measured else None,
                       last_month=measured[-1] if measured else None,
                       eligible_min=min(counts) if counts else None,
                       eligible_median=float(np.median(counts)) if counts else None,
                       eligible_max=max(counts) if counts else None,
                       eligible_by_year={y: float(np.median(v)) for y, v in by_year.items()})


# ------------------------------------------------------------------ 후보 ②
@dataclass
class GateEval:
    mdd_gate: float
    mdd_hold: float
    mdd_diff: Stat
    return_given_up_annual: float
    vol_gate: float
    vol_hold: float
    switches: int
    episodes: list


def _annual_return(daily) -> float:
    n = len(daily)
    if n == 0:
        return 0.0
    return float(np.prod(1.0 + np.asarray(daily, dtype=float)) ** (252 / n) - 1.0)


def _vol(daily) -> float:
    return float(np.std(np.asarray(daily, dtype=float), ddof=1) * np.sqrt(252)) if len(daily) > 1 else 0.0


def evaluate_gate(bench, calendar, *, start, end, draws: int = registry.DRAWS) -> GateEval:
    all_periods = periods(calendar)
    window = in_window(all_periods, start, end)
    if not window:
        return GateEval(0.0, 0.0, mdd_diff_stat([], [], block=registry.BLOCK_DAYS), 0.0, 0.0, 0.0, 0, [])
    gate_t, hold_t = gate_targets(bench, all_periods)
    first = window[0].trade_day
    kw = dict(start=first, end=end, etf_codes=frozenset({BENCHMARK}))
    gate = run_portfolio({BENCHMARK: bench}, calendar, gate_t, CostModel(1.0), **kw).daily
    hold = run_portfolio({BENCHMARK: bench}, calendar, hold_t, CostModel(1.0), **kw).daily

    states = gate_states(bench, all_periods, months=registry.GATE.months)
    flags = [states[p.signal_day] for p in window]
    episodes = [{"peak_day": e.peak_day, "end_day": e.end_day, "depth_hold": e.depth,
                 "depth_gate": window_drawdown(gate, e.peak_day, e.end_day)}
                for e in drawdown_episodes(hold, registry.BIG_DROP)]
    return GateEval(
        mdd_gate=max_drawdown(gate), mdd_hold=max_drawdown(hold),
        mdd_diff=mdd_diff_stat(gate, hold, block=registry.BLOCK_DAYS, draws=draws, seed=registry.SEED),
        return_given_up_annual=_annual_return(hold) - _annual_return(gate),
        vol_gate=_vol(gate), vol_hold=_vol(hold),
        switches=sum(1 for a, b in zip(flags[:-1], flags[1:]) if a != b),
        episodes=episodes)
