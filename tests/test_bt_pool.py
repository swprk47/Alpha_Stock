from bt_helpers import DATE, listing, make_frame, one
from backtest.pool import select_pool


def test_filters_and_keeps_listing_order():
    frames = {"A": one(999, 10_000_000),          # 가격 미달
              "B": one(60_000, 1_000_000),         # max_price 50_000 초과
              "C": one(10_000, 199_999),           # 거래대금 1_999.99 백만 < 2_000
              "D": one(10_000, 0),                 # 거래정지
              "E": one(10_000, 300_000), "F": one(20_000, 150_000)}
    assert select_pool(listing("ABCDEF"), frames, DATE, 50_000) == ["E", "F"]


def test_boundaries_are_inclusive():
    frames = {"A": one(1_000, 2_000_000), "B": one(50_000, 40_000), "C": one(10_000, 200_000)}   # 1000원, 상한 50_000원, 정확히 2000 백만
    assert select_pool(listing("ABC"), frames, DATE, 50_000) == ["A", "B", "C"]


def test_limit_cuts_after_the_first_thirty_in_listing_order():
    codes = [f"S{i:02d}" for i in range(40)]
    frames = {c: one(10_000, 300_000) for c in codes}
    assert select_pool(listing(codes), frames, DATE, 50_000) == codes[:30]


def test_missing_date_and_vol_break_rows():
    short = make_frame([(10_000,) * 4 + (300_000,)], start="2025-01-06")    # 기준일 행이 없는 종목
    marked = one(10_000, 300_000)
    marked["vol_break"] = True                                               # 풀에는 남는다(신호 단계에서 거른다)
    assert select_pool(listing("SM"), {"S": short, "M": marked}, DATE, 50_000) == ["M"]


def test_pre_split_rows_stay_out_of_the_pool():
    pre, post = one(10_000, 300_000), one(10_000, 300_000)
    pre["pre_split"] = True                                                  # 분할 전 기간: 실제(명목) 가격이 조정 가격보다 높았다
    assert select_pool(listing("PQ"), {"P": pre, "Q": post}, DATE, 50_000) == ["Q"]

