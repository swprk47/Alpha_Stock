"""거래 재추출 위험 분포: 실제 일별 계좌 수익률을 날짜 블록으로 다시 뽑아 가상의 계좌 곡선을 만든다.

정규분포를 가정하지 않으므로 갭하락 손절 같은 꼬리가 그대로 남는다. 미래를 맞히는 것이 아니라
과거 분포가 이어진다고 가정한 범위다. 낙폭은 양수(깊이)로 적는다.
"""
import math

import numpy as np
import pandas as pd

from .bootstrap import BLOCK, DEFAULT_SEED, bootstrap_sums

HORIZONS = (21, 63, 252, 756)
PATHS = 5000
EXPECTED_EXCEED = 0.05
_RISK_KEYS = ("prob_profit", "p5", "cvar5", "mdd_median", "mdd_p95", "prob_mdd_20")


def simulate_paths(daily_ret: np.ndarray, horizon: int, *, paths: int = PATHS, block: int = BLOCK,
                   seed: int = DEFAULT_SEED) -> np.ndarray:
    """(paths x horizon) 일간 수익률. 경로마다 연속 block 일 구간을 무작위 시작점에서 이어 붙여 horizon 일을 채운다."""
    daily_ret = np.asarray(daily_ret, dtype=float)
    n = len(daily_ret)
    if n == 0:
        return np.zeros((0, horizon))
    block = min(block, n)
    rng = np.random.default_rng(seed)
    n_blocks = -(-horizon // block)
    starts = rng.integers(0, n - block + 1, size=(paths, n_blocks))
    index = (starts[:, :, None] + np.arange(block)).reshape(paths, -1)[:, :horizon]
    return daily_ret[index]


def risk_summary(path_returns: np.ndarray) -> dict:
    """기간 후 이익 확률, 최종 수익률 하위 5%(p5)와 그 이하 평균(cvar5), 최대 낙폭(깊이)의 중앙값·95퍼센타일, 낙폭 20% 이상 확률."""
    if path_returns.size == 0:
        return {key: None for key in _RISK_KEYS}
    curves = np.cumprod(1 + path_returns, axis=1)
    final = curves[:, -1] - 1
    peak = np.maximum.accumulate(np.concatenate([np.ones((len(curves), 1)), curves], axis=1), axis=1)[:, 1:]
    depth = (1 - curves / peak).max(axis=1)
    p5 = float(np.percentile(final, 5))
    return {"prob_profit": float(np.mean(final > 0)), "p5": p5, "cvar5": float(final[final <= p5].mean()),
            "mdd_median": float(np.median(depth)), "mdd_p95": float(np.percentile(depth, 95)),
            "prob_mdd_20": float(np.mean(depth >= 0.20))}


def risk_by_horizon(daily_ret: np.ndarray, *, horizons=HORIZONS, paths: int = PATHS, seed: int = DEFAULT_SEED) -> dict:
    return {h: risk_summary(simulate_paths(daily_ret, h, paths=paths, seed=seed)) for h in horizons}


def by_regime(daily: pd.DataFrame, bench: pd.DataFrame) -> dict:
    """**전날** 벤치 종가가 20일 단순이동평균 이상이면 "up", 아니면 "down"인 날의 일간 수익률(날짜순).
    투자할 때 알 수 있는 상태로 나눠야 하므로 그날의 움직임이 그날의 분류를 정하지 않게 하루 늦춘다.
    전날의 20일선이 아직 없는 날은 뺀다."""
    close = bench["close"]
    ma20 = close.rolling(20).mean()
    previous_up = (close >= ma20).where(ma20.notna()).shift(1)
    up, down = [], []
    for date, ret in daily["ret"].items():
        if date not in previous_up.index or pd.isna(previous_up.loc[date]):
            continue
        (up if previous_up.loc[date] else down).append(float(ret))
    return {"up": np.array(up), "down": np.array(down)}


def calibration(train_ret: np.ndarray, test_ret: np.ndarray, *, horizon: int = 21, paths: int = PATHS,
                seed: int = DEFAULT_SEED, draws: int = 5000):
    """Kupiec 방식 점검: 학습 기간만으로 만든 horizon 일 누적수익 분포의 하위 5% 경계(p5)를, 검증 기간의 모든
    연속 horizon 일 구간(중첩)이 넘어서 나쁜 비율(exceed_rate, 기대 0.05)로 확인한다. 구간은 horizon 일 블록 부트스트랩."""
    train_ret, test_ret = np.asarray(train_ret, dtype=float), np.asarray(test_ret, dtype=float)
    if len(train_ret) == 0 or len(test_ret) < horizon:
        return None
    sim = simulate_paths(train_ret, horizon, paths=paths, seed=seed)
    p5 = float(np.percentile(np.prod(1 + sim, axis=1) - 1, 5))
    cum = np.concatenate([[0.0], np.cumsum(np.log1p(np.clip(test_ret, -0.999999, None)))])
    windows = np.exp(cum[horizon:] - cum[:-horizon]) - 1
    exceed = (windows < p5).astype(float)
    stats = np.column_stack([exceed, np.ones(len(exceed))])
    res = bootstrap_sums(stats, lambda s: s[0] / s[1] - EXPECTED_EXCEED, block=horizon, draws=draws, seed=seed)
    rate = float(exceed.mean())
    return {"p5": p5, "exceed_rate": rate, "expected": EXPECTED_EXCEED, "n_windows": int(len(exceed)),
            "ci_lo": None if res.lo is None else res.lo + EXPECTED_EXCEED,
            "ci_hi": None if res.hi is None else res.hi + EXPECTED_EXCEED, "p": res.p}
