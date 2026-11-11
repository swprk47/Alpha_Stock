"""블록 부트스트랩 통계와 최대 낙폭 테스트: 기대값은 손으로 계산해 적었다."""
import numpy as np
import pandas as pd
import pytest

from backtest.forward.registry import DRAWS, SEED
from backtest.forward.stats import (
    Episode,
    Stat,
    drawdown_episodes,
    max_drawdown,
    mdd_diff_stat,
    mean_stat,
    window_drawdown,
)


def test_mean_stat_point_and_one_sided_p():
    pos = mean_stat([0.01, 0.02, 0.03, 0.04], block=2, draws=500, seed=1)
    assert pos.point == pytest.approx(0.025)
    assert pos.n == 4
    assert pos.p_one == 0.0  # 전부 양수면 재추출 평균도 전부 양수
    assert pos.lo > 0 and pos.hi < 0.04 + 1e-12
    assert pos.se > 0

    neg = mean_stat([-0.01, -0.02, -0.03, -0.04], block=2, draws=500, seed=1)
    assert neg.point == pytest.approx(-0.025)
    assert neg.p_one == 1.0


def test_mean_stat_one_sided_p_on_skewed_sample_is_not_half_two_sided():
    # [-1, 1, 1, 1], block=1: 재추출 평균 <= 0 이려면 -1 이 4개 중 2개 이상.
    # P(Bin(4, 0.25) >= 2) = 1 - 81/256 - 108/256 = 67/256 = 0.2617
    s = mean_stat([-1.0, 1.0, 1.0, 1.0], block=1, draws=20_000, seed=7)
    assert s.point == pytest.approx(0.5)
    assert s.p_one == pytest.approx(67 / 256, abs=0.02)
    # 양측 p 의 절반 꼴이 아니라 P(<=0) 그 자체(0.5 에서 멀다)
    assert abs(s.p_one - 0.5) > 0.2


def test_mean_stat_same_seed_same_result_and_uses_registry_defaults():
    values = [0.01, -0.02, 0.03, 0.00, -0.01, 0.02, 0.04, -0.03, 0.01, 0.02]
    a = mean_stat(values, block=3)
    b = mean_stat(values, block=3)
    explicit = mean_stat(values, block=3, draws=DRAWS, seed=SEED)
    assert a == b == explicit
    other_seed = mean_stat(values, block=3, draws=500, seed=SEED + 1)
    assert other_seed != mean_stat(values, block=3, draws=500, seed=SEED)


def test_mean_stat_empty_input():
    assert mean_stat([], block=3, draws=100, seed=1) == Stat(None, None, None, None, None, 0)


def test_max_drawdown_known_series():
    # 가치 1.1 → 0.55 → 0.66, 고점 1.1 → 낙폭 1 - 0.55/1.1 = 0.5
    assert max_drawdown([0.10, -0.50, 0.20]) == pytest.approx(0.5)
    assert max_drawdown([0.01, 0.02, 0.03]) == 0.0
    assert max_drawdown([]) == 0.0
    # 시작 가치 1.0 이 첫 고점: 첫날 -20% 도 낙폭이다
    assert max_drawdown([-0.20, 0.10]) == pytest.approx(0.2)
    # 낙폭 두 번 중 큰 쪽: 1.0→0.9(0.1), 회복 후 1.2→0.6(0.5)
    assert max_drawdown([-0.10, 0.3333333333333333, 0.2, -0.5]) == pytest.approx(0.5)


def test_mdd_diff_point_and_paired_resampling():
    hold = [0.10, -0.50, 0.20, 0.05, -0.10, 0.03]
    # gate 가 hold 와 같으면 점추정 0, 같은 위치로 재추출하므로 모든 표본이 정확히 0
    same = mdd_diff_stat(hold, hold, block=2, draws=500, seed=3)
    assert same.point == 0.0
    assert same.lo == 0.0 and same.hi == 0.0
    assert same.p_one == 1.0
    assert same.se == 0.0
    assert same.n == 6

    # gate 가 계속 0% 면 mdd(gate)=0, 점추정 = mdd(hold) = 0.5
    flat = mdd_diff_stat([0.0] * 6, hold, block=2, draws=500, seed=3)
    assert flat.point == pytest.approx(0.5)
    assert flat.lo >= 0.0  # 표본 = mdd(hold 재추출) - 0 >= 0


def test_mdd_diff_stat_rejects_unequal_length_and_handles_empty():
    with pytest.raises(ValueError):
        mdd_diff_stat([0.01, 0.02], [0.01], block=1, draws=10, seed=1)
    assert mdd_diff_stat([], [], block=1, draws=10, seed=1) == Stat(None, None, None, None, None, 0)


def _series(equity):
    """가치 경로(첫 값=시작 가치) → 첫날 수익률 0 으로 시작하는 일간 수익률 Series."""
    eq = np.array(equity, dtype=float)
    rets = np.concatenate([[0.0], eq[1:] / eq[:-1] - 1.0])
    return pd.Series(rets, index=pd.bdate_range("2024-01-01", periods=len(eq)))


def test_drawdown_episodes_split_on_recovery():
    daily = _series([100, 80, 100, 101, 70])
    days = daily.index
    eps = drawdown_episodes(daily, 0.15)
    assert len(eps) == 2
    assert eps[0] == Episode(days[0], days[1], days[2], pytest.approx(0.20))
    assert eps[1].peak_day == days[3]
    assert eps[1].trough_day == days[4]
    assert eps[1].end_day == days[4]  # 끝까지 회복 못 함 → 마지막 날
    assert eps[1].depth == pytest.approx(1 - 70 / 101)  # 0.30693...


def test_drawdown_episodes_ignores_small_dips():
    daily = _series([100, 90, 100, 95, 100])  # 10%, 5% 하락
    assert drawdown_episodes(daily, 0.15) == []
    assert len(drawdown_episodes(daily, 0.10 - 1e-9)) == 1  # 임계값을 10% 바로 아래로 낮추면 10% 하락만 잡힌다


def test_drawdown_episodes_trough_is_lowest_point_inside_episode():
    daily = _series([100, 90, 70, 85, 100, 120])
    days = daily.index
    (ep,) = drawdown_episodes(daily, 0.15)
    assert ep.peak_day == days[0]
    assert ep.trough_day == days[2]
    assert ep.end_day == days[4]
    assert ep.depth == pytest.approx(0.30)


def test_window_drawdown_uses_only_the_window():
    daily = pd.Series([0.10, -0.50, 0.20, 0.0, 0.10, -0.10],
                      index=pd.bdate_range("2024-01-01", periods=6))
    assert max_drawdown(daily) == pytest.approx(0.5)
    # 뒤 세 날만: 가치 1.0 → 1.1 → 0.99, 낙폭 1 - 0.99/1.1 = 0.1 (앞의 50% 낙폭은 제외)
    assert window_drawdown(daily, daily.index[3], daily.index[5]) == pytest.approx(0.1)
    # 구간 끝은 포함(inclusive)
    assert window_drawdown(daily, daily.index[0], daily.index[1]) == pytest.approx(0.5)
