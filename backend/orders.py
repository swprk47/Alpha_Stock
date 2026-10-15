"""
orders.py
주문 서비스: 체결가·종목명은 서버가 실시간 시세로만 결정한다.
시세 조회 실패/비정상 값이면 주문을 거부(503)한다.
"""
from fastapi import HTTPException

import market_data
from portfolio import MultiUserPortfolioManager, OrderError
from schemas import BuyRequest, SellRequest

DEFAULT_TARGET_RATIO = 1.065
DEFAULT_STOP_RATIO = 0.97


def fetch_live_quote(code: str) -> dict:
    try:
        info = market_data.get_realtime_stock_info(code)
    except Exception:
        info = None
    price = (info or {}).get("current_price")
    if not info or not isinstance(price, int) or price <= 0:
        raise HTTPException(status_code=503, detail="실시간 시세를 조회할 수 없어 주문을 거부했습니다. 잠시 후 다시 시도하세요.")
    return info


def _is_fractional(code: str) -> bool:
    try:
        ok, _ = market_data.is_stock_fractional_tradable(code)
        return bool(ok)
    except Exception:
        return False  # 판별 실패 시 보수적으로 정수만 허용


def place_buy(mgr: MultiUserPortfolioManager, user_id: str, req: BuyRequest) -> dict:
    quote = fetch_live_quote(req.code)
    price = quote["current_price"]
    target = req.target_price or int(price * DEFAULT_TARGET_RATIO)
    stop = req.stop_loss_price or int(price * DEFAULT_STOP_RATIO)
    needs_fraction = abs(req.quantity - round(req.quantity)) > 1e-6
    try:
        return mgr.buy(
            user_id=user_id, code=req.code, name=quote.get("name") or req.code,
            price=price, quantity=req.quantity, target_price=target, stop_loss_price=stop,
            max_hold_days=req.max_hold_days,
            allow_fractional=_is_fractional(req.code) if needs_fraction else True,
        )
    except OrderError as e:
        raise HTTPException(status_code=400, detail=str(e))


def place_sell(mgr: MultiUserPortfolioManager, user_id: str, req: SellRequest) -> dict:
    if mgr.get_holding_quantity(user_id, req.code) <= 0:
        raise HTTPException(status_code=400, detail="보유하고 있지 않은 종목입니다.")
    quote = fetch_live_quote(req.code)
    try:
        return mgr.sell(user_id=user_id, code=req.code, price=quote["current_price"], quantity=req.quantity)
    except OrderError as e:
        raise HTTPException(status_code=400, detail=str(e))
