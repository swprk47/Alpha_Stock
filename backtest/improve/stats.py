"""날짜 블록 부트스트랩 통계: 점추정·95% 구간·한쪽 p(표본에서 직접)·표준오차, 로그성장 초과, 최소 검출 효과(MDE).

분석 층의 `bootstrap_sums`는 양쪽 p만 주므로 같은 재추출(`block_indices`)을 여기서 다시 만들어 한쪽 p를 직접 센다.
"""
import math
from dataclasses import dataclass
from statistics import NormalDist
from typing import Callable

import numpy as np

from backtest.analysis.bootstrap import block_indices

BLOCK = 20
DRAWS = 20_000
SEED = 20261103
ANNUAL = 252
NEAR = 0.20            # 문턱의 ±20% 안이면 "경계"로 표시만 한다(판정은 바꾸지 않는다)


@dataclass(frozen=True)
class Stat:
    point: "float | None"
    lo: "float | None"
    hi: "float | None"
    p_one: "float | None"      # 한쪽 p = mean(재추출 표본 <= 0)
    se: "float | None"         # 재추출 표본의 표준편차
    n_days: int
    draws: int


def _none(n_days: int) -> Stat:
    return Stat(None, None, None, None, None, n_days, 0)


def bootstrap_stat(day_stats: np.ndarray, stat_fn: Callable[[np.ndarray], float], *, block: int = BLOCK,
                   draws: int = DRAWS, seed: int = SEED) -> Stat:
    """날짜별 합계 행렬(날짜 x k)의 날짜 블록을 복원 추출해 stat_fn(열별 합계)의 분포를 만든다."""
    arr = np.asarray(day_stats, dtype=float)
    n_days = len(arr)
    if n_days == 0:
        return _none(0)
    with np.errstate(all="ignore"):
        point = float(stat_fn(arr.sum(axis=0)))
        if not math.isfinite(point):
            return _none(n_days)
        rng = np.random.default_rng(seed)
        samples = np.array([float(stat_fn(arr[block_indices(n_days, block, rng)].sum(axis=0))) for _ in range(draws)])
    samples = samples[np.isfinite(samples)]
    if len(samples) == 0:
        return _none(n_days)
    lo, hi = np.percentile(samples, [2.5, 97.5])
    se = float(np.std(samples, ddof=1)) if len(samples) > 1 else None
    return Stat(point, float(lo), float(hi), float(np.mean(samples <= 0)), se, n_days, draws)


def _ratio(sums: np.ndarray) -> float:
    return sums[0] / sums[1]


def mean_stat(values, **kw) -> Stat:
    """일간 값의 평균."""
    values = np.asarray(values, dtype=float)
    return bootstrap_stat(np.column_stack([values, np.ones(len(values))]), _ratio, **kw)


def ratio_stat(sum_values, counts, **kw) -> Stat:
    """날짜별 합계 / 날짜별 건수의 합(거래당 평균)."""
    return bootstrap_stat(np.column_stack([np.asarray(sum_values, dtype=float), np.asarray(counts, dtype=float)]), _ratio, **kw)


def log_growth_excess(ret, other=None, **kw) -> Stat:
    """일간 log(1+ret) - log(1+other)의 평균 x 252(연환산). other 가 None 이면 현금(수익 0)과 비교한다.
    산술 평균 초과는 변동성이 큰 집중 계좌의 복리 성과를 과대평가하므로 로그 차이를 쓴다."""
    ret = np.asarray(ret, dtype=float)
    other = np.zeros(len(ret)) if other is None else np.asarray(other, dtype=float)
    diff = np.log1p(np.clip(ret, -0.999999, None)) - np.log1p(np.clip(other, -0.999999, None))
    return bootstrap_stat(np.column_stack([diff, np.ones(len(diff))]), lambda s: s[0] / s[1] * ANNUAL, **kw)


def significant(stat: Stat, alpha_adj: float) -> bool:
    """유의 = 점추정이 0보다 크고 한쪽 p 가 보정된 문턱 이하."""
    return stat.point is not None and stat.p_one is not None and stat.point > 0 and stat.p_one <= alpha_adj


def near_threshold(stat: Stat, alpha_adj: float) -> bool:
    return stat.p_one is not None and alpha_adj * (1 - NEAR) <= stat.p_one <= alpha_adj * (1 + NEAR)


def mde(se_train, train_days: int, test_days: int, n: int, *, alpha: float = 0.05, power: float = 0.80):
    """최소 검출 효과(정규 근사, 한쪽): (z_{1-alpha/n} + z_power) x se_train x sqrt(학습 일수 / 검증 일수). 추정치이며 확정이 아니다."""
    if se_train is None or train_days <= 0 or test_days <= 0 or n <= 0:
        return None
    dist = NormalDist()
    return (dist.inv_cdf(1 - alpha / n) + dist.inv_cdf(power)) * se_train * math.sqrt(train_days / test_days)
