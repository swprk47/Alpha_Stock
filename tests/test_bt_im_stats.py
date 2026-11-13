import inspect
import math

import numpy as np
import pytest

from backtest.analysis.bootstrap import block_indices
from backtest.improve import stats
from backtest.improve.stats import (ANNUAL, BLOCK, DRAWS, SEED, Stat, bootstrap_stat, log_growth_excess, mde, mean_stat,
                                    near_threshold, ratio_stat, significant)


def test_defaults_are_the_pre_registered_values():
    assert (BLOCK, DRAWS, SEED, ANNUAL) == (20, 20_000, 20261103, 252)
    params = inspect.signature(bootstrap_stat).parameters
    assert params["block"].default == 20 and params["draws"].default == 20_000 and params["seed"].default == 20261103


def test_same_seed_same_result():
    values = np.random.default_rng(0).normal(1.0, 3.0, 300)
    assert mean_stat(values, draws=300, seed=7) == mean_stat(values, draws=300, seed=7)


def test_one_sided_p_is_the_direct_share_not_half_of_a_two_sided_p():
    day_stats = np.column_stack([np.random.default_rng(1).normal(0.1, 2.0, 200), np.ones(200)])
    draws, seed, block = 400, 11, 20
    res = bootstrap_stat(day_stats, lambda s: s[0] / s[1], draws=draws, seed=seed, block=block)
    rng = np.random.default_rng(seed)                              # 같은 재추출을 독립적으로 다시 만들어 센다
    samples = np.array([day_stats[block_indices(200, block, rng)].sum(axis=0) for _ in range(draws)])
    samples = samples[:, 0] / samples[:, 1]
    assert res.p_one == pytest.approx(float(np.mean(samples <= 0)))
    assert res.se == pytest.approx(float(np.std(samples, ddof=1)))


def test_ci_and_se_for_known_mean():
    values = np.random.default_rng(2).normal(2.0, 1.0, 400)
    res = mean_stat(values, draws=2000, seed=3)
    assert isinstance(res, Stat)
    assert res.lo <= res.point <= res.hi
    assert 0.03 < res.se < 0.09
    assert res.p_one < 0.01 and res.n_days == 400 and res.draws == 2000


def test_ratio_stat_is_sum_over_count():
    res = ratio_stat(np.array([2.0, 4.0, 0.0]), np.array([1.0, 1.0, 0.0]), draws=50, seed=1)
    assert res.point == pytest.approx(3.0)


def test_log_growth_excess_differs_from_arithmetic():
    ret = np.tile([0.05, -0.05], 100)
    res = log_growth_excess(ret, np.zeros(200), draws=100, seed=1)
    expected = (math.log(1.05) + math.log(0.95)) / 2 * ANNUAL
    assert res.point == pytest.approx(expected) and res.point < -0.2     # 산술 평균 차이는 0 이지만 복리로는 손해


def test_log_growth_cash_when_other_is_none():
    ret = np.random.default_rng(3).normal(0.001, 0.01, 150)
    assert log_growth_excess(ret, None, draws=60, seed=2) == log_growth_excess(ret, np.zeros(150), draws=60, seed=2)


def test_significant_requires_positive_point_and_small_p():
    good = Stat(0.5, 0.1, 0.9, 0.004, 0.1, 100, 1000)
    assert significant(good, 0.0125) and not significant(good, 0.001)
    negative = Stat(-0.5, -0.9, -0.1, 0.001, 0.1, 100, 1000)
    assert not significant(negative, 0.0125)
    assert not significant(Stat(None, None, None, None, None, 0, 0), 0.0125)


def test_near_threshold():
    assert near_threshold(Stat(0.1, 0, 0.2, 0.014, 0.1, 10, 100), 0.0125)
    assert not near_threshold(Stat(0.1, 0, 0.2, 0.02, 0.1, 10, 100), 0.0125)
    assert not near_threshold(Stat(None, None, None, None, None, 0, 0), 0.0125)


def test_mde_known_value():
    assert mde(1.0, 100, 100, 1) == pytest.approx(1.6449 + 0.8416, abs=1e-3)
    assert mde(1.0, 100, 100, 4) > mde(1.0, 100, 100, 1)               # 후보가 많을수록 문턱이 엄격해진다
    assert mde(1.0, 400, 100, 1) == pytest.approx(2 * (1.6449 + 0.8416), abs=1e-3)   # 검증 일수가 짧으면 표준오차가 커진다


def test_mde_none_for_missing_inputs():
    assert mde(None, 100, 100, 1) is None
    assert mde(1.0, 0, 100, 1) is None and mde(1.0, 100, 0, 1) is None and mde(1.0, 100, 100, 0) is None


def test_empty_returns_none_stat():
    res = bootstrap_stat(np.zeros((0, 2)), lambda s: s[0] / s[1], draws=50)
    assert res == Stat(None, None, None, None, None, 0, 0)
    assert stats.mean_stat(np.array([]), draws=50).point is None
