import numpy as np
import pandas as pd
import pytest

from backtest.analysis.risk import HORIZONS, by_regime, calibration, risk_by_horizon, risk_summary, simulate_paths
from bt_helpers import make_frame


def test_simulate_paths_shape_and_seed():
    ret = np.random.default_rng(0).normal(0, 0.01, 300)
    a = simulate_paths(ret, 63, paths=50, seed=1)
    b = simulate_paths(ret, 63, paths=50, seed=1)
    c = simulate_paths(ret, 63, paths=50, seed=2)
    assert a.shape == (50, 63)
    assert np.array_equal(a, b) and not np.array_equal(a, c)
    long = simulate_paths(ret, 700, paths=5, seed=1)               # 원본보다 긴 기간은 블록을 이어 붙여 채운다
    assert long.shape == (5, 700)


def test_simulate_paths_keeps_consecutive_blocks():
    ret = np.arange(300, dtype=float)
    path = simulate_paths(ret, 20, paths=1, block=5, seed=3)[0]
    for start in range(0, 20, 5):
        chunk = path[start:start + 5]
        assert list(chunk) == list(range(int(chunk[0]), int(chunk[0]) + 5))


def test_risk_summary_known_distribution():
    paths = np.array([[0.10, 0.0], [-0.25, 0.0], [0.05, 0.05], [-0.10, -0.10]])
    out = risk_summary(paths)
    assert out["prob_profit"] == 0.5
    assert out["cvar5"] == pytest.approx(-0.25)                    # 하위 5% 이하는 가장 나쁜 경로 하나뿐
    assert out["mdd_median"] == pytest.approx(0.095)               # 낙폭은 양수(깊이): 0, 0.25, 0, 0.19
    assert out["prob_mdd_20"] == 0.25
    assert out["p5"] < 0


def test_risk_summary_losing_series_has_low_prob_profit():
    paths = simulate_paths(np.full(500, -0.001), 63, paths=100, seed=1)
    out = risk_summary(paths)
    assert out["prob_profit"] == 0.0 and out["p5"] < 0


def test_mdd_p95_not_less_than_median():
    ret = np.random.default_rng(1).normal(0, 0.01, 500)
    out = risk_summary(simulate_paths(ret, 252, paths=300, seed=2))
    assert out["mdd_p95"] >= out["mdd_median"] >= 0


def test_risk_by_horizon_has_all_horizons():
    ret = np.random.default_rng(2).normal(0.0005, 0.01, 400)
    out = risk_by_horizon(ret, paths=40, seed=1)
    assert set(out) == set(HORIZONS)


def test_by_regime_splits_by_ma20_state():
    closes = [100 + i for i in range(40)] + [140 - 2 * i for i in range(40)]
    bench = make_frame([(c, c, c, c, 1) for c in closes])
    daily = pd.DataFrame({"ret": np.arange(80, dtype=float)}, index=bench.index)
    out = by_regime(daily, bench)
    assert len(out["up"]) + len(out["down"]) == 80 - 19                  # 20봉이 안 쌓인 앞 19일은 뺀다
    assert 25.0 in out["up"] and 79.0 in out["down"]
    assert list(out["up"]) == sorted(out["up"]) and list(out["down"]) == sorted(out["down"])


def test_calibration_iid_returns_exceed_rate_near_five_percent():
    rng = np.random.default_rng(3)
    train, test = rng.normal(0.0005, 0.01, 2000), rng.normal(0.0005, 0.01, 2000)
    out = calibration(train, test, horizon=21, paths=2000, seed=1, draws=300)
    assert 0.02 < out["exceed_rate"] < 0.10
    assert out["ci_lo"] <= 0.05 <= out["ci_hi"]


def test_calibration_flags_regime_shift():
    rng = np.random.default_rng(4)
    out = calibration(rng.normal(0.0005, 0.01, 2000), rng.normal(-0.003, 0.02, 600), horizon=21, paths=2000, seed=1, draws=300)
    assert out["exceed_rate"] > 0.2
    assert out["ci_lo"] > 0.05


def test_calibration_none_when_test_period_shorter_than_horizon():
    assert calibration(np.zeros(100), np.zeros(10), horizon=21, paths=100, seed=1, draws=50) is None


def test_risk_empty_input_returns_none_values():
    empty = simulate_paths(np.array([]), 21, paths=10, seed=1)
    assert empty.shape[0] == 0
    out = risk_summary(empty)
    assert all(out[k] is None for k in ("prob_profit", "p5", "cvar5", "mdd_median", "mdd_p95", "prob_mdd_20"))
    assert calibration(np.array([]), np.zeros(100), horizon=21, paths=10, seed=1, draws=10) is None
