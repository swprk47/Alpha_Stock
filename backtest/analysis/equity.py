"""일봉 기준 계좌 곡선과 단순 보유 비교.

보유 중인 포지션마다 종가로 평가하고(일중 변동은 보지 못한다), 그날 보유한 포지션에 균등 배분(매일 재조정)하며
보유 포지션이 없는 날은 현금(수익 0)이다. 한 거래의 일별 증가율을 모두 곱하면 시뮬레이션의 순수익률과 정확히 같다.
"""
import math

import numpy as np
import pandas as pd

from .bootstrap import DEFAULT_SEED, DRAWS, BootResult, bootstrap_sums

TRADING_DAYS = 252
_EPS = 1e-12


def trade_daily_factors(trade, frame: pd.DataFrame) -> pd.Series:
    """거래가 열려 있는 날마다 (1 + 일간 수익률). 종가 진입은 진입일 다음 날부터, 다음날 시가 진입은 진입일부터 시작한다.
    기준가는 진입가(슬리피지 포함), 중간 날은 종가(거래정지로 0 이하면 직전 값 유지), 청산일은 청산가이고
    진입·청산 비용(수수료·세금)은 청산일에 한 번에 반영한다."""
    entry_pos = frame.index.get_loc(trade.entry_date)
    exit_pos = frame.index.get_loc(trade.exit_date)
    first = entry_pos if trade.entry_mode == "next_open" else entry_pos + 1
    days = frame.index[first:exit_pos + 1]
    cost = (1 + trade.net_return_pct / 100) / (trade.exit_price / trade.entry_price)
    prev, factors = float(trade.entry_price), []
    for i, day in enumerate(days):
        if i == len(days) - 1:
            price = float(trade.exit_price)
        else:
            close = float(frame["close"].loc[day])
            price = close if close > 0 else prev
        factors.append(price / prev)
        prev = price
    factors[-1] *= cost
    return pd.Series(factors, index=days)


def portfolio_daily(trades: list, frames: dict, dates: list) -> pd.DataFrame:
    """dates 전체에 대한 일간 수익률 ret(보유 포지션 단순평균, 없으면 0)과 보유 여부 invested."""
    parts = [trade_daily_factors(t, frames[t.code]) - 1 for t in trades]
    index = pd.Index(dates)
    if not parts:
        return pd.DataFrame({"ret": 0.0, "invested": False}, index=index)
    grouped = pd.concat(parts).groupby(level=0).mean()
    ret = grouped.reindex(index).fillna(0.0)
    return pd.DataFrame({"ret": ret, "invested": index.isin(grouped.index)}, index=index)


def perf(ret: pd.Series, invested: "pd.Series | None" = None) -> dict:
    """연환산 수익률, 최대 낙폭(시작 값 1 이 첫 고점), 샤프(무위험수익률 0 가정), 시장 노출 비율."""
    n = len(ret)
    if n == 0:
        return {"ann_return": None, "max_drawdown": None, "sharpe": None, "exposure": None, "n_days": 0}
    curve = (1 + ret).cumprod()
    peak = np.maximum(curve.cummax(), 1.0)
    std = ret.std(ddof=1) if n > 1 else float("nan")
    sharpe = None if not math.isfinite(std) or std < _EPS else float(ret.mean() / std * math.sqrt(TRADING_DAYS))
    return {"ann_return": float(curve.iloc[-1] ** (TRADING_DAYS / n) - 1),
            "max_drawdown": float((curve / peak - 1).min()), "sharpe": sharpe,
            "exposure": None if invested is None else float(invested.mean()), "n_days": n}


def benchmark_returns(bench: pd.DataFrame, dates: list) -> pd.Series:
    """벤치마크 종가의 일간 수익률을 dates 에 맞춘다(없는 날은 0)."""
    return bench["close"].pct_change().reindex(pd.Index(dates)).fillna(0.0)


def matched_benchmark(bench_ret: pd.Series, invested: pd.Series) -> pd.Series:
    """우리가 투자한 날에만 벤치마크를 보유한 것으로 본다(투자 기간 맞춤)."""
    return bench_ret.where(invested.reindex(bench_ret.index, fill_value=False), 0.0)


def information_ratio(ret: pd.Series, bench_ret: pd.Series):
    diff = ret - bench_ret
    std = diff.std(ddof=1) if len(diff) > 1 else float("nan")
    if not math.isfinite(std) or std < _EPS:
        return None
    return float(diff.mean() / std * math.sqrt(TRADING_DAYS))


def excess_ci(ret: pd.Series, other: pd.Series, *, seed: int = DEFAULT_SEED, draws: int = DRAWS) -> BootResult:
    """일간 초과수익 평균(연환산은 호출하는 쪽에서 x 252)의 날짜 블록 부트스트랩."""
    diff = (ret - other).to_numpy(dtype=float)
    stats = np.column_stack([diff, np.ones(len(diff))])
    return bootstrap_sums(stats, lambda s: s[0] / s[1], draws=draws, seed=seed)


def cost_drag(trades: list) -> dict:
    """수수료·세금이 깎은 양: 총수익(슬리피지 포함, 수수료·세금 제외) 평균과 순수익 평균, 그 차이."""
    if not trades:
        return {"gross_mean_pct": None, "net_mean_pct": None, "drag_pct": None}
    gross = math.fsum((t.exit_price / t.entry_price - 1) * 100 for t in trades) / len(trades)
    net = math.fsum(t.net_return_pct for t in trades) / len(trades)
    return {"gross_mean_pct": gross, "net_mean_pct": net, "drag_pct": gross - net}
