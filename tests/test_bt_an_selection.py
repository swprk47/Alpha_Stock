import numpy as np
import pandas as pd

from backtest.analysis.selection import selection_effect


def _panel(seed, boost, n_days=500, per_day=6, picks=2):
    rng = np.random.default_rng(seed)
    dates = np.repeat(pd.bdate_range("2019-01-01", periods=n_days).to_numpy(), per_day)
    picked = np.tile([True] * picks + [False] * (per_day - picks), n_days)
    if boost == 0:                                          # 추천이 무작위로 뽑힌 경우
        picked = np.concatenate([rng.permutation(picked[i:i + per_day]) for i in range(0, len(picked), per_day)])
    net = rng.normal(0, 3.0, len(dates)) + np.where(picked, boost, 0.0)
    return pd.DataFrame({"date": pd.to_datetime(dates), "picked": picked, "net_return_pct": net})


def test_selection_effect_positive_when_picks_beat_pool():
    res = selection_effect(_panel(1, boost=2.0), draws=300)
    assert res.point > 1.0                                  # 풀 평균에 추천이 섞여 있어 2.0 이 아니라 2 x (1 - 2/6) 근처
    assert res.lo > 0 and res.p < 0.05


def test_selection_effect_zero_when_picks_random():
    res = selection_effect(_panel(2, boost=0.0), draws=300)
    assert res.lo < 0 < res.hi


def test_selection_effect_none_without_picks():
    panel = _panel(3, boost=0.0)
    panel["picked"] = False
    res = selection_effect(panel, draws=100)
    assert res.point is None and res.p is None
    assert selection_effect(panel.iloc[0:0], draws=100).point is None
