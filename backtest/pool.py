"""날짜별 후보 풀: 앱의 후보 선정 규칙(가격 범위, 거래대금, 시총 순서 앞 30개)을 과거 일봉에 적용한다."""
import pandas as pd

POOL_LIMIT = 30
MIN_PRICE = 1000
MIN_VALUE_M = 2000      # 거래대금 2000백만원(20억) 이상


def select_pool(listings, frames, date: pd.Timestamp, max_price: int, *,
                min_price: int = MIN_PRICE, min_value_m: int = MIN_VALUE_M, limit: int = POOL_LIMIT) -> list:
    """상장 목록 순서대로 date 에 거래 가능하고 가격·거래대금 조건을 만족하는 코드의 앞 limit 개.
    vol_break 는 여기서 거르지 않는다(실제 후보 풀의 슬롯 구조를 유지하고 신호 단계에서 뺀다)."""
    pool = []
    for item in listings:
        frame = frames.get(item.code)
        if frame is None or date not in frame.index:
            continue
        row = frame.loc[date]
        if row["halt"]:
            continue
        close = row["close"]
        if not (min_price <= close <= max_price):
            continue
        if close * row["volume"] / 1_000_000 < min_value_m:
            continue
        pool.append(item.code)
        if len(pool) >= limit:
            break
    return pool
