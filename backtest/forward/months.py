"""월 달력: 달의 마지막 거래일에 신호를 보고, 달력에서 그다음 거래일에 교체한다."""
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Period:
    signal_day: pd.Timestamp
    trade_day: pd.Timestamp


def periods(calendar: pd.DatetimeIndex) -> list:
    """달마다 마지막 거래일(신호일)과 그다음 거래일(교체일). 다음 거래일이 없는 마지막 달은 뺀다."""
    cal = pd.DatetimeIndex(calendar).sort_values().unique()
    out = []
    for i in range(len(cal) - 1):
        if (cal[i].year, cal[i].month) != (cal[i + 1].year, cal[i + 1].month):
            out.append(Period(cal[i], cal[i + 1]))
    return out


def in_window(all_periods, start, end) -> list:
    """교체일이 start 이상 end 이하인 기간만."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    return [p for p in all_periods if start <= p.trade_day <= end]


def month_rows(frame: pd.DataFrame, signal_day) -> pd.DataFrame:
    """신호일과 같은 연·월이고 신호일 이하인 행."""
    day = pd.Timestamp(signal_day)
    idx = frame.index
    mask = (idx.year == day.year) & (idx.month == day.month) & (idx <= day)
    return frame.loc[mask]
