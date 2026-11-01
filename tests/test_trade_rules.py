"""거래 안내 팝업이 쓰는 GET /api/trade-rules.

화면에 보이는 수수료·세율·스윙 룰 숫자는 앱이 실제 계산에 쓰는 값에서 만든다.
그래서 계산 쪽 값이 바뀌면 이 응답도 같이 바뀌고, 이 테스트가 둘이 어긋나면 알려 준다.
"""
import config
import orders
from fees import calc_buy_cost, calc_sell_proceeds
from strategy import calculate_position_sizing


def _rules(client):
    r = client.get("/api/trade-rules")
    assert r.status_code == 200
    return r.json()


def test_rules_are_public_and_have_every_field(client):
    body = _rules(client)  # 로그인 없이 읽는다(고정된 거래 기준이라 개인정보가 아니다)
    assert body["success"] is True
    assert set(body["rules"]) == {"buy_fee_pct", "sell_fee_pct", "sell_tax_pct", "target_pct", "stop_pct", "max_hold_days"}
    assert all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in body["rules"].values())


def test_default_values(client):
    rules = _rules(client)["rules"]
    assert rules == {"buy_fee_pct": 0.015, "sell_fee_pct": 0.015, "sell_tax_pct": 0.2,
                     "target_pct": 6.5, "stop_pct": -3.0, "max_hold_days": 5}


def test_fee_rates_follow_config_at_request_time(client, monkeypatch):
    monkeypatch.setattr(config, "BUY_FEE_RATE", 0.0003)
    monkeypatch.setattr(config, "SELL_FEE_RATE", 0.0002)
    monkeypatch.setattr(config, "SELL_TAX_RATE", 0.001)
    rules = _rules(client)["rules"]
    assert (rules["buy_fee_pct"], rules["sell_fee_pct"], rules["sell_tax_pct"]) == (0.03, 0.02, 0.1)


def test_fee_numbers_match_the_real_calculation(client):
    rules = _rules(client)["rules"]
    gross = 1_000_000
    assert calc_buy_cost(gross, 1)["fee"] == round(gross * rules["buy_fee_pct"] / 100)
    sell = calc_sell_proceeds(gross, 1)
    assert sell["fee"] == round(gross * rules["sell_fee_pct"] / 100)
    assert sell["tax"] == round(gross * rules["sell_tax_pct"] / 100)


def test_swing_numbers_match_the_strategy_and_the_order_defaults(client):
    rules = _rules(client)["rules"]
    sizing = calculate_position_sizing({"current_price": 10_000})
    assert rules["target_pct"] == sizing["target_return_pct"]
    assert rules["stop_pct"] == sizing["stop_loss_pct"]
    assert rules["max_hold_days"] == sizing["max_hold_days"]
    # 매수 주문이 목표가·손절가를 안 받았을 때 쓰는 비율과도 같다
    price = 1_000_000
    assert int(price * orders.DEFAULT_TARGET_RATIO) == int(price * (1 + rules["target_pct"] / 100))
    assert int(price * orders.DEFAULT_STOP_RATIO) == int(price * (1 + rules["stop_pct"] / 100))
