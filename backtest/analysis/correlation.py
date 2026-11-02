"""추천 3종목의 상관: 서로 비슷하게 움직이는 종목을 몰아 추천하는지, 3종목이 함께 손절되는 일이 독립 가정보다 잦은지 본다."""
import math
from collections import defaultdict

import numpy as np
import pandas as pd

from backtest.signals import daily_picks
from backtest.simulate import simulate_trade

from .bootstrap import DEFAULT_SEED, DRAWS, BootResult, bootstrap_sums

WINDOW = 60
MIN_COMMON_DAYS = 20
PICKS = 3
MIN_TERCILE_DAYS = 30
TERCILE_LABELS = ("낮음", "중간", "높음")


def _corr_matrix(frames: dict, codes: list, date, window: int) -> pd.DataFrame:
    """date 까지 최근 window 일 일간 수익률의 상관행렬(쌍마다 겹치는 날이 20일 이상일 때만, 아니면 NaN)."""
    rets = pd.concat({c: frames[c]["close"].loc[:date].tail(window + 1).pct_change() for c in codes}, axis=1, sort=True)
    return rets.corr(min_periods=MIN_COMMON_DAYS)


def _mean_offdiag(corr: pd.DataFrame, codes: list):
    values = corr.loc[codes, codes].to_numpy()[np.triu_indices(len(codes), k=1)]
    values = values[np.isfinite(values)]
    return float(values.mean()) if len(values) else None


def pair_corr_mean(frames: dict, codes: list, date, *, window: int = WINDOW):
    """date 까지 최근 window 일 일간 수익률의 쌍별 상관 평균. 종목이 2개 미만이거나 쌍마다 겹치는 날이 20일 미만이면 None."""
    if len(codes) < 2:
        return None
    return _mean_offdiag(_corr_matrix(frames, codes, date, window), codes)


def picks_vs_random(days: list, frames: dict, *, repeats: int = 20, seed: int = DEFAULT_SEED) -> dict:
    """정확히 3개를 추천한 날의 평균 쌍별 상관과, 같은 날 후보 풀에서 무작위 3개를 뽑았을 때의 평균 상관.
    n_skipped 는 추천이 1~2개라 제외한 날 수(추천이 0개인 날은 세지 않는다)."""
    rng = np.random.default_rng(seed)
    picks_vals, random_vals, skipped = [], [], 0
    for day in days:
        picks = daily_picks(day, PICKS)
        if not picks:
            continue
        if len(picks) < PICKS:
            skipped += 1
            continue
        pick_codes, pool = [s.code for s in picks], list(day.pool)
        if len(pool) < PICKS:
            continue
        matrix = _corr_matrix(frames, list(dict.fromkeys(pool + pick_codes)), day.date, WINDOW)       # 날마다 한 번만 만든다
        corr = _mean_offdiag(matrix, pick_codes)
        if corr is None:
            continue
        draws = [_mean_offdiag(matrix, [pool[i] for i in rng.choice(len(pool), size=PICKS, replace=False)])
                 for _ in range(repeats)]
        draws = [v for v in draws if v is not None]
        if not draws:
            continue
        picks_vals.append(corr)
        random_vals.append(math.fsum(draws) / len(draws))
    mean = lambda values: math.fsum(values) / len(values) if values else None
    return {"picks_mean": mean(picks_vals), "random_mean": mean(random_vals), "n_days": len(picks_vals), "n_skipped": skipped}


def unfiltered_pick_trades(days: list, frames: dict, entry_mode: str, *, bucket: int, slippage_pct: float = 0.1,
                           top_n: int = PICKS) -> list:
    """날짜순으로 그날 추천 상위 top_n 을 모두 거래로 만든다. 계좌 시뮬레이션(simulate_picks)과 달리 이미 보유 중인
    종목도 건너뛰지 않아서, 추천이 3개인 날이 거의 그대로 남는다(진입 불가·미완결 거래만 빠진다)."""
    trades = []
    for day in sorted(days, key=lambda d: d.date):
        for sig in daily_picks(day, top_n):
            trade = simulate_trade(frames[sig.code], sig.code, sig.date, entry_mode, score=sig.score, bucket=bucket,
                                   slippage_pct=slippage_pct)
            if trade is not None:
                trades.append(trade)
    return trades


def _three_trade_days(trades: list) -> list:
    """(신호일, 거래 3건) 목록, 날짜순. 정확히 3건인 날만."""
    groups = defaultdict(list)
    for t in trades:
        groups[t.signal_date].append(t)
    return [(date, group) for date, group in sorted(groups.items()) if len(group) == PICKS]


def all_stop_vs_independent(trades: list, *, seed: int = DEFAULT_SEED, draws: int = DRAWS) -> dict:
    """3건이 모두 손절된 날의 비율을, 건별 손절 확률의 세제곱(독립 가정)과 비교한다. diff 는 둘의 차이의 부트스트랩 구간."""
    days = _three_trade_days(trades)
    if not days:
        return {"p_stop": None, "observed": None, "expected": None, "diff": BootResult(None, None, None, None, 0, 0), "n_days": 0}
    stops = np.array([[t.exit_reason == "stop" for t in group] for _, group in days])
    p_stop = float(stops.mean())
    all_stop = stops.all(axis=1).astype(float)
    expected = p_stop ** PICKS
    stats = np.column_stack([all_stop - expected, np.ones(len(days))])
    diff = bootstrap_sums(stats, lambda s: s[0] / s[1], draws=draws, seed=seed)
    return {"p_stop": p_stop, "observed": float(all_stop.mean()), "expected": expected, "diff": diff, "n_days": len(days)}


def terciles_by_corr(frames: dict, trades: list) -> list:
    """3종목 평균 상관 3분위(낮음/중간/높음)별 그날 3종목 평균 손익의 평균·표준편차·하위 5% 평균.
    표본이 30일 미만이면 빈 목록. 상관이 같으면(반올림 9자리) 날짜순으로 나눈다."""
    rows = []
    for date, group in _three_trade_days(trades):
        corr = pair_corr_mean(frames, [t.code for t in group], date)
        if corr is not None:
            rows.append((round(corr, 9), math.fsum(t.net_return_pct for t in group) / PICKS))
    if len(rows) < MIN_TERCILE_DAYS:
        return []
    order = np.argsort([r[0] for r in rows], kind="stable")
    out = []
    for label, chunk in zip(TERCILE_LABELS, np.array_split(order, 3)):
        rets = sorted(rows[i][1] for i in chunk)
        k = max(1, math.ceil(len(rets) * 0.05 - 1e-9))
        out.append({"label": label, "n_days": len(rets), "mean_ret": float(np.mean(rets)),
                    "std_ret": float(np.std(rets, ddof=1)) if len(rets) > 1 else None,
                    "lowest5_mean": float(np.mean(rets[:k]))})
    return out
