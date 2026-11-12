"""10개월 평균 게이트 신호 테스트: 월말 종가를 직접 정해 만든 영업일 프레임."""
import pandas as pd
import pytest

from backtest.forward.gate import gate_states
from backtest.forward.months import periods
from tests.bt_fw_helpers import frame_from_closes


def bench_with_month_ends(month_end_closes, start="2020-01-01", filler=1.0):
    """영업일 프레임. 각 달 마지막 영업일 종가는 지정값, 나머지 날은 filler.

    마지막 달 뒤에 다음 달 첫 영업일을 하나 더 두어 마지막 월말도 신호일이 되게 한다.
    """
    days = pd.bdate_range(start, periods=len(month_end_closes) * 23 + 40)
    last_of_month = {}
    for d in days:
        last_of_month[(d.year, d.month)] = d  # 마지막으로 덮어쓴 날 = 그 달의 마지막 영업일
    keys = sorted(last_of_month)[: len(month_end_closes)]
    month_ends = {last_of_month[k]: c for k, c in zip(keys, month_end_closes)}
    cutoff = last_of_month[keys[-1]] + pd.offsets.BDay(1)
    days = days[days <= cutoff]
    closes = [month_ends.get(d, filler) for d in days]
    # frame_from_closes는 start부터 영업일 달력을 다시 만들므로 날짜가 같다.
    frame = frame_from_closes(closes, start=start)
    assert list(frame.index) == list(days)
    return frame, [last_of_month[k] for k in keys]


def run(month_end_closes, months=10):
    bench, signal_days = bench_with_month_ends(month_end_closes)
    states = gate_states(bench, periods(bench.index), months=months)
    return [states[d] for d in signal_days]


def test_gate_holds_until_ten_month_ends_exist():
    # 첫 9개 월말은 평균을 못 내므로, 종가가 아무리 낮아도 모두 True
    out = run([100, 90, 80, 70, 60, 50, 40, 30, 20])
    assert out == [True] * 9


def test_gate_goes_to_cash_below_average_and_back():
    # 100이 10번 -> 평균 100, 종가 100은 보유
    # 그다음 90: 최근 10개 평균 99, 90 < 99 -> 현금
    # 그다음 130: 최근 10개 평균 (8*100+90+130)/10 = 102, 130 >= 102 -> 보유
    out = run([100] * 10 + [90, 130])
    assert out[:10] == [True] * 10
    assert out[10] is False
    assert out[11] is True


def test_gate_equal_to_average_holds():
    # 60이 10번이면 평균 60 == 종가 60 -> 보유
    out = run([60] * 10)
    assert out[9] is True
    # 종가를 조금만 낮추면 평균보다 낮아져 현금
    below = run([60] * 9 + [59.9])
    assert below[9] is False


def test_gate_uses_only_most_recent_months_window():
    # 오래된 높은 종가는 창에서 빠져야 한다: 1000 하나 뒤에 100이 10번이면
    # 마지막(100)의 최근 10개 평균은 100이라 보유. 창이 안 밀리면 평균이 높아져 현금이 된다.
    out = run([1000] + [100] * 10)
    assert out[10] is True


def test_gate_ignores_data_after_signal_day():
    # 신호일 이후 데이터가 뒤바뀌어도 그 신호일의 상태는 같아야 한다.
    base = [100] * 10 + [90]
    out_a = run(base + [1])
    out_b = run(base + [10_000])
    assert out_a[:11] == out_b[:11]
    assert out_a[10] is False


def test_gate_ignores_intramonth_closes():
    # 월중 종가가 달라도 월말 종가만 쓴다
    closes = [100] * 10 + [90]
    bench_lo, days = bench_with_month_ends(closes, filler=1.0)
    bench_hi, _ = bench_with_month_ends(closes, filler=5000.0)
    lo = gate_states(bench_lo, periods(bench_lo.index))
    hi = gate_states(bench_hi, periods(bench_hi.index))
    assert lo == hi


def test_gate_custom_months_window():
    # months=3: 100,100,100 -> 보유, 그다음 90은 평균 (100+100+90)/3 > 90 -> 현금
    out = run([100, 100, 100, 90], months=3)
    assert out == [True, True, True, False]


def test_gate_covers_every_signal_day():
    bench, days = bench_with_month_ends([100] * 12)
    all_p = periods(bench.index)
    states = gate_states(bench, all_p)
    assert set(states) == {p.signal_day for p in all_p}


def test_gate_missing_signal_day_raises_key_error():
    bench, _ = bench_with_month_ends([100] * 12)
    all_p = periods(bench.index)
    holed = bench.drop(index=all_p[11].signal_day)
    with pytest.raises(KeyError):
        gate_states(holed, all_p)


@pytest.mark.parametrize("bad", [float("nan"), 0.0, -5.0])
def test_gate_rejects_missing_or_non_positive_signal_close(bad):
    bench, _ = bench_with_month_ends([100] * 12)
    all_p = periods(bench.index)
    broken = bench.copy()
    broken.loc[all_p[5].signal_day, "close"] = bad
    with pytest.raises(ValueError):
        gate_states(broken, all_p)
