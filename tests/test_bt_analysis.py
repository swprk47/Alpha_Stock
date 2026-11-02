import pandas as pd
import pytest

import config
from bt_helpers import make_frame, make_trade
from backtest.metrics import (ControlSummary, benchmark_excess, by_market_state, control_runs, evaluate_checklist,
                              sensitivity, summarize, summarize_control)
from backtest.signals import DayResult, Signal
from backtest.simulate import simulate_picks

SIG = (10_000, 10_000, 10_000, 10_000, 100_000)
WIN = (10_000, 10_700, 10_000, 10_600, 1)       # 첫 날 목표가(10650)에 닿는다
LOSE = (10_000, 10_000, 9_600, 9_700, 1)        # 첫 날 손절가(9700)에 닿는다


@pytest.fixture(autouse=True)
def default_fees(monkeypatch):
    monkeypatch.setattr(config, "BUY_FEE_RATE", 0.00015)
    monkeypatch.setattr(config, "SELL_FEE_RATE", 0.00015)
    monkeypatch.setattr(config, "SELL_TAX_RATE", 0.0020)


def bench_frame(closes, opens=None):
    opens = opens or closes
    return make_frame([(o, max(o, c), min(o, c), c, 1) for o, c in zip(opens, closes)])


# ── 벤치마크 ──


def test_benchmark_excess_close_and_next_open_and_missing_dates():
    bench = bench_frame([100 + i for i in range(10)])                       # d0=100 ... d3=103
    close_trade = make_trade(6.2551, signal_date="2026-01-05", held_days=3)  # 진입 d0, 청산 d3
    assert benchmark_excess([close_trade], bench) == pytest.approx(6.2551 - 3.0)
    open_trade = make_trade(6.0, signal_date="2026-01-06", held_days=2, entry_mode="next_open")   # 진입 d1 시가 101, 청산 d3 종가 103
    assert benchmark_excess([open_trade], bench) == pytest.approx(6.0 - (103 / 101 - 1) * 100)
    outside = make_trade(5.0, signal_date="2027-01-04", held_days=3)         # 벤치에 없는 날짜는 제외
    assert benchmark_excess([close_trade, outside], bench) == pytest.approx(6.2551 - 3.0)
    assert benchmark_excess([outside], bench) is None and benchmark_excess([], bench) is None


# ── 시장 상태 ──


def test_market_state_uses_the_twenty_day_average_at_the_signal_date():
    closes = [100 + i for i in range(30)] + [60 - 2 * i for i in range(10)]   # 30일 상승 뒤 10일 급락
    bench = bench_frame(closes)
    dates = list(bench.index)
    at = lambda i: make_trade(1.0, signal_date=str(dates[i].date()))
    states = by_market_state([at(25), at(38), at(5)], bench)                 # 5번째 행은 20봉이 안 쌓여 제외
    assert (states["up"].n, states["down"].n) == (1, 1)


# ── 대조군 ──


def uniform_frame(pattern, n=30):
    return make_frame([SIG] + [pattern] * (n - 1))


def control_setup():
    frames = {c: uniform_frame(WIN if c in "ABC" else LOSE) for c in "ABCDEF"}
    dates = list(frames["A"].index)[:15]
    days = []
    for i, d in enumerate(dates):
        pool = list("ABCD") if i % 2 == 0 else list("CDEF")
        signals = [] if i % 3 == 2 else [Signal(pool[0], d, 70, 2.17, 100_000), Signal(pool[1], d, 65, 2.17, 100_000)]   # 3일에 하루는 신호가 없다
        days.append(DayResult(d, pool, signals))
    return days, frames


def test_control_runs_are_seeded_matched_to_signal_days_and_from_the_pool():
    days, frames = control_setup()
    pool_of = {d.date: d.pool for d in days}
    picks_of = {d.date: len(d.signals) for d in days}                       # 그날 전략이 고른 개수
    runs = control_runs(days, frames, "close", bucket=100_000, repeats=5)
    assert len(runs) == 5 and runs == control_runs(days, frames, "close", bucket=100_000, repeats=5)
    assert all(t.code in pool_of[t.signal_date] for run in runs for t in run)
    assert all(picks_of[t.signal_date] > 0 for run in runs for t in run)    # 신호가 없는 날에는 대조군도 사지 않는다(시장 타이밍 효과 제거)
    for run in runs:
        per_day = {}
        for t in run:
            per_day[t.signal_date] = per_day.get(t.signal_date, 0) + 1
        assert all(count <= picks_of[date] for date, count in per_day.items())    # 그날 전략과 같은 개수까지만
    assert runs != control_runs(days, frames, "close", bucket=100_000, repeats=5, seed=1)


def test_summarize_control_averages_the_runs():
    s = summarize_control([[make_trade(2.0)], [make_trade(-1.0)]])
    assert s == ControlSummary(mean_n=1.0, mean_expectancy_pct=pytest.approx(0.5), mean_win_rate=pytest.approx(0.5))
    empty = summarize_control([])
    assert (empty.mean_n, empty.mean_expectancy_pct, empty.mean_win_rate) == (0.0, None, None)


# ── 민감도 ──


def test_sensitivity_grid_has_29_rows_and_baseline_matches_summarize():
    frames = {c: uniform_frame(WIN if c == "A" else LOSE) for c in "AD"}
    dates = list(frames["A"].index)[:15]
    days = [DayResult(d, ["A", "D"], [Signal("A", d, 70, 2.17, 100_000), Signal("D", d, 65, 2.17, 100_000)]) for d in dates]
    rows = sensitivity(days, frames, "close", bucket=100_000)
    assert len(rows) == 29 and {r.slippage_pct for r in rows} == {0.0, 0.1, 0.3}
    base = next(r for r in rows if (r.target_pct, r.stop_pct, r.hold_days, r.slippage_pct) == (6.5, 3.0, 5, 0.0))
    expected = summarize(simulate_picks(days, frames, "close", bucket=100_000))
    assert base.n == expected.n > 0 and base.expectancy_pct == pytest.approx(expected.expectancy_pct)


# ── 점검표 ──


def test_checklist_items_and_unknowns():
    labels = ["거래 100건 이상", "플러스 연도 과반", "대조군보다 기대 손익 높음", "슬리피지 0.3% 후에도 기대 손익 > 0"]
    plus, minus = summarize([make_trade(1.0)]), summarize([make_trade(-1.0)])
    ok = evaluate_checklist(summary=summarize([make_trade(1.0)] * 100), control_expectancy=0.2,
                            yearly={2025: plus, 2026: plus}, slip03_expectancy=0.1)
    assert [i.label for i in ok] == labels and all(i.passed for i in ok)
    bad = evaluate_checklist(summary=summarize([make_trade(1.0)] * 99), control_expectancy=5.0,
                             yearly={2025: plus, 2026: minus}, slip03_expectancy=-0.1)
    assert [i.passed for i in bad] == [False, False, False, False]           # 99건 / 2년 중 1년(과반 아님) / 대조군 5.0 보다 낮음 / 슬리피지 후 음수
    unknown = evaluate_checklist(summary=summarize([]), control_expectancy=None, yearly={}, slip03_expectancy=None)
    assert [i.passed for i in unknown] == [False] * 4 and unknown[2].detail == "판단 불가" and unknown[3].detail == "판단 불가"
