"""후보 ② 신호: KODEX 200 월말 종가의 10개월 평균 게이트.

신호일 종가가 그 신호일까지의 월말 종가(신호일 포함) 최근 months개 평균보다 낮으면
다음 달은 현금(False), 아니면 보유(True). 월말 종가가 months개 미만이면 보유(True).
"""
import math

import pandas as pd


def gate_states(bench: pd.DataFrame, all_periods: list, *, months: int = 10) -> dict:
    """신호일 -> 다음 달 보유 여부(True=보유, False=현금). 신호일 이후 데이터는 보지 않는다."""
    signal_days = [p.signal_day for p in all_periods]
    # 신호일이 벤치마크에 없으면 호출자 오류이므로 KeyError가 그대로 올라간다.
    month_end_closes = [float(bench.loc[d, "close"]) for d in signal_days]
    for d, c in zip(signal_days, month_end_closes):
        if not math.isfinite(c) or c <= 0:
            raise ValueError(f"신호일 {pd.Timestamp(d).date()} 의 KODEX 200 종가가 없거나 0 이하다: {c}")
    states = {}
    for i, day in enumerate(signal_days):
        if i + 1 < months:
            states[day] = True
            continue
        window = month_end_closes[i + 1 - months : i + 1]
        average = sum(window) / months
        states[day] = month_end_closes[i] >= average
    return states
