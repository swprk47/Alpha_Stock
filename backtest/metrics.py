"""백테스트 지표: 요약, 연도별, 점수대별, 시장 대비, 대조군, 민감도, 점검표."""
import math
import random
from collections import defaultdict
from dataclasses import dataclass

import pandas as pd

from .signals import DayResult, Signal
from .simulate import simulate_picks


@dataclass(frozen=True)
class Summary:
    n: int
    target_rate: float
    stop_rate: float
    expire_rate: float
    win_rate: float                  # 순수익률 > 0 인 거래 비율
    avg_win_pct: "float | None"
    avg_loss_pct: "float | None"
    expectancy_pct: "float | None"   # 거래당 평균 순수익률(비용 반영)
    profit_factor: "float | None"    # 이익 합 / |손실 합|, 손실이 없으면 None
    avg_held_days: "float | None"
    max_drawdown_pct: float          # 날짜순 누적 순수익률 곡선의 최대 하락폭(%p)
    max_loss_streak: int             # 순수익률 < 0 이 이어진 최대 거래 수


def summarize(trades) -> Summary:
    n = len(trades)
    if n == 0:
        return Summary(0, 0.0, 0.0, 0.0, 0.0, None, None, None, None, None, 0.0, 0)
    nets = [t.net_return_pct for t in trades]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x < 0]
    rate = lambda reason: sum(1 for t in trades if t.exit_reason == reason) / n
    ordered = sorted(trades, key=lambda t: (t.signal_date, t.code))
    cum = peak = max_dd = 0.0
    streak = max_streak = 0
    for t in ordered:
        cum += t.net_return_pct
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
        streak = streak + 1 if t.net_return_pct < 0 else 0
        max_streak = max(max_streak, streak)
    return Summary(
        n=n, target_rate=rate("target"), stop_rate=rate("stop"), expire_rate=rate("expire"),
        win_rate=len(wins) / n,
        avg_win_pct=math.fsum(wins) / len(wins) if wins else None,
        avg_loss_pct=math.fsum(losses) / len(losses) if losses else None,
        expectancy_pct=math.fsum(nets) / n,
        profit_factor=math.fsum(wins) / abs(math.fsum(losses)) if losses else None,
        avg_held_days=math.fsum(t.held_days for t in trades) / n,
        max_drawdown_pct=max_dd, max_loss_streak=max_streak)


def by_year(trades) -> dict:
    groups = defaultdict(list)
    for t in trades:
        groups[t.signal_date.year].append(t)
    return {year: summarize(group) for year, group in sorted(groups.items())}


SCORE_BANDS = (("60-64", 60, 65), ("65-69", 65, 70), ("70+", 70, 10_000))


def by_score_band(trades) -> dict:
    """점수대별 요약. 세 구간 키는 거래가 없어도 항상 있다."""
    return {label: summarize([t for t in trades if low <= t.score < high]) for label, low, high in SCORE_BANDS}


# ── 시장 대비 ──


def benchmark_excess(trades, bench):
    """거래 순수익률 - 같은 기간 벤치마크 수익률(비용 미반영)의 평균(%p). 벤치에 날짜가 없는 거래는 뺀다."""
    diffs = []
    for t in trades:
        if t.entry_date not in bench.index or t.exit_date not in bench.index:
            continue
        start = bench["close"].loc[t.entry_date] if t.entry_mode == "close" else bench["open"].loc[t.entry_date]
        end = bench["close"].loc[t.exit_date]
        if start <= 0:
            continue
        diffs.append(t.net_return_pct - (end / start - 1) * 100)
    return math.fsum(diffs) / len(diffs) if diffs else None


def by_market_state(trades, bench) -> dict:
    """신호일 벤치 종가가 20일 단순이동평균 이상이면 "up", 아니면 "down". 20봉이 안 쌓인 날은 뺀다."""
    ma20 = bench["close"].rolling(20).mean()
    groups = {"up": [], "down": []}
    for t in trades:
        d = t.signal_date
        if d not in bench.index or pd.isna(ma20.loc[d]):
            continue
        groups["up" if bench["close"].loc[d] >= ma20.loc[d] else "down"].append(t)
    return {state: summarize(group) for state, group in groups.items()}


# ── 대조군 ──

CONTROL_SEED = 20261102
CONTROL_REPEATS = 20
CONTROL_K = 3


@dataclass(frozen=True)
class ControlSummary:
    mean_n: float
    mean_expectancy_pct: "float | None"
    mean_win_rate: "float | None"


def control_runs(days, frames, entry_mode, *, bucket, seed=CONTROL_SEED, repeats=CONTROL_REPEATS,
                 k=CONTROL_K, **sim_kwargs) -> list:
    """같은 날 같은 후보 풀에서 무작위 k 개를 골라 같은 규칙으로 청산한 거래 목록을 repeats 번 만든다(시드 고정)."""
    runs = []
    for r in range(repeats):
        rng = random.Random(seed + r)
        fake_days = []
        for day in days:
            picks = rng.sample(day.pool, min(k, len(day.pool)))
            fake_days.append(DayResult(day.date, day.pool, [Signal(c, day.date, 0, 0.0, bucket) for c in picks]))
        runs.append(simulate_picks(fake_days, frames, entry_mode, bucket=bucket, top_n=None, **sim_kwargs))
    return runs


def summarize_control(runs) -> ControlSummary:
    sums = [summarize(run) for run in runs]
    if not sums:
        return ControlSummary(0.0, None, None)
    traded = [s for s in sums if s.n > 0]
    return ControlSummary(
        mean_n=math.fsum(s.n for s in sums) / len(sums),
        mean_expectancy_pct=math.fsum(s.expectancy_pct for s in traded) / len(traded) if traded else None,
        mean_win_rate=math.fsum(s.win_rate for s in traded) / len(traded) if traded else None)


# ── 민감도 ──

SENS_TARGETS = (5.2, 6.5, 7.8)
SENS_STOPS = (2.4, 3.0, 3.6)
SENS_HOLDS = (3, 5, 7)
SENS_SLIPPAGES = (0.1, 0.3)
SENS_BASE = (6.5, 3.0, 5)


@dataclass(frozen=True)
class SensRow:
    target_pct: float
    stop_pct: float
    hold_days: int
    slippage_pct: float
    n: int
    expectancy_pct: "float | None"


def sensitivity(days, frames, entry_mode, *, bucket, top_n=3) -> list:
    """익절 x 손절 x 보유 27칸 격자(슬리피지 0) + 기준 규칙의 슬리피지 0.1, 0.3 두 줄 = 29줄."""
    def row(target, stop, hold, slip):
        trades = simulate_picks(days, frames, entry_mode, bucket=bucket, top_n=top_n,
                                target_ratio=round(1 + target / 100, 6), stop_ratio=round(1 - stop / 100, 6),
                                hold_days=hold, slippage_pct=slip)
        s = summarize(trades)
        return SensRow(target, stop, hold, slip, s.n, s.expectancy_pct)

    rows = [row(t, s, h, 0.0) for t in SENS_TARGETS for s in SENS_STOPS for h in SENS_HOLDS]
    rows += [row(*SENS_BASE, slip) for slip in SENS_SLIPPAGES]
    return rows


# ── 점검표 ──


@dataclass(frozen=True)
class CheckItem:
    label: str
    passed: bool
    detail: str


UNKNOWN = "판단 불가"


def evaluate_checklist(*, summary, control_expectancy, yearly, slip03_expectancy) -> list:
    """결론을 단정하지 않고 증거만 낸다. 필요한 값이 없으면 통과가 아니라 "판단 불가"로 둔다."""
    items = [CheckItem("거래 100건 이상", summary.n >= 100, f"{summary.n}건")]
    if yearly:
        plus = sum(1 for s in yearly.values() if s.expectancy_pct is not None and s.expectancy_pct > 0)
        items.append(CheckItem("플러스 연도 과반", plus * 2 > len(yearly), f"{plus}/{len(yearly)}개 연도가 플러스"))
    else:
        items.append(CheckItem("플러스 연도 과반", False, UNKNOWN))
    if control_expectancy is None or summary.expectancy_pct is None:
        items.append(CheckItem("대조군보다 기대 손익 높음", False, UNKNOWN))
    else:
        items.append(CheckItem("대조군보다 기대 손익 높음", summary.expectancy_pct > control_expectancy,
                               f"추천 {summary.expectancy_pct:.2f}% / 대조군 {control_expectancy:.2f}%"))
    if slip03_expectancy is None:
        items.append(CheckItem("슬리피지 0.3% 후에도 기대 손익 > 0", False, UNKNOWN))
    else:
        items.append(CheckItem("슬리피지 0.3% 후에도 기대 손익 > 0", slip03_expectancy > 0, f"{slip03_expectancy:.2f}%"))
    return items
