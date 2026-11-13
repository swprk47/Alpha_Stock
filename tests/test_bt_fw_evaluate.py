"""후보별 평가(evaluate) 테스트: 합성 자료는 고정 시드나 고정 패턴으로만 만든다."""
import numpy as np
import pandas as pd
import pytest

from backtest.forward import months
from backtest.forward.evaluate import (
    GateEval, LotteryEval, evaluate_gate, evaluate_lottery, gate_targets, lottery_targets,
)
from backtest.forward.registry import BENCHMARK
from tests.bt_fw_helpers import frame_from_returns

DRAWS = 300
N = 520  # 2020-01-01부터 영업일 520개: 약 2년


def _cal(n=N):
    return pd.bdate_range("2020-01-01", periods=n)


def _k(cal):
    """달 안에서 몇 번째 영업일인지(0부터)."""
    s = pd.Series(1, index=cal)
    return (s.groupby([cal.year, cal.month]).cumsum() - 1).to_numpy()


def _mi(cal):
    return ((cal.year - 2020) * 12 + cal.month - 1).to_numpy()


def _frame(r):
    """날짜마다 수익률 하나인 배열(첫 값은 버린다)로 만든 프레임."""
    return frame_from_returns(list(r[1:]))


def _code(j):
    return f"{100000 + j:06d}"


def _fixed_universe(*, bad_month=None):
    """조용한 8개 + 매달 +20%/-15% 하루씩 있는 2개(S8, S9). 벤치마크는 노이즈."""
    cal = _cal()
    k, mi = _k(cal), _mi(cal)
    rng = np.random.default_rng(7)
    bench = _frame(rng.normal(0.0, 0.006, N))
    frames = {}
    for j in range(10):
        r = rng.normal(0.0005, 0.003, N)
        if j >= 8:
            r[k == 3] = 0.20
            r[k == 4] = -0.15
        if bad_month is not None:
            r[(mi == bad_month) & (k == 3)] = 0.40
        frames[_code(j)] = _frame(r)
    return frames, bench, cal


def _rotating_universe(*, shock_from=None):
    """매달 서로 다른 2종목이 급등락하고 다음 달에 꾸준히 내린다. shock_from 이후는 수익률을 바꾼다."""
    cal = _cal()
    k, mi = _k(cal), _mi(cal)
    rng = np.random.default_rng(11)
    bench_r = rng.normal(0.0, 0.006, N)
    stock_r = {}
    for j in range(10):
        g = j // 2
        r = rng.normal(0.002, 0.003, N)
        spike = (mi % 5) == g
        r[spike & (k == 3)] = 0.20
        r[spike & (k == 4)] = -0.15
        r[((mi - 1) % 5) == g] = -0.008
        stock_r[j] = r
    if shock_from is not None:
        bench_r[shock_from:] = -bench_r[shock_from:] - 0.01
        for r in stock_r.values():
            r[shock_from:] = -r[shock_from:] - 0.01
    frames = {_code(j): _frame(r) for j, r in stock_r.items()}
    return frames, _frame(bench_r), cal


def _order(frames):
    return sorted(frames)


# ---------------------------------------------------------------- lottery_targets
def test_lottery_targets_base_is_all_eligible_and_tilt_drops_top_fifth():
    frames, bench, cal = _fixed_universe()
    ap = months.periods(cal)
    tilt, base, log = lottery_targets(frames, bench, ap, _order(frames), reentry_pct=0.20)
    assert list(tilt) == [p.trade_day for p in ap]
    for p in ap:
        t, b = tilt[p.trade_day], base[p.trade_day]
        assert len(b) == 10 and all(w == pytest.approx(0.1) for w in b.values())
        assert len(t) == 8 and all(w == pytest.approx(0.125) for w in t.values())
        assert _code(8) not in t and _code(9) not in t
        info = log[p.trade_day]
        assert info["signal_day"] == p.signal_day
        assert info["eligible"] == 10
        assert sorted(info["excluded"]) == [_code(8), _code(9)]


def _ladder_universe(n=60):
    """S_j는 부호가 번갈아 바뀌는 ±0.003*(j+1) 수익률(벤치마크는 상수라 IVOL=표준편차).
    S0만 1월에 급등락하고 2월에는 S8과 S7 사이 크기로 움직인다."""
    cal = _cal(n)
    k, mi = _k(cal), _mi(cal)
    sign = np.where(np.arange(n) % 2 == 0, 1.0, -1.0)
    bench = _frame(np.full(n, 0.001))
    frames = {}
    for j in range(10):
        r = sign * 0.003 * (j + 1)
        if j == 0:
            jan, feb = mi == 0, mi == 1
            r[feb] = sign[feb] * 0.0255
            r[jan & (k == 3)] = 0.25
            r[jan & (k == 4)] = -0.20
        frames[_code(j)] = _frame(r)
    return frames, bench, cal


def test_lottery_targets_state_carries_over_from_first_month():
    frames, bench, cal = _ladder_universe()
    ap = months.periods(cal)
    order = _order(frames)
    tilt, _, log = lottery_targets(frames, bench, ap, order, reentry_pct=0.30)
    p1 = ap[1].trade_day
    # 1월: S0(급등락)과 S9가 제외. 2월: S0는 3위지만 직전 제외라 완충으로 계속 제외
    assert sorted(log[ap[0].trade_day]["excluded"]) == [_code(0), _code(9)]
    assert _code(0) in log[p1]["excluded"] and _code(0) not in tilt[p1]
    assert sorted(log[p1]["excluded"]) == [_code(0), _code(8), _code(9)]
    # 신호를 둘째 달부터 시작하면 S0는 보유 — 그래서 첫 달부터 계산해야 한다
    tilt_cut, _, _ = lottery_targets(frames, bench, ap[1:], order, reentry_pct=0.30)
    assert _code(0) in tilt_cut[p1]


def test_lottery_targets_month_with_no_eligible_stock_is_cash():
    frames, bench, cal = _fixed_universe(bad_month=5)  # 6월 모든 종목에 +40% 하루(bad)
    ap = months.periods(cal)
    tilt, base, log = lottery_targets(frames, bench, ap, _order(frames), reentry_pct=0.20)
    june = next(p for p in ap if p.signal_day.month == 6 and p.signal_day.year == 2020)
    assert tilt[june.trade_day] == {} and base[june.trade_day] == {}
    assert log[june.trade_day]["eligible"] == 0 and list(log[june.trade_day]["excluded"]) == []
    others = [p for p in ap if p is not june and p.signal_day.month != 6]
    assert all(len(base[p.trade_day]) == 10 for p in others[:3])


# ---------------------------------------------------------------- evaluate_lottery
def _eval_lottery(frames, bench, cal):
    return evaluate_lottery(frames, bench, cal, _order(frames), start=cal[0], end=cal[-1],
                            reentry_pct=0.20, draws=DRAWS)


def test_evaluate_lottery_positive_when_lottery_stocks_lose():
    frames, bench, cal = _rotating_universe()
    ev = _eval_lottery(frames, bench, cal)
    assert isinstance(ev, LotteryEval)
    assert set(ev.diff) == {1.0, 1.5, 2.0}
    assert ev.diff[1.0].point > 0.01
    # 비용을 올리면 회피 쪽(교체가 잦음)이 더 불리해진다
    assert ev.diff[2.0].point < ev.diff[1.5].point < ev.diff[1.0].point
    assert ev.diff[1.0].n == ev.n_months == len(ev.monthly_diff)
    assert ev.diff[1.0].point == pytest.approx(ev.monthly_diff.mean())


def test_evaluate_lottery_reports_turnover_and_yearly():
    frames, bench, cal = _rotating_universe()
    ev = _eval_lottery(frames, bench, cal)
    assert 0.0 < ev.turnover_base < ev.turnover_tilt <= 1.0
    assert ev.turnover_tilt > 0.15 and ev.turnover_base < 0.10
    assert ev.excluded_mean == pytest.approx(2.0)
    assert set(ev.yearly_diff) == {2020, 2021}
    assert sum(ev.yearly_diff.values()) == pytest.approx(ev.monthly_diff.sum())
    for y, v in ev.yearly_diff.items():
        assert v == pytest.approx(ev.monthly_diff[ev.monthly_diff.index.year == y].sum())
    assert ev.n_months == len(months.periods(cal)) - 1
    # 벤치마크 평균 수익률이 0 근처라 매달 회피하는 쪽이 KODEX 보유보다 크게 앞선다
    assert ev.vs_kodex_annual > 0.2


def test_evaluate_lottery_window_only_trims_returns():
    frames, bench, cal = _rotating_universe()
    full = _eval_lottery(frames, bench, cal)
    ap = months.periods(cal)
    part = evaluate_lottery(frames, bench, cal, _order(frames), start=ap[10].trade_day, end=cal[-1],
                            reentry_pct=0.20, draws=DRAWS)
    assert part.n_months == len(ap) - 10 - 1
    # 같은 달의 월 차이는 구간과 상관없이 같다(신호가 첫 달부터 계산되고, 둘째 달부터는 초기 매수 영향이 없다)
    common = full.monthly_diff.index.intersection(part.monthly_diff.index)
    assert len(common) == part.n_months
    assert part.monthly_diff[common].iloc[1:].to_numpy() == pytest.approx(
        full.monthly_diff[common].iloc[1:].to_numpy(), abs=1e-10)


def _assert_empty(ev):
    assert ev.n_months == 0 and len(ev.monthly_diff) == 0
    assert ev.yearly_diff == {} and ev.turnover_tilt == 0.0 and ev.turnover_base == 0.0
    assert ev.excluded_mean == 0.0 and ev.vs_kodex_annual == 0.0
    assert all(s.point is None and s.n == 0 for s in ev.diff.values())
    assert ev.first_month is None and ev.last_month is None
    assert ev.eligible_min is None and ev.eligible_median is None and ev.eligible_max is None
    assert ev.eligible_by_year == {}


def test_evaluate_lottery_empty_window():
    frames, bench, cal = _rotating_universe()
    ev = evaluate_lottery(frames, bench, cal, _order(frames), start="2030-01-01", end="2030-12-31",
                          reentry_pct=0.20, draws=DRAWS)
    _assert_empty(ev)


def _slice(frames, bench, cal, since):
    """모든 프레임과 달력을 since 이후로 자른다(첫 달의 행 수를 줄이는 용도)."""
    since = pd.Timestamp(since)
    return ({c: f.loc[f.index >= since] for c, f in frames.items()},
            bench.loc[bench.index >= since], cal[cal >= since])


def test_evaluate_lottery_starts_at_first_month_with_eligible_stock():
    # 달력이 2020-01-20에 시작해 1월 유효한 날이 15일 미만 -> 첫 교체일(2월 초)은 대상 종목이 없다
    frames, bench, cal = _slice(*_rotating_universe(), "2020-01-20")
    ap = months.periods(cal)
    order = _order(frames)
    _, base, _ = lottery_targets(frames, bench, ap, order, reentry_pct=0.20)
    assert base[ap[0].trade_day] == {} and len(base[ap[1].trade_day]) == 10
    a = evaluate_lottery(frames, bench, cal, order, start=cal[0], end=cal[-1], reentry_pct=0.20, draws=DRAWS)
    b = evaluate_lottery(frames, bench, cal, order, start=ap[1].trade_day, end=cal[-1],
                         reentry_pct=0.20, draws=DRAWS)
    pd.testing.assert_series_equal(a.monthly_diff, b.monthly_diff)
    assert (a.turnover_tilt, a.turnover_base, a.n_months, a.excluded_mean) == (
        b.turnover_tilt, b.turnover_base, b.n_months, b.excluded_mean)
    assert a.diff == b.diff
    assert a.first_month == ap[1].trade_day
    # 초기 매수(100%)가 회전율 평균에 들어가지 않는다
    assert a.turnover_base < 0.10
    # 빈 첫 교체일부터 센 교체일 쌍(마지막 달은 미완성이라 빠짐)보다 하나 적다
    window_days = [p.trade_day for p in months.in_window(ap, cal[0], cal[-1])]
    assert a.n_months == (len(window_days) - 1) - 1


def test_evaluate_lottery_no_eligible_month_in_window_is_empty():
    frames, bench, cal = _slice(*_rotating_universe(), "2020-01-20")
    ap = months.periods(cal)
    ev = evaluate_lottery(frames, bench, cal, _order(frames), start=ap[0].trade_day, end=ap[0].trade_day,
                          reentry_pct=0.20, draws=DRAWS)
    _assert_empty(ev)


def test_evaluate_lottery_includes_final_month_when_signal_day_is_end():
    frames, bench, cal = _rotating_universe()
    ap = months.periods(cal)
    full = _eval_lottery(frames, bench, cal)
    end = ap[-1].signal_day
    ev = evaluate_lottery(frames, bench, cal, _order(frames), start=cal[0], end=end,
                          reentry_pct=0.20, draws=DRAWS)
    window_days = [p.trade_day for p in months.in_window(ap, cal[0], end)]
    assert ev.n_months == len(window_days) == len(ap) - 1
    assert ev.first_month == ap[0].trade_day and ev.last_month == ap[-2].trade_day
    assert ev.monthly_diff.index[-1] == ap[-2].trade_day
    # 마지막 달 값은 다음 교체일까지 잰 긴 구간의 같은 달과 같다
    assert ev.monthly_diff.to_numpy() == pytest.approx(full.monthly_diff[ev.monthly_diff.index].to_numpy(),
                                                       abs=1e-12)


def test_evaluate_lottery_drops_final_month_when_end_is_mid_month():
    frames, bench, cal = _rotating_universe()
    ap = months.periods(cal)
    end = ap[-2].trade_day + pd.Timedelta(days=14)
    ev = evaluate_lottery(frames, bench, cal, _order(frames), start=cal[0], end=end,
                          reentry_pct=0.20, draws=DRAWS)
    window_days = [p.trade_day for p in months.in_window(ap, cal[0], end)]
    assert window_days[-1] == ap[-2].trade_day
    assert ev.n_months == len(window_days) - 1
    assert ev.last_month == ap[-3].trade_day


def test_evaluate_lottery_includes_final_month_at_calendar_month_end_cut():
    # 학습처럼 달력을 달력상 월말(2021-06-30, 수요일)에서 자른 경우
    frames, bench, cal = _rotating_universe()
    full = _eval_lottery(frames, bench, cal)
    cut = pd.Timestamp("2021-06-30")
    tf = {c: f.loc[f.index <= cut] for c, f in frames.items()}
    tb, tc = bench.loc[bench.index <= cut], cal[cal <= cut]
    assert tc[-1] == cut
    ev = evaluate_lottery(tf, tb, tc, _order(tf), start=tc[0], end=cut, reentry_pct=0.20, draws=DRAWS)
    ap = months.periods(tc)
    assert ev.n_months == len(ap)
    assert ev.last_month == ap[-1].trade_day == pd.Timestamp("2021-06-01")
    assert ev.monthly_diff.to_numpy() == pytest.approx(full.monthly_diff[ev.monthly_diff.index].to_numpy(),
                                                       abs=1e-12)


def test_evaluate_lottery_counts_eligible_stocks_over_time():
    # S6·S7은 2020-07, S8·S9는 2021-01부터 일봉이 있다
    frames, bench, cal = _fixed_universe()
    for j, since in ((6, "2020-07-01"), (7, "2020-07-01"), (8, "2021-01-01"), (9, "2021-01-01")):
        f = frames[_code(j)]
        frames[_code(j)] = f.loc[f.index >= pd.Timestamp(since)]
    ev = _eval_lottery(frames, bench, cal)
    # 측정한 달(신호일 2020-01 ~ 2021-10): 6개가 6달, 8개가 6달, 10개가 10달
    assert ev.n_months == 22
    assert (ev.eligible_min, ev.eligible_median, ev.eligible_max) == (6, 8.0, 10)
    # 교체일 연도별: 2020은 [6]*6 + [8]*5, 2021은 [8] + [10]*10
    assert ev.eligible_by_year == {2020: 6.0, 2021: 10.0}


# ---------------------------------------------------------------- gate
def _up_then_down_returns(up=260, down=260):
    return np.concatenate([[0.0], np.full(up, 0.001), np.full(down, -0.002)])


def _bench_up_then_down():
    r = _up_then_down_returns()
    return _frame(r), _cal(len(r))


def test_gate_targets_cash_when_below_average():
    bench, cal = _bench_up_then_down()
    ap = months.periods(cal)
    gate, hold = gate_targets(bench, ap)
    assert list(gate) == list(hold) == [p.trade_day for p in ap]
    assert all(h == {BENCHMARK: 1.0} for h in hold.values())
    # 앞 9개월은 월말 종가가 10개 미만이라 보유
    assert all(gate[p.trade_day] == {BENCHMARK: 1.0} for p in ap[:9])
    # 12개월 상승 뒤 계속 하락하면 마지막 달은 현금
    assert gate[ap[-1].trade_day] == {}
    assert {tuple(g.items()) for g in gate.values()} == {(), ((BENCHMARK, 1.0),)}


def test_gate_targets_first_cash_month_hand_computed():
    # 종가(시작 1) = 1.001^min(k,260) * 0.998^max(0,k-260), k = 영업일 위치.
    # 신호일 2021-01-29(k=282): 종가 1.24089 >= 최근 10개 월말 평균 1.19541 -> 보유
    # 신호일 2021-02-26(k=302): 종가 1.19218 <  최근 10개 월말 평균 1.20565 -> 처음으로 현금
    bench, cal = _bench_up_then_down()
    ap = months.periods(cal)
    gate, _ = gate_targets(bench, ap)
    assert ap[12].signal_day == pd.Timestamp("2021-01-29") and ap[13].signal_day == pd.Timestamp("2021-02-26")
    assert all(gate[p.trade_day] == {BENCHMARK: 1.0} for p in ap[:13])
    assert gate[pd.Timestamp("2021-02-01")] == {BENCHMARK: 1.0}
    assert gate[pd.Timestamp("2021-03-01")] == {}


def test_evaluate_gate_reduces_drawdown_in_long_decline():
    bench, cal = _bench_up_then_down()
    ev = evaluate_gate(bench, cal, start=cal[0], end=cal[-1], draws=DRAWS)
    assert isinstance(ev, GateEval)
    assert 0.38 < ev.mdd_hold < 0.42
    assert ev.mdd_gate < ev.mdd_hold - 0.05
    assert ev.mdd_diff.point == pytest.approx(ev.mdd_hold - ev.mdd_gate)
    assert ev.mdd_diff.point > 0 and ev.mdd_diff.n > 0
    assert ev.switches >= 1
    assert ev.vol_gate < ev.vol_hold
    assert ev.return_given_up_annual < 0   # 하락장이라 게이트가 오히려 더 번다
    assert len(ev.episodes) == 1
    e = ev.episodes[0]
    assert set(e) == {"peak_day", "end_day", "depth_hold", "depth_gate"}
    assert e["depth_hold"] >= 0.15 and e["depth_gate"] < e["depth_hold"]


def test_evaluate_gate_no_switch_when_always_rising():
    r = np.concatenate([[0.0], np.full(400, 0.001)])
    bench, cal = _frame(r), _cal(len(r))
    ev = evaluate_gate(bench, cal, start=cal[0], end=cal[-1], draws=DRAWS)
    assert ev.switches == 0
    assert ev.mdd_diff.point == 0.0
    assert ev.mdd_gate == ev.mdd_hold < 0.002  # 첫날 매수 비용만큼의 낙폭
    assert ev.return_given_up_annual == pytest.approx(0.0, abs=1e-12)
    assert ev.episodes == []
    assert ev.vol_gate == pytest.approx(ev.vol_hold)


def test_evaluate_gate_empty_window():
    bench, cal = _bench_up_then_down()
    ev = evaluate_gate(bench, cal, start="2030-01-01", end="2030-12-31", draws=DRAWS)
    assert ev.switches == 0 and ev.episodes == []
    assert ev.mdd_gate == ev.mdd_hold == 0.0 and ev.mdd_diff.n == 0 and ev.mdd_diff.point is None
    assert ev.return_given_up_annual == 0.0 and ev.vol_gate == ev.vol_hold == 0.0


# ---------------------------------------------------------------- 미래 자료 차단
def test_signal_days_never_use_later_data():
    cut = 400
    f1, b1, cal = _rotating_universe()
    f2, b2, _ = _rotating_universe(shock_from=cut + 1)
    end = cal[cut]
    assert not b1.equals(b2)

    la = evaluate_lottery(f1, b1, cal, _order(f1), start=cal[0], end=end, reentry_pct=0.20, draws=DRAWS)
    lb = evaluate_lottery(f2, b2, cal, _order(f2), start=cal[0], end=end, reentry_pct=0.20, draws=DRAWS)
    assert la.n_months > 10
    pd.testing.assert_series_equal(la.monthly_diff, lb.monthly_diff)
    assert la.diff == lb.diff and la.yearly_diff == lb.yearly_diff
    assert (la.turnover_tilt, la.turnover_base, la.excluded_mean, la.vs_kodex_annual) == (
        lb.turnover_tilt, lb.turnover_base, lb.excluded_mean, lb.vs_kodex_annual)

    r = _up_then_down_returns()
    r2 = r.copy()
    r2[cut + 1:] = 0.05
    gcal = _cal(len(r))
    ga = evaluate_gate(_frame(r), gcal, start=gcal[0], end=gcal[cut], draws=DRAWS)
    gb = evaluate_gate(_frame(r2), gcal, start=gcal[0], end=gcal[cut], draws=DRAWS)
    assert ga == gb
    assert ga.mdd_hold > 0
