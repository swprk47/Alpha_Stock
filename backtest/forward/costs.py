"""연도별 매도세를 반영한 거래 비용 모델 (비율 계산, 원 단위 절사 없음).

세율 출처는 설계서 4절 표이며 config.SELL_TAX_RATE는 쓰지 않는다.
"""
import datetime as dt
from dataclasses import dataclass

import pandas as pd

import config
from backtest.forward.registry import SLIPPAGE

# (적용 시작일, 매도세율): 거래일이 시작일 이상인 마지막 항목을 쓴다.
_TAX_TABLE = (
    (dt.date(1900, 1, 1), 0.0030),
    (dt.date(2019, 5, 30), 0.0025),
    (dt.date(2021, 1, 1), 0.0023),
    (dt.date(2023, 1, 1), 0.0020),
    (dt.date(2024, 1, 1), 0.0018),
    (dt.date(2025, 1, 1), 0.0015),
    (dt.date(2026, 1, 1), 0.0020),
)


def sell_tax_rate(day) -> float:
    """거래일(datetime.date 또는 pd.Timestamp)의 매도세율."""
    if isinstance(day, pd.Timestamp):
        day = day.date()
    rate = _TAX_TABLE[0][1]
    for start, r in _TAX_TABLE:
        if day >= start:
            rate = r
    return rate


@dataclass(frozen=True)
class CostModel:
    multiplier: float = 1.0

    def buy_rate(self) -> float:
        return (config.BUY_FEE_RATE + SLIPPAGE) * self.multiplier

    def sell_rate(self, day, *, etf: bool) -> float:
        tax = 0 if etf else sell_tax_rate(day)
        return (config.SELL_FEE_RATE + tax + SLIPPAGE) * self.multiplier
