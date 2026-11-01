"""
trade_rules.py
거래 안내 팝업에 보이는 수수료·세율·스윙 룰. 앱이 실제 계산에 쓰는 값에서 매 요청마다 만든다
(화면용 숫자를 따로 적어 두면 세율을 .env 로 바꿨을 때 계산과 어긋난다).
"""
import config
from orders import DEFAULT_STOP_RATIO, DEFAULT_TARGET_RATIO
from schemas import BuyRequest


def _pct(rate: float) -> float:
    """비율(0.00015) → 퍼센트(0.015). 부동소수 꼬리를 4자리에서 정리한다."""
    return round(rate * 100, 4)


def get_trade_rules() -> dict:
    return {
        "buy_fee_pct": _pct(config.BUY_FEE_RATE),
        "sell_fee_pct": _pct(config.SELL_FEE_RATE),
        "sell_tax_pct": _pct(config.SELL_TAX_RATE),
        "target_pct": round((DEFAULT_TARGET_RATIO - 1) * 100, 2),
        "stop_pct": round((DEFAULT_STOP_RATIO - 1) * 100, 2),
        "max_hold_days": BuyRequest.model_fields["max_hold_days"].default,
    }
