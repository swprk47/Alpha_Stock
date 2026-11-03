import numpy as np
import pandas as pd
import pytest

from backtest.analysis.equity import trade_daily_factors
from backtest.improve.evaluate import Evaluation, Window, evaluate, vs_baseline
from backtest.improve.stats import ANNUAL
from backtest.signals import DayResult, Signal
from bt_helpers import make_frame, trending_rows

BUCKET = 200_000
DRAWS = 200


def _frames(codes="AB", n=150):
    return {c: make_frame(trending_rows(n)) for c in codes}


def _bench(falling=False, n=150):
    closes = [200.0 - i for i in range(n)] if falling else [100.0 + 0.5 * i for i in range(n)]
    return make_frame([(c, c * 1.01, c * 0.99, c, 100_000) for c in closes])


def _day(date, codes):
    return DayResult(date, list(codes), [Signal(c, date, 0, 0.0, BUCKET) for c in codes])


def _window(frames, start=60, end=140, sig_start=70, sig_end=130):
    dates = list(frames["A"].index)
    return Window(dates[sig_start], dates[sig_end], dates[start:end + 1])


def _eval(days, frames, bench, window, **kw):
    return evaluate(days, frames, bench, window, exit_kwargs=kw.pop("exit_kwargs", {}), bucket=BUCKET, draws=DRAWS, **kw)


def test_trades_are_limited_to_the_signal_window():
    frames = _frames()
    dates = list(frames["A"].index)
    window = _window(frames, sig_start=75, sig_end=95)
    days = [_day(dates[i], "A") for i in range(50, 125, 7)]
    ev = _eval(days, frames, _bench(), window)
    assert ev.n_trades > 0
    assert all(window.signal_start <= t.signal_date <= window.signal_end for t in ev.trades)


def test_rows_include_days_without_trades_as_zero():
    frames = _frames()
    window = _window(frames)
    ev = _eval([_day(window.dates[20], "A")], frames, _bench(), window)
    assert ev.trade_mean.n_days == len(window.dates)
    assert isinstance(ev, Evaluation) and list(ev.ret.index) == list(window.dates)


def test_trade_mean_uses_signal_day_sums():
    frames = _frames()
    window = _window(frames)
    ev = _eval([_day(window.dates[20], "A")], frames, _bench(), window)
    assert ev.n_trades == 1
    assert ev.trade_mean.point == pytest.approx(ev.trades[0].net_return_pct)


def test_vs_kodex_positive_when_account_beats_a_falling_benchmark():
    frames = _frames()
    window = _window(frames)
    ev = _eval([], frames, _bench(falling=True), window)
    assert (ev.ret == 0).all()
    assert ev.vs_kodex.point > 0                                            # 현금(0)이 하락하는 KODEX 보다 낫다


def test_vs_cash_is_log_growth_of_the_account():
    frames = _frames()
    window = _window(frames)
    ev = _eval([_day(window.dates[20], "AB")], frames, _bench(), window)
    expected = float(np.mean(np.log1p(ev.ret.to_numpy()))) * ANNUAL
    assert ev.vs_cash.point == pytest.approx(expected)


def test_trade_kodex_excess_matches_manual():
    frames = _frames()
    bench = _bench()
    window = _window(frames)
    ev = _eval([_day(window.dates[20], "A")], frames, bench, window)
    t = ev.trades[0]
    expected = t.net_return_pct - (bench["close"].loc[t.exit_date] / bench["open"].loc[t.entry_date] - 1) * 100
    assert ev.trade_kodex_excess_mean == pytest.approx(expected)


def test_avg_hold_days_and_utilisation():
    frames = _frames()
    window = _window(frames)
    ev = _eval([_day(window.dates[20], "A")], frames, _bench(), window)
    t = ev.trades[0]
    open_days = len(trade_daily_factors(t, frames["A"]))
    assert ev.avg_hold_days == pytest.approx(t.held_days)
    assert ev.exposure == pytest.approx(open_days / len(window.dates))
    assert ev.avg_slots == pytest.approx(open_days / len(window.dates) / 2)


def test_vs_baseline_zero_for_identical_accounts():
    ret = pd.Series(np.random.default_rng(0).normal(0.001, 0.01, 120))
    res = vs_baseline(ret, ret.copy(), draws=DRAWS)
    assert res.point == pytest.approx(0.0)


def test_no_trades_gives_zero_account_and_none_trade_mean():
    frames = _frames()
    window = _window(frames)
    ev = _eval([], frames, _bench(), window)
    assert ev.n_trades == 0 and ev.trade_mean.point is None
    assert (ev.ret == 0).all() and ev.vs_cash.point == pytest.approx(0.0)
    assert ev.avg_hold_days is None and ev.exposure == 0.0 and ev.trade_kodex_excess_mean is None


def test_account_window_includes_exit_costs_of_late_trades():
    frames = _frames()
    dates = list(frames["A"].index)
    window = Window(dates[70], dates[130], dates[60:146])                    # 계좌 창은 마지막 신호일보다 뒤까지 이어진다
    ev = _eval([_day(dates[130], "A")], frames, _bench(), window)
    t = ev.trades[0]
    assert t.exit_date > window.signal_end and t.exit_date in window.dates
    factors = trade_daily_factors(t, frames["A"]) - 1
    assert ev.ret.sum() * 2 == pytest.approx(float(factors.sum()))           # 청산일 비용까지 전부 창 안에 들어 있다
