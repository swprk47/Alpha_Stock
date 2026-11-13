import numpy as np
import pandas as pd
import pytest

from backtest.data import CandleCache
from backtest.forward import registry
from backtest.forward.frames import load_all, prepare, truncate
from tests.bt_fw_helpers import frame_from_closes, frame_from_returns, raw_from_closes


def test_prepare_returns_and_flags():
    f = frame_from_closes([100, 110, 0, 121, 200])
    assert list(f.columns) == ["open", "high", "low", "close", "volume", "halt", "ret", "bad"]
    exp = [np.nan, 0.10, np.nan, np.nan, 200 / 121 - 1]
    np.testing.assert_allclose(f["ret"].to_numpy(), exp, equal_nan=True)
    assert f["halt"].tolist() == [False, False, True, False, False]
    assert f["bad"].tolist() == [False, False, False, False, True]


def test_prepare_halt_on_zero_volume():
    raw = raw_from_closes([100, 101, 102])
    raw.loc[1, "volume"] = 0
    f = prepare(raw)
    assert f["halt"].tolist() == [False, True, False]
    assert f["ret"].isna().tolist() == [True, True, True]


def test_bad_uses_registry_threshold():
    f = frame_from_returns([registry.BAD_RETURN + 0.01, 0.0, -(registry.BAD_RETURN + 0.01), 0.1])
    assert f["bad"].tolist() == [False, True, False, True, False]


def test_prepare_drops_duplicate_dates_and_sorts():
    raw = raw_from_closes([100, 110, 120])
    dup = raw.iloc[[1]].copy()
    dup["close"] = 999.0
    dup["open"] = dup["high"] = dup["low"] = 999.0
    mixed = pd.concat([raw.iloc[[2]], dup, raw.iloc[[0, 1]]], ignore_index=True)
    f = prepare(mixed)
    assert f.index.is_monotonic_increasing and f.index.is_unique
    assert len(f) == 3
    # 같은 날짜는 입력에서 마지막 것
    assert f["close"].iloc[1] == 110.0
    assert f["close"].tolist() == [100.0, 110.0, 120.0]


def test_truncate_does_not_change_earlier_rows():
    raw = raw_from_closes([100 + (i * 7) % 13 - (50 if i == 14 else 0) for i in range(30)])
    full = prepare(raw)
    head = prepare(raw.iloc[:10])
    pd.testing.assert_frame_equal(full.iloc[:10], head)


def test_truncate_cuts_and_drops_and_does_not_mutate():
    a = frame_from_closes(range(100, 130), start="2020-01-01")
    b = frame_from_closes(range(100, 110), start="2021-01-01")
    frames = {"A": a, "B": b}
    out = truncate(frames, "2020-01-10")
    assert set(out) == {"A"}
    assert out["A"].index.max() <= pd.Timestamp("2020-01-10")
    assert out["A"].equals(a[a.index <= "2020-01-10"])
    assert set(frames) == {"A", "B"} and len(frames["A"]) == 30
    out2 = truncate(frames, pd.Timestamp("2020-01-10"))
    assert out2["A"].equals(out["A"])


def test_load_all_skips_missing_and_short(tmp_path):
    cache = CandleCache(tmp_path)
    cache.save("A", raw_from_closes([100 + i for i in range(100)]))
    cache.save("B", raw_from_closes([100 + i for i in range(10)]))
    frames, skipped = load_all(["C", "A", "B"], cache)
    assert set(frames) == {"A"}
    assert skipped == ["C", "B"]
    assert "ret" in frames["A"].columns
    frames2, skipped2 = load_all(["B"], cache, min_rows=5)
    assert set(frames2) == {"B"} and skipped2 == []


def test_truncate_does_not_change_earlier_rows_with_bad_row_in_prefix():
    # 6번째 행이 +50%(bad)이고 10번째 행이 -40%(bad): 둘 다 비교하는 앞 12행 안에 있다
    closes = [100, 101, 102, 103, 104, 156, 157, 158, 159, 95.4, 96, 97] + [100 + i for i in range(18)]
    raw = raw_from_closes(closes)
    full = prepare(raw)
    head = prepare(raw.iloc[:12])
    assert head["bad"].tolist()[5] and head["bad"].tolist()[9] and head["bad"].sum() == 2
    pd.testing.assert_frame_equal(full.iloc[:12], head)


@pytest.mark.parametrize("col", ["open", "high", "low", "close", "volume"])
def test_prepare_nan_in_any_price_column_is_halt(col):
    raw = raw_from_closes([100, 101, 102, 103, 104])
    raw[col] = raw[col].astype(float)
    raw.loc[2, col] = np.nan
    f = prepare(raw)
    assert f["halt"].tolist() == [False, False, True, False, False]
    # 그 행과 다음 행의 수익률은 없다
    assert f["ret"].isna().tolist() == [True, False, True, True, False]
    assert not f["bad"].any()
