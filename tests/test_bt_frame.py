import pandas as pd

from bt_helpers import flat_rows, make_frame, make_raw
from backtest.data import prepare_frame


def test_halt_and_index_and_sorting():
    raw = make_raw(flat_rows(10)).iloc[::-1]               # 뒤집힌 입력
    raw.loc[raw.index[0], "volume"] = 0                      # 가장 늦은 날이 거래정지
    f = prepare_frame(raw)
    assert f.index.is_monotonic_increasing and f.index.name == "date"
    assert list(f.columns) == ["open", "high", "low", "close", "volume", "halt", "vol_break"]
    assert f["halt"].iloc[-1] and not f["halt"].iloc[:-1].any()


def test_duplicate_dates_keep_the_last_row():
    raw = make_raw(flat_rows(6))
    dup = raw.iloc[[2]].copy()
    dup["close"] = 123
    f = prepare_frame(pd.concat([raw, dup]))
    assert len(f) == 6 and f["close"].iloc[2] == 123


def test_split_like_break_flags_six_rows_each_side_only():
    rows = flat_rows(20, volume=600) + flat_rows(3, volume=0) + flat_rows(18, volume=30_000)  # 삼성전자 2018형
    f = make_frame(rows)
    flagged = [i for i, v in enumerate(f["vol_break"]) if v]
    assert flagged == list(range(17, 30))                    # 분할 위치 23 의 앞뒤 6봉
    assert [i for i, v in enumerate(f["halt"]) if v] == [20, 21, 22]


def test_price_gap_with_volume_jump_is_not_a_split():
    rows = flat_rows(20, volume=600) + [(14_000, 14_000, 14_000, 14_000, 30_000)] * 15   # +40% 갭
    assert not make_frame(rows)["vol_break"].any()


def test_slow_volume_growth_and_single_spike_are_not_splits():
    growth = [(10_000,) * 4 + (v,) for v in range(1_000, 1_000 + 40 * 100, 100)]          # 점진 증가
    assert not make_frame(growth)["vol_break"].any()
    spike = flat_rows(15, volume=1_000) + [(10_000,) * 4 + (50_000,)] + flat_rows(15, volume=1_000)
    assert not make_frame(spike)["vol_break"].any()
