"""백테스트 테스트용 도우미: 손으로 만든 일봉 프레임."""
import pandas as pd

from backtest.data import Listing, prepare_frame


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


def one(close, volume, n=3):
    """같은 값의 일봉 n개짜리 프레임(마지막 날짜가 DATE)."""
    return make_frame([(close, close, close, close, volume)] * n)


def listing(codes):
    return [Listing(c, c, "KOSPI", i) for i, c in enumerate(codes)]


DATE = one(10_000, 1).index[-1]


def trending_rows(n):
    """완만한 상승과 눌림이 반복되는 일봉 n개. 앱의 analyze_stock_for_swing 점수가 80(RSI 약 58)이 되도록 맞춘 값."""
    rows, close = [], 10_000
    pattern = [60, -40, 50, -45, 55, -35]
    for i in range(n):
        new = close + pattern[i % len(pattern)]
        rows.append((close, max(close, new) + 20, min(close, new) - 20, new, 100_000))
        close = new
    return rows
