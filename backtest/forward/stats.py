"""블록 부트스트랩 통계와 최대 낙폭.

판정(통과/불합격)에 쓰이는 값이라 정의를 고정한다.
- 재추출: 날짜 블록 단위(`backtest.analysis.bootstrap.block_indices`), 반복마다 순서대로 한 번씩 뽑는다.
- 낙폭: 가치 = (1 + 일간 수익률)의 누적곱, 시작 가치 1.0 도 첫 고점으로 센다.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from backtest.analysis.bootstrap import block_indices
from backtest.forward.registry import DRAWS, SEED

_CHUNK = 500  # 한 번에 처리하는 재추출 횟수(메모리 제한)


@dataclass(frozen=True)
class Stat:
    point: "float | None"
    lo: "float | None"
    hi: "float | None"
    p_one: "float | None"
    se: "float | None"
    n: int


@dataclass(frozen=True)
class Episode:
    peak_day: object
    trough_day: object
    end_day: object
    depth: float


def _empty() -> Stat:
    return Stat(None, None, None, None, None, 0)


def _summarize(point: float, samples: np.ndarray, n: int) -> Stat:
    lo, hi = np.percentile(samples, [2.5, 97.5])
    return Stat(float(point), float(lo), float(hi), float(np.mean(samples <= 0)),
                float(np.std(samples, ddof=1)), n)


def _chunks(n: int, block: int, draws: int, seed: int):
    """반복마다 block_indices 를 한 번씩 뽑아 (chunk x n) 위치 행렬을 차례로 내놓는다."""
    rng = np.random.default_rng(seed)
    for start in range(0, draws, _CHUNK):
        k = min(_CHUNK, draws - start)
        yield np.stack([block_indices(n, block, rng) for _ in range(k)])


def mean_stat(values, *, block: int, draws: int = DRAWS, seed: int = SEED) -> Stat:
    """평균의 점추정과 블록 부트스트랩 구간·한쪽 p(평균 <= 0 비율)·표준오차."""
    v = np.asarray(values, dtype=float)
    n = len(v)
    if n == 0:
        return _empty()
    samples = np.concatenate([v[idx].mean(axis=1) for idx in _chunks(n, block, draws, seed)])
    return _summarize(v.mean(), samples, n)


def _mdd_rows(daily: np.ndarray) -> np.ndarray:
    """(행 x 일) 일간 수익률 행렬의 행별 최대 낙폭. 시작 가치 1.0 이 첫 고점."""
    equity = np.cumprod(1.0 + daily, axis=1)
    peak = np.maximum(np.maximum.accumulate(equity, axis=1), 1.0)
    return (1.0 - equity / peak).max(axis=1).clip(min=0.0)


def max_drawdown(daily) -> float:
    """고점 대비 최대 하락(양수 비율). 비었거나 하락이 없으면 0.0."""
    d = np.asarray(daily, dtype=float)
    if len(d) == 0:
        return 0.0
    return float(_mdd_rows(d[None, :])[0])


def mdd_diff_stat(gate_daily, hold_daily, *, block: int, draws: int = DRAWS, seed: int = SEED) -> Stat:
    """점추정 max_drawdown(hold) - max_drawdown(gate). 두 계열을 같은 위치로 재추출한다(쌍 재추출)."""
    gate = np.asarray(gate_daily, dtype=float)
    hold = np.asarray(hold_daily, dtype=float)
    if len(gate) != len(hold):
        raise ValueError(f"두 계열의 길이가 같아야 한다: gate={len(gate)}, hold={len(hold)}")
    n = len(gate)
    if n == 0:
        return _empty()
    point = max_drawdown(hold) - max_drawdown(gate)
    samples = np.concatenate([_mdd_rows(hold[idx]) - _mdd_rows(gate[idx])
                              for idx in _chunks(n, block, draws, seed)])
    return _summarize(point, samples, n)


def drawdown_episodes(daily: pd.Series, threshold: float) -> list:
    """고점에서 threshold 이상 내려간 구간들. 고점부터 고점을 회복한 날(없으면 마지막 날)까지가 한 구간."""
    if len(daily) == 0:
        return []
    days = list(daily.index)
    equity = np.cumprod(1.0 + daily.to_numpy(dtype=float))
    episodes = []

    peak, peak_day = 1.0, days[0]  # 시작 가치 1.0 이 첫 고점(첫 날짜)
    trough, trough_day = 1.0, days[0]

    def close(end_day):
        if trough < peak and 1.0 - trough / peak >= threshold:
            episodes.append(Episode(peak_day, trough_day, end_day, float(1.0 - trough / peak)))

    for day, e in zip(days, equity):
        if e >= peak:
            close(day)
            peak, peak_day, trough, trough_day = e, day, e, day
        elif e < trough:
            trough, trough_day = e, day
    close(days[-1])
    return episodes


def window_drawdown(daily: pd.Series, start, end) -> float:
    """start~end(양끝 포함) 구간만 잘라 가치를 1.0 에서 다시 시작해 구한 최대 낙폭."""
    return max_drawdown(daily.loc[start:end])
