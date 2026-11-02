"""백테스트 테스트용 도우미: 손으로 만든 일봉 프레임."""
import pandas as pd

from backtest.data import prepare_frame


def make_raw(rows, start="2026-01-05"):
    """rows 는 (open, high, low, close, volume) 튜플 목록. 날짜는 start 부터 영업일."""
    dates = pd.bdate_range(start, periods=len(rows))
    df = pd.DataFrame(list(rows), columns=["open", "high", "low", "close", "volume"])
    df.insert(0, "date", dates)
    return df


def make_frame(rows, start="2026-01-05"):
    return prepare_frame(make_raw(rows, start))


def flat_rows(n, price=10_000, volume=100_000):
    return [(price, price, price, price, volume)] * n
