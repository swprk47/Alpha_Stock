import pandas as pd

from bt_helpers import flat_rows, make_frame, make_raw
from backtest.data import prepare_frame


def test_halt_and_index_and_sorting():
    raw = make_raw(flat_rows(10)).iloc[::-1]               # 뒤집힌 입력
    raw.loc[raw.index[0], "volume"] = 0                      # 가장 늦은 날이 거래정지
    f = prepare_frame(raw)
    assert f.index.is_monotonic_increasing and f.index.name == "date"
    assert list(f.columns) == ["open", "high", "low", "close", "volume", "halt", "vol_break", "pre_split"]
    assert f["halt"].iloc[-1] and not f["halt"].iloc[:-1].any()


def test_duplicate_dates_keep_the_last_row():
    raw = make_raw(flat_rows(6))
    dup = raw.iloc[[2]].copy()
    dup["close"] = 123
    f = prepare_frame(pd.concat([raw, dup]))
    assert len(f) == 6 and f["close"].iloc[2] == 123


def test_split_like_break_flags_six_rows_each_side_only():
    rows = flat_rows(20, volume=600) + flat_rows(3, volume=0) + flat_rows(25, volume=30_000)  # 삼성전자 2018형(분할 뒤 수준이 20봉 이상 이어진다)
    f = make_frame(rows)
    flagged = [i for i, v in enumerate(f["vol_break"]) if v]
    assert flagged == list(range(17, 30))                    # 분할 위치 23 의 앞뒤 6봉
    assert [i for i, v in enumerate(f["halt"]) if v] == [20, 21, 22]
    assert [i for i, v in enumerate(f["pre_split"]) if v] == list(range(0, 23))      # 분할일(23) 이전은 분할 전 실제 가격을 알 수 없다


def test_price_gap_with_volume_jump_is_not_a_split():
    rows = flat_rows(20, volume=600) + [(14_000, 14_000, 14_000, 14_000, 30_000)] * 25   # +40% 갭
    assert not make_frame(rows)["vol_break"].any()


def test_slow_volume_growth_and_single_spike_are_not_splits():
    growth = [(10_000,) * 4 + (v,) for v in range(1_000, 1_000 + 40 * 100, 100)]          # 점진 증가
    assert not make_frame(growth)["vol_break"].any()
    spike = flat_rows(15, volume=1_000) + [(10_000,) * 4 + (50_000,)] + flat_rows(15, volume=1_000)
    assert not make_frame(spike)["vol_break"].any()


def test_fading_volume_surge_is_not_a_split():
    # 거래량이 며칠 20배로 뛰었다가 가라앉는 급등(+20%). 분할은 영구적이라 20봉 안에 수준이 돌아오면 분할이 아니다
    rows = flat_rows(15, volume=50_000) + [(12_000, 12_000, 12_000, 12_000, 1_000_000)] * 4 + [(12_000, 12_000, 12_000, 12_000, 50_000)] * 25
    f = make_frame(rows)
    assert not f["vol_break"].any() and not f["pre_split"].any()


def test_row_with_zero_ohl_but_volume_is_not_tradable():
    # 실데이터에 시가·고가·저가가 0이고 거래량만 있는 행이 있다(033790 2020-01-28, 047810 2017-10-11). 체결 가격을 믿을 수 없다
    rows = flat_rows(10)
    rows[5] = (0, 0, 0, 10_000, 400)
    f = make_frame(rows)
    assert [i for i, v in enumerate(f["halt"]) if v] == [5]

