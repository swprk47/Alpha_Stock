import pytest

import config
from bt_helpers import make_frame
from backtest.signals import DayResult, Signal
from backtest.simulate import simulate_picks, simulate_trade

SIG = (10_000, 10_000, 10_000, 10_000, 100_000)
CALM = (10_000, 10_300, 9_800, 10_100, 1)                          # 목표 10650·손절 9700 에 안 닿는 날


@pytest.fixture(autouse=True)
def default_fees(monkeypatch):
    monkeypatch.setattr(config, "BUY_FEE_RATE", 0.00015)
    monkeypatch.setattr(config, "SELL_FEE_RATE", 0.00015)
    monkeypatch.setattr(config, "SELL_TAX_RATE", 0.0020)


def path(rows):
    f = make_frame([SIG, *rows])                                      # 신호 행 + 이어지는 행
    return f, f.index[0]


def run(rows, mode="close", **kw):
    f, d = path(rows)
    return simulate_trade(f, "X", d, mode, **kw)


def test_target_first_and_cost_math():
    t = run([(10_100, 10_700, 10_050, 10_600, 1)] + [CALM] * 4)       # 목표가 int(10000*1.065)=10650
    assert (t.exit_reason, t.exit_price, t.held_days) == ("target", 10_650, 1)
    assert t.net_return_pct == pytest.approx(6.2551, abs=1e-3)         # (10_627_103 / 10_001_500 - 1) * 100


def test_stop_first():
    t = run([(9_900, 9_950, 9_690, 9_800, 1)] + [CALM] * 4)
    assert (t.exit_reason, t.exit_price) == ("stop", 9_700)


def test_same_day_target_and_stop_counts_as_stop():
    t = run([(10_000, 10_700, 9_690, 10_100, 1)] + [CALM] * 4)
    assert (t.exit_reason, t.exit_price) == ("stop", 9_700)


def test_gap_down_fills_at_the_open_not_the_stop():
    t = run([(9_000, 9_100, 8_900, 9_050, 1)] + [CALM] * 4)
    assert (t.exit_reason, t.exit_price) == ("stop", 9_000) and t.net_return_pct < -10.0


def test_gap_up_fills_at_the_target_without_bonus():
    t = run([(11_000, 11_200, 10_900, 11_100, 1)] + [CALM] * 4)
    assert (t.exit_reason, t.exit_price) == ("target", 10_650)


def test_expire_on_the_fifth_row_close():
    t = run([CALM] * 4 + [(10_000, 10_300, 9_800, 10_200, 1)])
    assert (t.exit_reason, t.exit_price, t.held_days) == ("expire", 10_200, 5)


def test_next_open_entry_and_same_day_target():
    t = run([(10_200, 10_900, 10_100, 10_800, 1)] + [CALM] * 4, mode="next_open")   # 목표 int(10200*1.065)=10863
    assert (t.entry_price, t.exit_price, t.exit_reason, t.held_days) == (10_200, 10_863, "target", 0)
    assert t.entry_date == t.exit_date


def test_halt_day_is_skipped_for_exit_checks():
    t = run([(9_000, 9_000, 9_000, 10_000, 0)] + [CALM] * 4)           # 거래정지 행의 저가 9000 은 손절 판단에서 제외
    assert (t.exit_reason, t.exit_price) == ("expire", 10_100)


def test_slippage_raises_entry_and_lowers_exit():
    t = run([(10_100, 10_700, 10_050, 10_600, 1)] + [CALM] * 4, slippage_pct=0.3)
    assert t.entry_price == 10_030 and t.exit_price == round(int(10_030 * 1.065) * 0.997)


def test_unfinished_trade_near_the_end_of_data_is_dropped():
    assert run([CALM] * 4) is None                                      # hold_days 5 에 한 행 모자람


def test_entry_row_missing_returns_none():
    assert run([], mode="next_open") is None


def test_simulate_picks_skips_resignal_while_holding_and_respects_top_n():
    f = make_frame([SIG] + [CALM] * 14)
    d = list(f.index)
    sig = lambda i, code="X", score=65: Signal(code, d[i], score, 2.17, 100_000)
    days = [DayResult(d[0], ["X"], [sig(0)]), DayResult(d[2], ["X"], [sig(2)]),    # 보유 중(0~5) 재신호 → 제외
            DayResult(d[7], ["X", "Y"], [sig(7), sig(7, "Y", 60)])]
    trades = simulate_picks(days, {"X": f, "Y": f}, "close", bucket=100_000)
    assert [(t.code, t.signal_date) for t in trades] == [("X", d[0]), ("X", d[7]), ("Y", d[7])]
    assert [t.code for t in simulate_picks(days, {"X": f, "Y": f}, "close", bucket=100_000, top_n=1)] == ["X", "X"]


ZERO_OHL = (0, 0, 0, 10_000, 401)                                   # 거래량은 있지만 시가·고가·저가가 0인 행


def test_zero_ohl_row_is_skipped_instead_of_booking_a_minus_100_percent_stop():
    t = run([ZERO_OHL] + [CALM] * 4)
    assert (t.exit_reason, t.exit_price) == ("expire", 10_100) and t.net_return_pct > -1.0


def test_zero_ohl_entry_row_gives_no_trade_instead_of_dividing_by_zero():
    assert run([ZERO_OHL] + [CALM] * 4, mode="next_open") is None

