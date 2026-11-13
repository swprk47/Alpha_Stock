import pandas as pd
import pytest

from backtest.analysis.equity import trade_daily_factors
from backtest.improve.slots import K, run_slots, slot_account, utilisation
from backtest.signals import DayResult, Signal
from backtest.simulate import simulate_picks
from bt_helpers import make_frame, trending_rows

BUCKET = 200_000


def _frames(codes="ABCD", n=150):
    return {c: make_frame(trending_rows(n)) for c in codes}


def _day(date, codes):
    return DayResult(date, list(codes), [Signal(c, date, 0, 0.0, BUCKET) for c in codes])


def test_slot_cap_never_exceeded():
    frames = _frames()
    dates = frames["A"].index
    days = [_day(dates[i], "ABC") for i in range(60, 100)]
    trades = run_slots(days, frames, "next_open", bucket=BUCKET, hold_days=10)
    assert trades
    account = slot_account(trades, frames, list(dates))
    assert account["open"].max() <= K


def test_skips_when_slots_are_full_then_resumes_after_exit():
    frames = _frames()
    dates = list(frames["A"].index)
    d0 = dates[60]
    first = run_slots([_day(d0, "ABC")], frames, "next_open", bucket=BUCKET, hold_days=5)
    assert [t.code for t in first] == ["A", "B"]                              # 슬롯 2개가 차서 C 는 건너뜀
    free_day = max(t.exit_date for t in first)
    days = [_day(d0, "ABC"), _day(dates[61], "C"), _day(free_day, "C")]
    trades = run_slots(days, frames, "next_open", bucket=BUCKET, hold_days=5)
    c_trades = [t for t in trades if t.code == "C"]
    assert len(c_trades) == 1 and c_trades[0].signal_date == free_day         # 청산일이 신호일 이하가 되면 슬롯이 빈다


def test_same_code_open_trade_is_skipped():
    frames = _frames()
    dates = list(frames["A"].index)
    trades = run_slots([_day(dates[60], "A"), _day(dates[61], "A")], frames, "next_open", bucket=BUCKET)
    assert len(trades) == 1


def test_reentry_allowed_when_exit_date_is_not_after_signal_day():
    frames = _frames()
    dates = list(frames["A"].index)
    first = run_slots([_day(dates[60], "A")], frames, "next_open", bucket=BUCKET)[0]
    days = [_day(dates[60], "A"), _day(first.exit_date, "A")]
    assert len(run_slots(days, frames, "next_open", bucket=BUCKET)) == 2
    assert len(simulate_picks(days, frames, "next_open", bucket=BUCKET)) == 1   # 기존 simulate_picks 는 `<=` 로 막는다


def test_none_trade_does_not_consume_a_slot():
    frames = _frames("ABC", 150)
    frames["SHORT"] = make_frame(trending_rows(40))
    date = frames["SHORT"].index[-3]                                           # 보유 기간을 못 채워 거래가 None 이 되는 날
    trades = run_slots([_day(date, ["SHORT", "A", "B"])], frames, "next_open", bucket=BUCKET, k=1)
    assert [t.code for t in trades] == ["A"]


def test_rank_order_is_respected():
    frames = _frames()
    trades = run_slots([_day(frames["A"].index[60], ["B", "A"])], frames, "next_open", bucket=BUCKET, k=1)
    assert [t.code for t in trades] == ["B"]


def test_account_return_is_sum_over_k():
    frames = _frames()
    dates = list(frames["A"].index)
    trades = run_slots([_day(dates[60], "AB")], frames, "next_open", bucket=BUCKET)
    fa, fb = (trade_daily_factors(t, frames[t.code]) - 1 for t in trades)
    account = slot_account(trades, frames, dates)
    for day in fa.index.intersection(fb.index):
        assert account.loc[day, "ret"] == pytest.approx((fa[day] + fb[day]) / 2)
        assert account.loc[day, "open"] == 2
    only_a = [d for d in fa.index if d not in fb.index]
    if only_a:
        assert account.loc[only_a[0], "ret"] == pytest.approx(fa[only_a[0]] / 2)
        assert account.loc[only_a[0], "open"] == 1


def test_empty_slots_are_cash():
    frames = _frames()
    dates = list(frames["A"].index)
    trades = run_slots([_day(dates[60], "A")], frames, "next_open", bucket=BUCKET)
    account = slot_account(trades, frames, dates)
    assert account.loc[dates[10], "ret"] == 0.0 and account.loc[dates[10], "open"] == 0
    assert account.loc[dates[-1], "ret"] == 0.0 and account.loc[dates[-1], "open"] == 0
    assert len(account) == len(dates)


def test_utilisation_values():
    account = pd.DataFrame({"ret": [0.0, 0.0, 0.0, 0.0], "open": [0, 1, 2, 2]})
    out = utilisation(account, k=2)
    assert out == {"exposure": 0.75, "avg_slots": pytest.approx(0.625)}
    assert utilisation(pd.DataFrame({"ret": [], "open": []}), k=2) == {"exposure": 0.0, "avg_slots": 0.0}


def test_empty_days_returns_empty_trades_and_zero_account():
    frames = _frames()
    dates = list(frames["A"].index)
    assert run_slots([], frames, "next_open", bucket=BUCKET) == []
    account = slot_account([], frames, dates)
    assert (account["ret"] == 0.0).all() and (account["open"] == 0).all() and len(account) == len(dates)
