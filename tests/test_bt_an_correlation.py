import numpy as np
import pandas as pd
import pytest

from backtest.analysis.correlation import (all_stop_vs_independent, pair_corr_mean, picks_vs_random, terciles_by_corr,
                                           unfiltered_pick_trades)
from backtest.signals import DayResult, Signal
from backtest.simulate import simulate_picks
from bt_helpers import make_frame, make_trade, trending_rows


def _scaled(rows, k):
    return [(o * k, h * k, l * k, c * k, v) for o, h, l, c, v in rows]


def _random_rows(n, seed):
    rng = np.random.default_rng(seed)
    close, rows = 10_000, []
    for _ in range(n):
        new = max(100, int(close * (1 + rng.normal(0, 0.02))))
        rows.append((close, max(close, new), min(close, new), new, 100_000))
        close = new
    return rows


def _sig(code, date, score=80):
    return Signal(code, date, score, 2.17, 100_000)


def test_pair_corr_perfectly_correlated_series_is_one():
    base = trending_rows(80)
    frames = {"A": make_frame(base), "B": make_frame(_scaled(base, 2)), "C": make_frame(_scaled(base, 3))}
    assert pair_corr_mean(frames, ["A", "B", "C"], frames["A"].index[-1]) == pytest.approx(1.0)


def test_pair_corr_none_with_too_few_common_days():
    frames = {"A": make_frame(trending_rows(80)), "B": make_frame(trending_rows(10))}
    assert pair_corr_mean(frames, ["A", "B"], frames["A"].index[-1]) is None
    assert pair_corr_mean(frames, ["A"], frames["A"].index[-1]) is None


def test_picks_vs_random_skips_days_with_fewer_than_three_picks():
    base = trending_rows(100)
    frames = {"A": make_frame(base), "B": make_frame(_scaled(base, 2)), "C": make_frame(_scaled(base, 3)),
              "D": make_frame(_random_rows(100, 5))}
    dates = frames["A"].index
    pool = ["A", "B", "C", "D"]
    days = [DayResult(dates[80], pool, [_sig("A", dates[80]), _sig("B", dates[80]), _sig("C", dates[80])]),
            DayResult(dates[81], pool, [_sig("A", dates[81]), _sig("B", dates[81]), _sig("C", dates[81])]),
            DayResult(dates[82], pool, [_sig("A", dates[82]), _sig("B", dates[82])]),
            DayResult(dates[83], pool, [])]
    out = picks_vs_random(days, frames, repeats=20, seed=1)
    assert out["n_days"] == 2 and out["n_skipped"] == 1                  # 추천이 1~2개인 날은 제외, 0개인 날은 세지 않는다
    assert out["picks_mean"] == pytest.approx(1.0)
    assert out["random_mean"] < 1.0


def _day_trades(day, reasons):
    return [make_trade(-3.0 if r == "stop" else 6.0, r, signal_date=day, code=f"C{i}") for i, r in enumerate(reasons)]


def test_all_stop_expected_is_cube_of_stop_rate():
    trades = []
    for i in range(10):
        reasons = ["stop"] * 3 if i < 2 else (["stop", "target", "target"] if i == 2 else ["target"] * 3)
        trades += _day_trades(pd.Timestamp("2026-01-05") + pd.Timedelta(days=i), reasons)
    out = all_stop_vs_independent(trades)
    assert out["n_days"] == 10
    assert out["p_stop"] == pytest.approx(7 / 30)
    assert out["expected"] == pytest.approx((7 / 30) ** 3)
    assert out["observed"] == pytest.approx(0.2)


def test_all_stop_excess_when_stops_cluster():
    rng = np.random.default_rng(0)
    trades = []
    for i in range(400):
        stop = rng.random() < 0.1
        trades += _day_trades(pd.Timestamp("2026-01-05") + pd.Timedelta(days=i), ["stop" if stop else "target"] * 3)
    out = all_stop_vs_independent(trades, draws=300)
    assert out["observed"] > out["expected"]
    assert out["diff"].point > 0 and out["diff"].lo > 0


def test_all_stop_ignores_days_without_three_trades():
    out = all_stop_vs_independent(_day_trades(pd.Timestamp("2026-01-05"), ["stop", "stop"]))
    assert out["n_days"] == 0 and out["observed"] is None and out["diff"].point is None


def test_terciles_empty_when_too_few_days():
    base = trending_rows(100)
    frames = {c: make_frame(_scaled(base, k)) for c, k in (("A", 1), ("B", 2), ("C", 3))}
    dates = frames["A"].index
    trades = []
    for i in range(5):
        trades += [make_trade(1.0, "target", signal_date=dates[80 + i], code=c) for c in "ABC"]
    assert terciles_by_corr(frames, trades) == []


def test_terciles_split_days_into_three_groups():
    base = trending_rows(200)
    frames = {c: make_frame(_scaled(base, k)) for c, k in (("A", 1), ("B", 2), ("C", 3))}
    dates = frames["A"].index
    trades = []
    for i in range(60):
        trades += [make_trade(float(i), "target", signal_date=dates[100 + i], code=c) for c in "ABC"]
    out = terciles_by_corr(frames, trades)
    assert [row["label"] for row in out] == ["낮음", "중간", "높음"]
    assert sum(row["n_days"] for row in out) == 60
    assert out[0]["mean_ret"] == pytest.approx(np.mean(range(20)))      # 상관이 모두 같으면 날짜순으로 나뉜다
    assert out[0]["lowest5_mean"] == pytest.approx(0.0)


def test_unfiltered_pick_trades_keep_every_pick_even_when_already_held():
    base = trending_rows(100)
    frames = {c: make_frame(_scaled(base, k)) for c, k in (("A", 1), ("B", 2), ("C", 3))}
    dates = frames["A"].index
    days = [DayResult(dates[60 + i], ["A", "B", "C"], [_sig(c, dates[60 + i]) for c in "ABC"]) for i in range(3)]
    unfiltered = unfiltered_pick_trades(days, frames, "close", bucket=100_000)
    assert len(unfiltered) == 9                                               # 매일 3개씩, 보유 중이어도 건너뛰지 않는다
    assert len(simulate_picks(days, frames, "close", bucket=100_000)) < 9     # 계좌 시뮬레이션은 같은 종목 중복 보유를 거른다
    assert all_stop_vs_independent(unfiltered, draws=50)["n_days"] == 3
    assert [t.signal_date for t in unfiltered] == sorted(t.signal_date for t in unfiltered)
