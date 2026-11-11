"""순방향 검증 테스트용 도우미: 손으로 만든 일봉 프레임."""
import pandas as pd

from backtest.forward.frames import prepare


def raw_from_closes(closes, start="2020-01-01", volume=1000):
    """영업일 달력에 시가=고가=저가=종가인 일봉."""
    dates = pd.bdate_range(start, periods=len(closes))
    c = [float(x) for x in closes]
    return pd.DataFrame({"date": dates, "open": c, "high": c, "low": c, "close": c, "volume": volume})


def frame_from_closes(closes, start="2020-01-01"):
    return prepare(raw_from_closes(closes, start))


def frame_from_returns(returns, start="2020-01-01", base=10_000.0):
    """첫 종가는 base, 이후는 수익률을 곱해 쌓은 종가로 만든 프레임."""
    closes, price = [base], base
    for r in returns:
        price *= 1.0 + r
        closes.append(price)
    return frame_from_closes(closes, start)
