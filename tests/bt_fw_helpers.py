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


def frame_from_rows(rows, start="2020-01-01"):
    """(시가, 종가) 또는 (시가, 종가, 거래량) 행 목록으로 만든 프레임. 고가·저가는 시가·종가의 최대·최소."""
    dates = pd.bdate_range(start, periods=len(rows))
    recs = []
    for d, row in zip(dates, rows):
        o, c = float(row[0]), float(row[1])
        v = row[2] if len(row) > 2 else 1000
        recs.append({"date": d, "open": o, "high": max(o, c), "low": min(o, c), "close": c, "volume": v})
    return prepare(pd.DataFrame(recs))


# ------------------------------------------------------------------ 단계 명령 테스트용 합성 캐시
def synthetic_raw(seed, start="2014-08-01", end="2024-12-31", drift=0.0003, vol=0.015):
    """고정 시드 난수로 만든 일봉(date, open, high, low, close, volume). 시가는 전일 종가."""
    import numpy as np
    dates = pd.bdate_range(start, end)
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, len(dates))
    close = 10_000.0 * np.cumprod(1.0 + rets)
    open_ = np.concatenate([[10_000.0], close[:-1]])
    return pd.DataFrame({"date": dates, "open": open_,
                         "high": np.maximum(open_, close), "low": np.minimum(open_, close),
                         "close": close, "volume": 1000})


def stock_codes(n=12):
    return [f"{100000 + i}" for i in range(n)]


def build_candle_cache(root, codes, bench="069500", with_bench=True):
    """codes 의 합성 일봉과(옵션) 벤치마크 일봉을 root 캐시에 저장한다."""
    from backtest.data import CandleCache
    cache = CandleCache(root)
    for i, code in enumerate(codes):
        cache.save(code, synthetic_raw(i + 1, vol=0.01 + 0.002 * (i % 5)))
    if with_bench:
        cache.save(bench, synthetic_raw(999, drift=0.0004, vol=0.01))
    return cache


def fake_listing(codes):
    """Listing 목록을 돌려주는 가짜 fetch_listing."""
    from backtest.data import Listing
    items = [Listing(c, f"종목{c}", "KOSPI" if i < len(codes) // 2 else "KOSDAQ", i)
             for i, c in enumerate(codes)]
    return lambda: items


def no_fetch(code, count):
    """네트워크 없이 항상 못 받은 것으로 처리하는 fetch_candles."""
    return None
