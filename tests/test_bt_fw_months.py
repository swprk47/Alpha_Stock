import pandas as pd

from backtest.forward.months import Period, in_window, month_rows, periods
from tests.bt_fw_helpers import frame_from_closes


def _pairs(ps):
    return [(p.signal_day.date().isoformat(), p.trade_day.date().isoformat()) for p in ps]


def test_periods_use_last_trading_day_and_next_trading_day():
    cal = pd.bdate_range("2020-01-01", "2020-03-31")
    ps = periods(cal)
    assert _pairs(ps) == [("2020-01-31", "2020-02-03"), ("2020-02-28", "2020-03-02")]


def test_periods_respect_calendar_gaps():
    cal = pd.DatetimeIndex(["2020-01-29", "2020-01-30", "2020-02-04", "2020-02-05", "2020-03-02"])
    assert _pairs(periods(cal)) == [("2020-01-30", "2020-02-04"), ("2020-02-05", "2020-03-02")]
    assert periods(pd.DatetimeIndex([])) == []


def test_in_window_filters_by_trade_day():
    ps = periods(pd.bdate_range("2020-01-01", "2020-06-30"))
    got = in_window(ps, "2020-02-03", pd.Timestamp("2020-04-01"))
    assert _pairs(got) == [("2020-01-31", "2020-02-03"), ("2020-02-28", "2020-03-02"),
                           ("2020-03-31", "2020-04-01")]
    assert in_window(ps, "2020-02-04", "2020-03-01") == []


def test_period_is_frozen():
    p = Period(pd.Timestamp("2020-01-31"), pd.Timestamp("2020-02-03"))
    try:
        p.signal_day = pd.Timestamp("2020-01-01")
    except Exception:
        return
    raise AssertionError("frozen dataclass expected")


def test_month_rows_stops_at_signal_day_and_month():
    f = frame_from_closes(range(100, 160), start="2020-01-01")
    rows = month_rows(f, pd.Timestamp("2020-02-28"))
    assert rows.index.min() >= pd.Timestamp("2020-02-01")
    assert rows.index.max() == pd.Timestamp("2020-02-28")
    assert (rows.index.month == 2).all()
    early = month_rows(f, pd.Timestamp("2020-02-14"))
    assert early.index.max() == pd.Timestamp("2020-02-14")
