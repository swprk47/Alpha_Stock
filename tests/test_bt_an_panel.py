import numpy as np
import pandas as pd

from backtest.analysis.features import FEATURE_COLUMNS, compute_features
from backtest.analysis.panel import PANEL_COLUMNS, TRAIN_END, build_panel, passes_from_days, pools_from_days
from backtest.signals import DayResult, Signal
from backtest.simulate import simulate_trade
from bt_helpers import make_frame, trending_rows

CODES = ["A", "B", "C", "D", "E"]


def _setup(start="2026-01-05", n=70, codes=CODES):
    frames = {c: make_frame(trending_rows(n), start=start) for c in codes}
    features = {c: compute_features(f) for c, f in frames.items()}
    return frames, features, frames[codes[0]].index


def _sig(code, date, score):
    return Signal(code, date, score, 2.17, 100_000)


def test_panel_has_one_row_per_pool_candidate_day():
    frames, features, dates = _setup()
    pools = {d: ["A", "B"] for d in dates[30:40]}
    panel = build_panel(pools, frames, features, "next_open", bucket=100_000)
    assert len(panel) == 20
    assert set(panel["code"]) == {"A", "B"}
    assert list(panel.columns) == list(PANEL_COLUMNS)
    assert set(panel["date"]) == set(dates[30:40])


def test_panel_drops_unfinished_trades():
    frames, features, dates = _setup()
    pools = {dates[40]: ["A"], dates[-3]: ["A"], dates[-1]: ["A"]}
    panel = build_panel(pools, frames, features, "next_open", bucket=100_000)
    assert list(panel["date"]) == [dates[40]]            # 데이터 끝에서 보유 기간을 못 채운 신호는 0% 로 세지 않고 뺀다


def test_panel_flags_passed_and_picked():
    frames, features, dates = _setup()
    d = dates[40]
    pools = {d: CODES}
    passes = {d: [_sig("A", d, 85), _sig("B", d, 80), _sig("C", d, 75), _sig("D", d, 70)]}
    panel = build_panel(pools, frames, features, "next_open", bucket=100_000, passes=passes)
    row = panel.set_index("code")
    assert list(row.loc[["A", "B", "C", "D", "E"], "passed"]) == [True, True, True, True, False]
    assert list(row.loc[["A", "B", "C", "D", "E"], "picked"]) == [True, True, True, False, False]
    assert row.loc["A", "score"] == 85 and row.loc["D", "score"] == 70
    assert np.isnan(row.loc["E", "score"])


def test_panel_period_split_at_train_end():
    frames, features, dates = _setup(start="2021-12-01", n=70)
    pools = {dates[15]: ["A"], dates[40]: ["A"]}
    assert dates[15] <= TRAIN_END < dates[40]
    panel = build_panel(pools, frames, features, "next_open", bucket=100_000).set_index("date")
    assert panel.loc[dates[15], "period"] == "train"
    assert panel.loc[dates[40], "period"] == "test"


def test_panel_net_return_matches_simulate_trade():
    frames, features, dates = _setup()
    d = dates[45]
    panel = build_panel({d: ["B"]}, frames, features, "next_open", bucket=100_000, slippage_pct=0.1)
    expected = simulate_trade(frames["B"], "B", d, "next_open", bucket=100_000, slippage_pct=0.1).net_return_pct
    assert panel.iloc[0]["net_return_pct"] == expected
    for col in FEATURE_COLUMNS:
        assert panel.iloc[0][col] == features["B"].loc[d, col] or (np.isnan(panel.iloc[0][col]) and np.isnan(features["B"].loc[d, col]))


def test_panel_empty_pool_returns_empty_frame_with_columns():
    frames, features, dates = _setup()
    for pools in ({}, {dates[40]: []}):
        panel = build_panel(pools, frames, features, "next_open", bucket=100_000)
        assert panel.empty and list(panel.columns) == list(PANEL_COLUMNS)


def test_pools_and_passes_from_days():
    frames, features, dates = _setup()
    sig = _sig("A", dates[40], 80)
    days = [DayResult(dates[40], ["A", "B"], [sig]), DayResult(dates[41], ["B"], [])]
    assert pools_from_days(days) == {dates[40]: ["A", "B"], dates[41]: ["B"]}
    assert passes_from_days(days) == {dates[40]: [sig], dates[41]: []}
    assert isinstance(dates[40], pd.Timestamp)
