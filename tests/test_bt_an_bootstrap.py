import numpy as np

from backtest.analysis.bootstrap import BootResult, block_indices, bootstrap_sums


def test_block_indices_length_and_consecutive():
    idx = block_indices(23, 5, np.random.default_rng(1))
    assert len(idx) == 23
    for start in range(0, 20, 5):
        chunk = idx[start:start + 5]
        assert list(chunk) == list(range(chunk[0], chunk[0] + 5))
    assert idx.min() >= 0 and idx.max() < 23


def test_block_indices_short_series_uses_whole_series():
    idx = block_indices(3, 5, np.random.default_rng(1))
    assert len(idx) == 3
    assert idx.min() >= 0 and idx.max() < 3


def _mean_stat(sums):
    return sums[0] / sums[1]


def _day_stats(values):
    values = np.asarray(values, dtype=float)
    return np.column_stack([values, np.ones(len(values))])


def test_bootstrap_same_seed_same_result():
    stats = _day_stats(np.random.default_rng(0).normal(1.0, 3.0, 300))
    a = bootstrap_sums(stats, _mean_stat, draws=300, seed=7)
    b = bootstrap_sums(stats, _mean_stat, draws=300, seed=7)
    assert a == b


def test_bootstrap_ci_contains_true_mean():
    stats = _day_stats(np.random.default_rng(1).normal(2.0, 1.0, 400))
    res = bootstrap_sums(stats, _mean_stat, draws=500, seed=3)
    assert isinstance(res, BootResult)
    assert res.lo <= res.point <= res.hi            # 구간은 표본 평균 주변이다(모집단 평균 2.0 은 표본 오차로 벗어날 수 있다)
    assert 1.5 < res.lo and res.hi < 2.5
    assert res.p < 0.05
    assert res.n_days == 400 and res.draws == 500


def test_bootstrap_p_large_when_mean_zero():
    stats = _day_stats(np.random.default_rng(2).normal(0.0, 1.0, 400))
    res = bootstrap_sums(stats, _mean_stat, draws=500, seed=3)
    assert res.p > 0.2
    assert res.lo < 0 < res.hi


def test_bootstrap_empty_returns_none():
    res = bootstrap_sums(np.zeros((0, 2)), _mean_stat, draws=100, seed=1)
    assert res == BootResult(None, None, None, None, 0, 0)
