import numpy as np
import pytest

from backtest.analysis.features import FEATURE_COLUMNS, compute_features
from backtest.signals import RAW_COLUMNS
from bt_helpers import flat_rows, make_frame, trending_rows
from strategy import calculate_technical_indicators


def test_features_match_app_on_last_60_window():
    frame = make_frame(trending_rows(120))
    feats = compute_features(frame)
    for pos in (70, 100, 119):
        t = frame.index[pos]
        win = frame.loc[:t, RAW_COLUMNS].tail(60)
        app = calculate_technical_indicators(win).iloc[-1]
        close = frame.loc[t, "close"]
        row = feats.loc[t]
        assert row["gap20"] == pytest.approx((close - app["ma20"]) / app["ma20"])
        assert row["ma_gap"] == pytest.approx((app["ma5"] - app["ma20"]) / app["ma20"])
        assert row["rsi"] == pytest.approx(app["rsi14"])
        assert row["vol_ratio"] == pytest.approx(app["volume"] / (app["vol_ma5"] + 1))
        assert row["pctb"] == pytest.approx((close - app["bb_lower"]) / (app["bb_upper"] - app["bb_lower"]))


def test_features_do_not_use_future_rows():
    frame = make_frame(trending_rows(120))
    t = frame.index[90]
    before = compute_features(frame).loc[t]
    changed = frame.copy()
    for col in ("open", "high", "low", "close"):
        changed.loc[changed.index > t, col] = 999_999
    changed.loc[changed.index > t, "volume"] = 7
    after = compute_features(changed).loc[t]
    assert list(before.index) == list(FEATURE_COLUMNS)
    assert np.allclose(before.to_numpy(), after.to_numpy(), equal_nan=True)


def test_atr_pct_hand_computed():
    rows = [(1000, 1010, 990, 1000, 100_000)] * 29 + [(1000, 1050, 1040, 1045, 100_000)]
    frame = make_frame(rows)
    # 마지막 날 참범위 = max(10, |1050-1000|, |1040-1000|) = 50, 앞 13일은 20 → (13*20 + 50) / 14
    expected = (13 * 20 + 50) / 14 / 1045
    assert compute_features(frame).iloc[-1]["atr_pct"] == pytest.approx(expected)


def test_short_frame_all_nan():
    feats = compute_features(make_frame(flat_rows(20)))
    assert list(feats.columns) == list(FEATURE_COLUMNS)
    assert len(feats) == 20
    assert feats.isna().all().all()


def test_pctb_nan_when_band_zero():
    feats = compute_features(make_frame(flat_rows(40)))
    assert np.isnan(feats.iloc[-1]["pctb"])
