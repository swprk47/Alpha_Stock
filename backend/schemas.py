"""
schemas.py
요청 스키마. user_id / price / name / logo_url 은 받지 않는다(서버가 결정).
"""
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

import config

# 종목코드: 영숫자 대문자 6자리 (예: 005930, 신규 ETF 0183J0)
CODE_PATTERN = r"^[0-9A-Z]{6}$"


class _Strict(BaseModel):
    # 알 수 없는 필드(user_id, price 등)가 오면 422로 거부
    model_config = ConfigDict(extra="forbid")


class DevLoginRequest(_Strict):
    nickname: str = Field(..., min_length=1, max_length=30)


class BuyRequest(_Strict):
    code: str = Field(..., pattern=CODE_PATTERN)
    quantity: float = Field(..., gt=0, le=config.MAX_ORDER_QUANTITY, allow_inf_nan=False)
    target_price: Optional[int] = Field(None, gt=0)
    stop_loss_price: Optional[int] = Field(None, gt=0)
    max_hold_days: int = Field(5, ge=1, le=30)


class SellRequest(_Strict):
    code: str = Field(..., pattern=CODE_PATTERN)
    quantity: Optional[float] = Field(None, gt=0, le=config.MAX_ORDER_QUANTITY, allow_inf_nan=False)


class SetBudgetRequest(_Strict):
    budget: int = Field(..., ge=config.MIN_BUDGET, le=config.MAX_BUDGET)
