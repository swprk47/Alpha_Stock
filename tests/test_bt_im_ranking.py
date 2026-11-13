import numpy as np
import pandas as pd
import pytest

from backtest.analysis.features import compute_features
from backtest.data import prepare_frame
from backtest.improve.candidates import Combo, by_name
from backtest.improve.ranking import apply_filter, candidate_days, rank_signals
from backtest.signals import DayResult, Signal
from bt_helpers import make_frame, make_raw

BUCKET = 200_000
N = 70
T = 65                                   # 신호일의 행 번호


def _rows(closes, highs=None, lows=None, vols=None):
    n = len(closes)
    highs = highs if highs is not None else closes
    lows = lows if lows is not None else closes
    vols = vols if vols is not None else [100_000] * n
    return [(c, h, l, c, v) for c, h, l, v in zip(closes, highs, lows, vols)]


def _ramp(target, n=N):
    """t-20 행(45)의 종가는 100, t 행(65)의 종가는 target 이 되는 완만한 경로."""
    return [100.0] * 46 + list(np.linspace(100.0, target, 20)) + [target] * (n - 66)


def _setup(rows_by_code, bench_closes=None):
    frames = {code: make_frame(rows) for code, rows in rows_by_code.items()}
    features = {code: compute_features(frame) for code, frame in frames.items()}
    bench = make_frame(_rows(bench_closes if bench_closes is not None else _ramp(105.0)))
    date = next(iter(frames.values())).index[T]
    return frames, features, bench, date


def _day(date, pool, with_signals=False):
    signals = [Signal(c, date, 70, 2.17, BUCKET) for c in pool] if with_signals else []
    return DayResult(date, list(pool), signals)


def _codes(days):
    return [[s.code for s in day.signals] for day in days]


def test_s1_orders_by_relative_strength():
    frames, features, bench, date = _setup({"A": _rows(_ramp(120.0)), "B": _rows(_ramp(110.0)), "C": _rows(_ramp(130.0))})
    out = rank_signals(by_name("S1"), [_day(date, "BAC")], frames, features, bench, BUCKET)
    assert _codes(out) == [["C", "A", "B"]]                               # +25, +15, +5 (KODEX +5 를 뺀 값)


def test_s2_requires_breakout_and_orders_by_volume_ratio():
    flat = [100.0] * N
    def breakout(volume_at_t, close_at_t=105.0):
        closes, highs, vols = list(flat), list(flat), [100_000] * N
        closes[T] = highs[T] = close_at_t
        vols[T] = volume_at_t
        return _rows(closes, highs, None, vols)
    frames, features, bench, date = _setup({"A": breakout(300_000), "B": breakout(200_000), "C": breakout(300_000, 99.0)})
    out = rank_signals(by_name("S2"), [_day(date, "BAC")], frames, features, bench, BUCKET)
    assert _codes(out) == [["A", "B"]]                                    # C 는 돌파하지 못해 제외, 거래량 비율 큰 순


def test_s3_requires_close_above_ma60_and_orders_lowest_5day_return_first():
    def path(close60, end):
        closes = list(np.linspace(80.0, 120.0, T + 1)) + [end] * (N - T - 1)
        closes[T - 5] = close60
        return _rows(closes)
    falling = _rows(list(np.linspace(120.0, 80.0, N)))
    frames, features, bench, date = _setup({"A": path(122.4, 120.0), "B": path(116.5, 120.0), "C": falling})
    out = rank_signals(by_name("S3"), [_day(date, "BCA")], frames, features, bench, BUCKET)
    assert _codes(out) == [["A", "B"]]                                    # A(-2%) 가 B(+3%) 보다 먼저, 60일선 아래인 C 는 제외


def test_s4_orders_lowest_atr_first():
    closes = [100.0 + (i % 3) for i in range(N)]
    def ranged(pct):
        return _rows(closes, [c * (1 + pct) for c in closes], [c * (1 - pct) for c in closes])
    frames, features, bench, date = _setup({"A": ranged(0.01), "B": ranged(0.03), "C": ranged(0.015)})
    out = rank_signals(by_name("S4"), [_day(date, "BCA")], frames, features, bench, BUCKET)
    assert _codes(out) == [["A", "C", "B"]]


def _random_rows(seed, n=N):
    rng = np.random.default_rng(seed)
    close, rows = 100.0, []
    for _ in range(n):
        new = close * (1 + rng.normal(0.004, 0.01))
        rows.append((close, max(close, new) * 1.005, min(close, new) * 0.995, new, 100_000))
        close = new
    return rows


@pytest.mark.parametrize("name", ["S1", "S2", "S3", "S4"])
def test_rankers_do_not_use_future_rows(name):
    raws = {code: make_raw(_random_rows(i + 1)) for i, code in enumerate("ABCD")}
    bench_raw = make_raw(_random_rows(9))

    def run(change):
        frames, bench = {}, None
        for code, raw in raws.items():
            raw = raw.copy()
            if change:
                raw.iloc[T + 1:, 1:5] = raw.iloc[T + 1:, 1:5] * 5            # t 이후의 가격만 바꾼다(거래량은 그대로)
            frames[code] = prepare_frame(raw)
        bench_df = bench_raw.copy()
        if change:
            bench_df.iloc[T + 1:, 1:5] = bench_df.iloc[T + 1:, 1:5] * 5
        bench = prepare_frame(bench_df)
        features = {code: compute_features(frame) for code, frame in frames.items()}
        days = [_day(frames["A"].index[pos], "ABCD") for pos in range(60, T + 1)]
        return _codes(rank_signals(by_name(name), days, frames, features, bench, BUCKET))

    before, after = run(False), run(True)
    assert before == after
    assert any(before)                                                     # 비어 있는 결과끼리 같은 것이 아니어야 한다


def test_excludes_halt_vol_break_missing_rows_and_nonpositive_closes():
    base = {c: _rows(_ramp(120.0 + i)) for i, c in enumerate("ABCDE")}
    frames, features, bench, date = _setup(base)
    index = frames["A"].index
    frames["B"].loc[index[T], "halt"] = True                               # t 행이 거래정지
    frames["C"].loc[index[T], "vol_break"] = True                          # t 행이 분할 의심
    frames["D"].loc[index[T - 20], "halt"] = True                          # t-20 행이 거래정지(S1 비교 행)
    frames["E"] = frames["E"].iloc[:T]                                     # t 행이 없음
    out = rank_signals(by_name("S1"), [_day(date, "ABCDE")], frames, features, bench, BUCKET)
    assert _codes(out) == [["A"]]
    zero = {"A": _rows(_ramp(120.0)), "B": _rows([0.0 if i == 45 else c for i, c in enumerate(_ramp(130.0))])}
    frames2, features2, bench2, date2 = _setup(zero)
    out2 = rank_signals(by_name("S1"), [_day(date2, "AB")], frames2, features2, bench2, BUCKET)
    assert _codes(out2) == [["A"]]                                         # t-20 종가가 0 이하이면 제외(무한대 수익률 방지)


def test_s2_needs_at_least_15_valid_rows_in_the_window():
    flat = [100.0] * N
    closes, highs = list(flat), list(flat)
    closes[T] = highs[T] = 105.0
    frames, features, bench, date = _setup({"A": _rows(closes, highs), "B": _rows(closes, highs)})
    index = frames["A"].index
    for k in range(T - 20, T - 20 + 5):
        frames["A"].loc[index[k], "halt"] = True                           # 5개 제외 -> 유효 15개
    for k in range(T - 20, T - 20 + 6):
        frames["B"].loc[index[k], "halt"] = True                           # 6개 제외 -> 유효 14개
    out = rank_signals(by_name("S2"), [_day(date, "AB")], frames, features, bench, BUCKET)
    assert _codes(out) == [["A"]]


def test_fewer_than_three_pass_returns_only_those():
    closes = [100.0 + (i % 3) for i in range(N)]
    frames, features, bench, date = _setup({"A": _rows(closes), "B": _rows(closes)})
    out = rank_signals(by_name("S4"), [_day(date, ["A", "B", "MISSING"])], frames, features, bench, BUCKET)
    assert _codes(out) == [["A", "B"]]


def test_ties_keep_pool_order():
    closes = [100.0 + (i % 3) for i in range(N)]
    frames, features, bench, date = _setup({"A": _rows(closes), "B": _rows(closes)})
    out = rank_signals(by_name("S4"), [_day(date, ["B", "A"])], frames, features, bench, BUCKET)
    assert _codes(out) == [["B", "A"]]


def test_score_is_zero_for_all_signals():
    frames, features, bench, date = _setup({"A": _rows(_ramp(120.0)), "B": _rows(_ramp(110.0))})
    for name in ("S1", "S4"):
        out = rank_signals(by_name(name), [_day(date, "AB")], frames, features, bench, BUCKET)
        assert out[0].signals and all(s.score == 0 and s.risk_reward == 0.0 and s.bucket == BUCKET for s in out[0].signals)


def test_f1_keeps_signals_only_when_benchmark_above_ma20():
    up = make_frame(_rows([100.0 + i for i in range(N)]))
    down = make_frame(_rows([200.0 - i for i in range(N)]))
    date = up.index[T]
    day = _day(date, "AB", with_signals=True)
    kept = apply_filter(by_name("F1"), [day], up)
    blocked = apply_filter(by_name("F1"), [day], down)
    assert _codes(kept) == [["A", "B"]]
    assert _codes(blocked) == [[]]
    assert blocked[0].pool == ["A", "B"]                                   # 풀은 그대로 둔다


def test_f1_blocks_when_benchmark_row_missing_or_under_20_bars():
    bench = make_frame(_rows([100.0 + i for i in range(N)]))
    early = _day(bench.index[10], "A", with_signals=True)                   # 20봉이 안 쌓인 날
    missing = _day(pd.Timestamp("2030-01-01"), "A", with_signals=True)      # 벤치마크에 행이 없는 날
    out = apply_filter(by_name("F1"), [early, missing], bench)
    assert _codes(out) == [[], []]


def test_non_filter_candidates_leave_days_unchanged():
    bench = make_frame(_rows([100.0 + i for i in range(N)]))
    days = [_day(bench.index[T], "A", with_signals=True)]
    assert apply_filter(by_name("S1"), days, bench) is days


def test_pool_is_unchanged_by_ranking_and_filter():
    frames, features, bench, date = _setup({"A": _rows(_ramp(120.0)), "B": _rows(_ramp(110.0))})
    pool = ["B", "A", "MISSING"]
    assert rank_signals(by_name("S1"), [_day(date, pool)], frames, features, bench, BUCKET)[0].pool == pool
    assert apply_filter(by_name("F1"), [_day(date, pool, True)], bench)[0].pool == pool


def test_candidate_days_combo_applies_signal_then_filter():
    closes = [100.0 + (i % 3) for i in range(N)]
    frames, features, _, date = _setup({"A": _rows(closes), "B": _rows(closes)})
    up = make_frame(_rows([100.0 + i for i in range(N)]))
    down = make_frame(_rows([200.0 - i for i in range(N)]))
    combo = Combo(signal=by_name("S4"), filter=by_name("F1"), exit=None)
    allowed = candidate_days(combo, [_day(date, ["B", "A"])], frames, features, up, BUCKET)
    blocked = candidate_days(combo, [_day(date, ["B", "A"])], frames, features, down, BUCKET)
    assert _codes(allowed) == [["B", "A"]] and _codes(blocked) == [[]]
    base = [_day(date, "AB", True)]
    assert candidate_days(by_name("E2"), base, frames, features, up, BUCKET) is base      # 청산 후보는 신호를 바꾸지 않는다
