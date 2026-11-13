"""후보 ① 복권형 종목 회피 신호: MAX, IVOL, 종합 순위, 제외와 복귀 완충."""
import math

import numpy as np
import pytest

from backtest.forward.lottery import composite, month_stats, select
from tests.bt_fw_helpers import frame_from_returns

B_PATTERN = [0.01, 0.02, -0.01, -0.02]


def _bench_returns(n):
    return [B_PATTERN[i % 4] for i in range(n)]


def _stock_returns(n):
    # e는 +0.01/-0.01 교대, b 패턴(주기 4)과 직교하고 평균 0
    return [2 * b + (0.01 if i % 2 == 0 else -0.01) for i, b in enumerate(_bench_returns(n))]


def test_month_stats_matches_hand_calculation():
    stock = frame_from_returns(_stock_returns(20))
    bench = frame_from_returns(_bench_returns(20))
    day = stock.index[-1]
    max_ret, ivol = month_stats(stock, bench, day)
    # 잔차는 정확히 e(±0.01): 20개, ddof=2 → sqrt(20 * 1e-4 / 18)
    assert ivol == pytest.approx(math.sqrt(20 * 1e-4 / 18), rel=1e-6)
    # 최대 수익률: 2*0.02-0.01 = 0.03, 2*0.01+0.01 = 0.03
    assert max_ret == pytest.approx(0.03, rel=1e-6)


def test_month_stats_ignores_days_after_signal_day():
    base_s, base_b = _stock_returns(20), _bench_returns(20)
    a = frame_from_returns(base_s + [0.01, 0.01, 0.01])
    b = frame_from_returns(base_s + [0.25, -0.2, 0.05])
    ba = frame_from_returns(base_b + [0.0, 0.0, 0.0])
    bb = frame_from_returns(base_b + [0.1, 0.3, -0.1])
    day = a.index[20]
    assert month_stats(a, ba, day) == month_stats(b, bb, day)
    assert month_stats(a, ba, day) is not None


def test_month_stats_none_when_halted_on_signal_day():
    stock = frame_from_returns(_stock_returns(20))
    bench = frame_from_returns(_bench_returns(20))
    day = stock.index[-1]
    stock.loc[day, "halt"] = True
    assert month_stats(stock, bench, day) is None


def test_month_stats_none_when_signal_day_missing():
    stock = frame_from_returns(_stock_returns(20))
    bench = frame_from_returns(_bench_returns(20))
    assert month_stats(stock, bench, stock.index[-1] + (stock.index[-1] - stock.index[-2]) * 30) is None


def test_month_stats_none_when_bad_return_in_month():
    stock = frame_from_returns(_stock_returns(20))
    bench = frame_from_returns(_bench_returns(20))
    stock.loc[stock.index[5], "bad"] = True
    assert month_stats(stock, bench, stock.index[-1]) is None


def test_month_stats_none_when_fewer_than_min_days_overlap_with_bench():
    stock = frame_from_returns(_stock_returns(20))
    bench = frame_from_returns(_bench_returns(10))      # 유효한 날 10일뿐
    assert month_stats(stock, bench, stock.index[-1]) is None
    assert month_stats(stock, bench, stock.index[-1], min_days=10) is not None


def test_month_stats_flat_bench_uses_plain_std():
    rets = _stock_returns(20)
    stock = frame_from_returns(rets)
    bench = frame_from_returns([0.0] * 20)
    max_ret, ivol = month_stats(stock, bench, stock.index[-1])
    assert ivol == pytest.approx(float(np.std(rets, ddof=1)), rel=1e-6)
    assert max_ret == pytest.approx(0.03, rel=1e-6)


def test_composite_is_mean_of_percentile_ranks():
    stats = {"A": (0.01, 0.01), "B": (0.02, 0.03), "C": (0.03, 0.02)}
    out = composite(stats)
    assert out["A"] == pytest.approx(1 / 3)
    assert out["B"] == pytest.approx((2 / 3 + 1) / 2)
    assert out["C"] == pytest.approx((1 + 2 / 3) / 2)


def test_composite_empty_returns_empty():
    assert composite({}) == {}


def _ten():
    codes = [f"S{i}" for i in range(10)]
    scores = {c: (i + 1) / 10 for i, c in enumerate(codes)}   # S9가 최고
    return codes, scores


def test_select_excludes_top_20_percent():
    codes, scores = _ten()
    held, excluded = select(scores, set(), codes, exclude_pct=0.20, reentry_pct=0.20)
    assert excluded == {"S9", "S8"}
    assert held == codes[:8]


def test_select_reentry_buffer_keeps_previously_excluded():
    codes, scores = _ten()
    # 이전에 제외된 S7(3위)는 상위 30% 안이라 계속 제외
    held, excluded = select(scores, {"S7"}, codes, exclude_pct=0.20, reentry_pct=0.30)
    assert excluded == {"S9", "S8", "S7"}
    assert "S7" not in held
    # S6(4위)는 상위 30% 밖이라 복귀
    held, excluded = select(scores, {"S6"}, codes, exclude_pct=0.20, reentry_pct=0.30)
    assert excluded == {"S9", "S8"}
    assert "S6" in held


def test_select_no_buffer_when_reentry_equals_exclude():
    codes, scores = _ten()
    held, excluded = select(scores, {"S7", "S6"}, codes, exclude_pct=0.20, reentry_pct=0.20)
    assert excluded == {"S9", "S8"}
    assert held == codes[:8]


def test_select_ties_broken_by_listing_order():
    codes = ["A", "B", "C", "D", "E"]
    scores = {c: 0.5 for c in codes}
    held, excluded = select(scores, set(), codes, exclude_pct=0.20, reentry_pct=0.20)
    assert excluded == {"A"}                  # 동점이면 order에서 앞선 코드가 먼저
    assert held == ["B", "C", "D", "E"]


def test_select_small_universe_excludes_nobody():
    codes = ["A", "B", "C", "D"]
    scores = {"A": 0.1, "B": 0.4, "C": 0.3, "D": 0.2}
    held, excluded = select(scores, {"B"}, codes, exclude_pct=0.20, reentry_pct=0.20)
    assert excluded == set()
    assert held == codes
    assert select({}, set(), [], exclude_pct=0.20, reentry_pct=0.30) == ([], set())


def test_select_float_floor_is_stable():
    # 100 * 0.29 == 28.999999999999996 이라 그냥 floor하면 28이 된다. 9자리 반올림으로 29를 지킨다.
    assert 100 * 0.29 < 29
    codes = [f"S{i:03d}" for i in range(100)]
    scores = {c: float(i) for i, c in enumerate(codes)}
    held, excluded = select(scores, set(), codes, exclude_pct=0.29, reentry_pct=0.29)
    assert len(excluded) == 29
    assert len(held) == 71
