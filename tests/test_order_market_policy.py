"""장 마감 중 주문 정책: 설정이 "차단"이고 장 상태가 pre/after/closed 이면 서버가 409 로 거절한다.

- regular 는 항상 허용, unknown(모르는 값·키 없음)은 막지 않는다(연습을 막지 않는 쪽), 설정이 켜져 있으면 모두 허용
- 매수·매도(부분·전량) 모두 막고, 매도 미리보기(읽기 전용)는 막지 않는다
- 검증 순서: 매도 미보유 400 → 시세 503 → 정책 409 → 소수 수량 400, 매수는 시세 503 → 정책 409 → 체결
- 판단은 주문 시점에 받은 그 종목의 시세(market_state)로 한다(추천 캐시의 상태가 아니다)
"""
import pytest

from conftest import login

BLOCK = "장 마감 중에는 주문하지 않도록 설정돼 있어요. 내 메뉴에서 바꿀 수 있어요."


def _state(client, state):
    if state is None:
        client.quotes["005930"].pop("market_state", None)
    else:
        client.quotes["005930"]["market_state"] = {"state": state, "nxt_listed": True}


def _allow(client, flag):
    assert client.post("/api/settings", json={"allow_closed_trading": flag}).status_code == 200


def _holding_qty(client):
    hs = client.get("/api/portfolio").json()["portfolio"]["holdings"]
    return hs[0]["quantity"] if hs else 0


def test_block_message_is_the_spec_text():
    import orders
    assert orders.MARKET_BLOCK_MESSAGE == BLOCK


@pytest.mark.parametrize("state,allow,expected", [
    ("pre", False, 409), ("after", False, 409), ("closed", False, 409),
    ("regular", False, 200), ("unknown", False, 200), (None, False, 200),
    ("pre", True, 200), ("after", True, 200), ("closed", True, 200),
    ("regular", True, 200), ("unknown", True, 200), (None, True, 200),
])
def test_buy_policy_table(client, state, allow, expected):
    login(client)
    _allow(client, allow)
    _state(client, state)
    r = client.post("/api/buy", json={"code": "005930", "quantity": 1})
    assert r.status_code == expected
    if expected == 409:
        assert r.json()["detail"] == BLOCK


@pytest.mark.parametrize("state,expected", [("pre", 409), ("after", 409), ("closed", 409), ("regular", 200), ("unknown", 200)])
@pytest.mark.parametrize("body", [{"code": "005930"}, {"code": "005930", "quantity": 1}], ids=["full", "partial"])
def test_sell_policy_blocks_partial_and_full(client, state, expected, body):
    login(client)
    assert client.post("/api/buy", json={"code": "005930", "quantity": 3}).status_code == 200
    _allow(client, False)
    _state(client, state)
    r = client.post("/api/sell", json=body)
    assert r.status_code == expected
    if expected == 409:
        assert r.json()["detail"] == BLOCK


def test_sell_preview_is_never_blocked(client):
    login(client)
    assert client.post("/api/buy", json={"code": "005930", "quantity": 3}).status_code == 200
    _allow(client, False)
    _state(client, "closed")
    assert client.get("/api/sell/preview", params={"code": "005930"}).status_code == 200


def test_blocked_orders_change_nothing(client):
    login(client)
    assert client.post("/api/buy", json={"code": "005930", "quantity": 3}).status_code == 200
    cash_before = client.get("/api/portfolio").json()["portfolio"]["cash_balance"]
    _allow(client, False)
    _state(client, "after")
    assert client.post("/api/buy", json={"code": "005930", "quantity": 1}).status_code == 409
    assert client.post("/api/sell", json={"code": "005930"}).status_code == 409
    assert _holding_qty(client) == 3
    assert client.get("/api/portfolio").json()["portfolio"]["cash_balance"] == cash_before


def test_quote_failure_is_503_before_the_policy(client):
    login(client)
    _allow(client, False)
    del client.quotes["005930"]
    assert client.post("/api/buy", json={"code": "005930", "quantity": 1}).status_code == 503


def test_policy_uses_the_quote_taken_at_order_time(client):
    login(client)
    _allow(client, False)
    _state(client, "regular")
    assert client.post("/api/buy", json={"code": "005930", "quantity": 1}).status_code == 200
    _state(client, "closed")  # 화면에 불러 둔 상태가 정규장이었더라도 주문 시점 시세가 닫혔으면 거절
    assert client.post("/api/buy", json={"code": "005930", "quantity": 1}).status_code == 409
