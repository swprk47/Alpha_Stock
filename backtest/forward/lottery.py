"""후보 ① 복권형 종목 회피 신호: 월 최대 일수익률(MAX)과 특이변동성(IVOL)으로 상위 종목을 제외한다.

신호일 t의 값은 t 이하 행만 쓴다(month_rows가 보장).
"""
import math

import numpy as np
import pandas as pd

from backtest.forward.months import month_rows


def month_stats(frame, bench, signal_day, *, min_days=15):
    """신호일까지 그달의 (max_ret, ivol). 계산할 수 없으면 None.

    유효한 날 = 종목과 벤치마크 월 행에 모두 있고 두 ret이 모두 NaN이 아닌 날.
    ivol = 종목 ret을 벤치마크 ret에 절편 포함 최소제곱 회귀한 잔차의 표준편차(ddof=2).
    벤치마크 ret 분산이 0이면 종목 ret의 표준편차(ddof=1).
    """
    day = pd.Timestamp(signal_day)
    if day not in frame.index or bool(frame.loc[day, "halt"]):
        return None
    rows = month_rows(frame, day)
    if bool(rows["bad"].any()):
        return None
    brows = month_rows(bench, day)
    common = rows.index.intersection(brows.index)
    y = rows.loc[common, "ret"].astype(float)
    x = brows.loc[common, "ret"].astype(float)
    ok = y.notna() & x.notna()
    y, x = y[ok].to_numpy(), x[ok].to_numpy()
    if len(y) < min_days:
        return None
    max_ret = float(y.max())
    var_x = float(np.var(x))
    if not math.isfinite(var_x) or var_x == 0.0:
        return max_ret, float(np.std(y, ddof=1))
    beta = float(np.cov(x, y, bias=True)[0, 1]) / var_x
    alpha = float(y.mean()) - beta * float(x.mean())
    resid = y - (alpha + beta * x)
    return max_ret, float(np.std(resid, ddof=2))


def composite(stats):
    """MAX와 IVOL 각각의 백분위 순위(rank(average)/n)의 평균. 클수록 복권형."""
    if not stats:
        return {}
    df = pd.DataFrame.from_dict(stats, orient="index", columns=["max", "ivol"])
    n = len(df)
    score = (df["max"].rank(method="average") / n + df["ivol"].rank(method="average") / n) / 2.0
    return {code: float(v) for code, v in score.items()}


def _count(n, pct):
    return int(math.floor(round(n * pct, 9)))


def select(scores, prev_excluded, order, *, exclude_pct, reentry_pct):
    """(held, excluded). 점수 내림차순(동점은 order 앞선 코드 먼저)으로 앞 n_ex개를 제외하고,
    직전에 제외됐던 종목은 앞 n_re개 안이면 계속 제외한다. held는 order 순서.
    """
    pos = {code: i for i, code in enumerate(order)}
    far = len(order)

    def tie_key(code):
        return (pos.get(code, far), code)

    ranked = sorted(scores, key=lambda c: (-scores[c], *tie_key(c)))
    n = len(ranked)
    n_ex = _count(n, exclude_pct)
    n_re = _count(n, reentry_pct)
    excluded = set(ranked[:n_ex]) | (set(prev_excluded) & set(ranked[:n_re]))
    held = sorted((c for c in ranked if c not in excluded), key=tie_key)
    return held, excluded
