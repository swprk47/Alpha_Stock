"""
fees.py
수수료·세금 계산 순수 함수 (원 단위 절사, 기존 계산식의 부동소수 오차 보정)
"""
import math

import config


def _apply_rate(amount: int, rate: float) -> int:
    """금액×요율을 원 단위 절사. 부동소수 오차(예: 100000*0.00015=14.999…) 보정."""
    return math.floor(round(amount * rate, 6))


def calc_buy_cost(price: int, quantity: float) -> dict:
    gross = int(price * quantity)
    fee = _apply_rate(gross, config.BUY_FEE_RATE)
    return {"gross": gross, "fee": fee, "total": gross + fee}


def calc_sell_proceeds(price: int, quantity: float) -> dict:
    gross = int(price * quantity)
    fee = _apply_rate(gross, config.SELL_FEE_RATE)
    tax = _apply_rate(gross, config.SELL_TAX_RATE)
    return {"gross": gross, "fee": fee, "tax": tax, "net": gross - fee - tax}


def estimate_sell_cost(eval_amount: int) -> int:
    """평가금액 기준 예상 매도 비용(기존 요약 계산식)."""
    return _apply_rate(eval_amount, config.SELL_FEE_RATE + config.SELL_TAX_RATE)
