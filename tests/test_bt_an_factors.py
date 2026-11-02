import numpy as np
import pandas as pd
import pytest

from backtest.analysis.bootstrap import BootResult
from backtest.analysis.factors import (FACTOR_COLUMNS, assign_bins, bin_table, holm, judge, merge_small_bins,
                                       rank_corr_test, train_edges, yearly_signs)
from backtest.analysis.panel import PANEL_COLUMNS, TRAIN_END


def _panel(seed=0, n_days=900, per_day=4, slope_col=None, slope=0.0):
    rng = np.random.default_rng(seed)
    dates = np.repeat(pd.bdate_range("2019-01-01", periods=n_days).to_numpy(), per_day)
    n = len(dates)
    data = {
        "date": pd.to_datetime(dates), "code": ["X"] * n, "bucket": 100_000,
        "gap20": rng.normal(0.03, 0.05, n), "ma_gap": rng.normal(0.01, 0.03, n),
        "rsi": rng.uniform(20, 80, n), "vol_ratio": rng.lognormal(0, 0.5, n),
        "pctb": rng.uniform(-0.2, 1.2, n), "atr_pct": rng.uniform(0.01, 0.06, n),
        "passed": rng.random(n) < 0.5, "picked": False,
        "score": rng.choice([60.0, 65.0, 70.0, 75.0, 80.0, 85.0], n),
    }
    noise = rng.normal(0, 3.0, n)
    data["net_return_pct"] = noise
    if slope_col is not None:
        std = np.std(data[slope_col])
        data["net_return_pct"] = noise + slope * (data[slope_col] - np.mean(data[slope_col])) / std
    panel = pd.DataFrame(data)
    panel["period"] = np.where(panel["date"] <= TRAIN_END, "train", "test")
    return panel[list(PANEL_COLUMNS)]


def test_train_edges_use_only_train_rows():
    panel = _panel(seed=1)
    before = train_edges(panel)
    changed = panel.copy()
    test_rows = changed["period"] == "test"
    for col in ("ma_gap", "vol_ratio", "atr_pct"):
        changed.loc[test_rows, col] = 1e6
    assert train_edges(changed) == before
    assert len(before["ma_gap"]) == 3 and len(before["vol_ratio"]) == 4 and len(before["atr_pct"]) == 2
    assert before["gap20"] == [0, 0.03, 0.06] and before["rsi"] == [30, 45, 60, 70]
    assert before["pctb"] == [0, 0.5, 1] and before["score"] == [70, 80]


def test_assign_bins_boundaries():
    values = pd.Series([-1.0, 0.0, 0.029, 0.03, 0.059, 0.06, 9.0, np.nan])
    bins = assign_bins(values, [0, 0.03, 0.06])
    assert list(bins[:7]) == [0, 1, 1, 2, 2, 3, 3]
    assert np.isnan(bins.iloc[7])


def test_merge_small_bins_rule():
    assert merge_small_bins([50, 300, 400]) == [0, 0, 1]
    assert merge_small_bins([300, 50, 40, 500]) == [0, 0, 0, 1]
    assert merge_small_bins([300, 300, 300]) == [0, 1, 2]
    assert merge_small_bins([10]) == [0]


def test_rank_corr_detects_planted_relation():
    panel = _panel(seed=2, slope_col="gap20", slope=2.0)
    res = rank_corr_test(panel, "gap20", draws=300)
    assert res.point > 0.2
    assert res.lo > 0 and res.p < 0.05


def test_rank_corr_independent_not_significant():
    significant = 0
    for seed in range(10):
        panel = _panel(seed=100 + seed, n_days=300, per_day=4)
        ps = {col: rank_corr_test(panel, col, draws=200, seed=seed).p for col in FACTOR_COLUMNS}
        significant += sum(1 for p in holm(ps).values() if p is not None and p < 0.05)
    assert significant <= 2


def test_rank_corr_constant_column_is_none():
    panel = _panel(seed=3)
    panel["gap20"] = 0.04
    res = rank_corr_test(panel, "gap20", draws=100)
    assert res.point is None and res.p is None
    flat = _panel(seed=3)
    flat["net_return_pct"] = 1.0
    assert rank_corr_test(flat, "gap20", draws=100).point is None


def test_holm_known_values():
    adj = holm({"a": 0.01, "b": 0.04, "c": 0.03, "d": None})
    assert adj["a"] == pytest.approx(0.03)
    assert adj["b"] == pytest.approx(0.06)
    assert adj["c"] == pytest.approx(0.06)
    assert adj["d"] is None


def _boot(point, lo, hi):
    return BootResult(point, lo, hi, 0.01, 100, 100)


def test_judge_passes_only_when_train_and_test_agree():
    signs = {2019: 1, 2020: 1, 2021: 1, 2022: 1}
    assert judge(_boot(0.1, 0.05, 0.15), _boot(0.08, 0.02, 0.14), signs, 0.01) == "유의"
    assert judge(_boot(-0.1, -0.15, -0.05), _boot(-0.08, -0.14, -0.02), {y: -1 for y in signs}, 0.01) == "유의"
    assert judge(_boot(0.1, 0.05, 0.15), _boot(-0.08, -0.14, -0.02), signs, 0.01) == "근거 부족"


def test_judge_train_only_is_insufficient():
    signs = {2019: 1, 2020: 1, 2021: 1, 2022: 1}
    assert judge(_boot(0.1, 0.05, 0.15), _boot(0.08, -0.02, 0.14), signs, 0.01) == "근거 부족"   # 검증 구간이 0 을 포함
    assert judge(_boot(0.1, 0.05, 0.15), _boot(0.08, 0.02, 0.14), signs, 0.2) == "근거 부족"     # Holm 보정 후 학습 미통과
    assert judge(_boot(None, None, None), _boot(0.08, 0.02, 0.14), signs, None) == "판정 불가"


def test_judge_marks_unstable_when_years_disagree():
    signs = {2019: 1, 2020: -1, 2021: -1, 2022: 1}
    assert judge(_boot(0.1, 0.05, 0.15), _boot(0.08, 0.02, 0.14), signs, 0.01) == "불안정"


def test_score_factor_uses_passed_rows_only():
    panel = _panel(seed=4, n_days=600, per_day=6)
    z = (panel["score"] - panel["score"].mean()) / panel["score"].std()
    passed = panel["passed"]
    panel["net_return_pct"] = np.where(passed, 3.0 * z, -3.0 * z) + np.random.default_rng(9).normal(0, 1.0, len(panel))
    res = rank_corr_test(panel, "score", draws=200)
    assert res.point > 0.5                                  # 통과하지 않은 행의 반대 관계가 섞이면 이 값이 나올 수 없다
    signs = yearly_signs(panel, "score")
    assert set(signs) == set(panel["date"].dt.year) and all(v in (-1, 0, 1) for v in signs.values())


def test_factor_functions_accept_an_empty_object_dtype_panel():
    empty = pd.DataFrame(columns=list(PANEL_COLUMNS))             # build_panel 이 풀이 비었을 때 돌려주는 모양(열은 전부 object)
    for column in FACTOR_COLUMNS:
        assert rank_corr_test(empty, column, draws=50).point is None
        assert bin_table(empty, column, train_edges(empty)[column]) == []
        assert all(v == 0 for v in yearly_signs(empty, column).values())


def test_bin_table_merges_small_bins_and_reports_counts():
    panel = _panel(seed=5, n_days=400, per_day=4)
    edges = train_edges(panel)
    table = bin_table(panel, "gap20", edges["gap20"])
    assert sum(row["n"] for row in table) == len(panel)
    assert all(row["n"] >= 200 for row in table) or len(table) == 1
    assert bin_table(panel.iloc[0:0], "gap20", edges["gap20"]) == []
