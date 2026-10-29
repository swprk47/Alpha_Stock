"""
orders.py
주문 서비스: 체결가·종목명은 서버가 실시간 시세로만 결정한다.
시세 조회 실패/비정상 값이면 주문을 거부(503)한다.
"""
from fastapi import HTTPException

import market_data
from portfolio import MultiUserPortfolioManager, OrderError
from schemas import BuyRequest, SellPreviewQuery, SellRequest

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


MARKET_BLOCK_MESSAGE = "장 마감 중에는 주문하지 않도록 설정돼 있어요. 내 메뉴에서 바꿀 수 있어요."
_NOT_REGULAR = ("pre", "after", "closed")


def enforce_market_policy(mgr: MultiUserPortfolioManager, user_id: str, quote: dict) -> None:
    """설정이 "차단"이고 이 주문의 시세가 정규장이 아니면(pre/after/closed) 409 로 거절한다.
    regular 는 항상 허용, unknown(모르는 값·키 없음)은 막지 않는다(연습을 막지 않는 쪽). 판단은 주문 시점에 받은 시세로 한다."""
    state = ((quote or {}).get("market_state") or {}).get("state", "unknown")
    if state in _NOT_REGULAR and not mgr.get_settings(user_id).get("allow_closed_trading", True):
        raise HTTPException(status_code=409, detail=MARKET_BLOCK_MESSAGE)


def _is_fractional(code: str) -> bool:
    try:
        ok, _ = market_data.is_stock_fractional_tradable(code)
        return bool(ok)
    except Exception:
        return False  # 판별 실패 시 보수적으로 정수만 허용


def place_buy(mgr: MultiUserPortfolioManager, user_id: str, req: BuyRequest) -> dict:
    quote = fetch_live_quote(req.code)
    enforce_market_policy(mgr, user_id, quote)
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


def _check_sell_quantity(mgr: MultiUserPortfolioManager, user_id: str, code: str, quantity) -> None:
    """소수점 거래가 안 되는 종목은 정수 수량만 매도할 수 있다. 보유 전량을 매도하는 것은 예외."""
    if quantity is None:
        return
    q = round(float(quantity), 4)
    if abs(q - round(q)) <= 1e-6:
        return
    if abs(q - round(mgr.get_holding_quantity(user_id, code), 4)) <= 1e-6:
        return
    if not _is_fractional(code):
        raise HTTPException(status_code=400, detail="소수점 거래가 지원되지 않는 종목입니다. 정수 수량만 가능합니다. (전량 매도는 가능합니다)")


def place_sell(mgr: MultiUserPortfolioManager, user_id: str, req: SellRequest) -> dict:
    if mgr.get_holding_quantity(user_id, req.code) <= 0:
        raise HTTPException(status_code=400, detail="보유하고 있지 않은 종목입니다.")
    quote = fetch_live_quote(req.code)
    enforce_market_policy(mgr, user_id, quote)
    _check_sell_quantity(mgr, user_id, req.code, req.quantity)
    try:
        return mgr.sell(user_id=user_id, code=req.code, price=quote["current_price"], quantity=req.quantity)
    except OrderError as e:
        raise HTTPException(status_code=400, detail=str(e))


def place_sell_preview(mgr: MultiUserPortfolioManager, user_id: str, query: SellPreviewQuery) -> dict:
    """읽기 전용: 실제 매도와 같은 검증 순서(미보유 400 → 시세 503 → 소수 수량 400 → 계산)."""
    if mgr.get_holding_quantity(user_id, query.code) <= 0:
        raise HTTPException(status_code=400, detail="보유하고 있지 않은 종목입니다.")
    quote = fetch_live_quote(query.code)
    _check_sell_quantity(mgr, user_id, query.code, query.quantity)
    try:
        return mgr.preview_sell(user_id=user_id, code=query.code, price=quote["current_price"], quantity=query.quantity)
    except OrderError as e:
        raise HTTPException(status_code=400, detail=str(e))
