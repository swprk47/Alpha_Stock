"""날짜 블록 부트스트랩: 날짜별 합계를 연속 구간(블록) 단위로 복원 추출해 신뢰구간과 p값을 구한다.

같은 날 종목들은 함께 움직이고 5일 보유라 이웃한 날의 거래가 겹치므로, 거래 단위가 아니라 날짜 블록 단위로 뽑는다.
"""
import math
from dataclasses import dataclass
from typing import Callable

import numpy as np

BLOCK = 5
DRAWS = 5000
DEFAULT_SEED = 20261103


@dataclass(frozen=True)
class BootResult:
    point: "float | None"
    lo: "float | None"
    hi: "float | None"
    p: "float | None"
    n_days: int
    draws: int


def block_indices(n_days: int, block: int, rng: np.random.Generator) -> np.ndarray:
    """길이 n_days 의 위치 배열: 연속 block 개 구간을 무작위 시작점에서 이어 붙이고 n_days 로 자른다."""
    if n_days <= 0:
        return np.zeros(0, dtype=int)
    block = min(block, n_days)
    n_blocks = -(-n_days // block)
    starts = rng.integers(0, n_days - block + 1, size=n_blocks)
    return (starts[:, None] + np.arange(block)).ravel()[:n_days]


def _none(n_days: int) -> BootResult:
    return BootResult(None, None, None, None, n_days, 0)


def bootstrap_sums(day_stats: np.ndarray, stat_fn: Callable[[np.ndarray], float], *,
                   block: int = BLOCK, draws: int = DRAWS, seed: int = DEFAULT_SEED) -> BootResult:
    """day_stats(날짜 x k 합계 행렬)의 날짜 블록을 재추출해 stat_fn(열별 합계)의 분포를 만든다."""
    day_stats = np.asarray(day_stats, dtype=float)
    n_days = len(day_stats)
    if n_days == 0:
        return _none(0)
    with np.errstate(all="ignore"):
        point = float(stat_fn(day_stats.sum(axis=0)))
        if not math.isfinite(point):
            return _none(n_days)
        rng = np.random.default_rng(seed)
        samples = np.array([float(stat_fn(day_stats[block_indices(n_days, block, rng)].sum(axis=0)))
                            for _ in range(draws)])
    samples = samples[np.isfinite(samples)]
    if len(samples) == 0:
        return _none(n_days)
    lo, hi = np.percentile(samples, [2.5, 97.5])
    p = min(1.0, 2 * min(float(np.mean(samples <= 0)), float(np.mean(samples >= 0))))
    return BootResult(point, float(lo), float(hi), p, n_days, draws)
