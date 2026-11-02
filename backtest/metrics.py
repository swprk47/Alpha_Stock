"""백테스트 지표: 요약, 연도별, 점수대별, 시장 대비, 대조군, 민감도, 점검표."""
import math
from collections import defaultdict
from dataclasses import dataclass


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
