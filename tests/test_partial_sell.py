"""부분 매도 서버 검증: 소수 수량 규칙과 수량별 매도 미리보기.

- 소수점 거래가 안 되는 종목은 정수 수량만 매도할 수 있다. 단 보유 전량을 매도하는 것은 항상 허용한다.
- 미리보기(GET /api/sell/preview)는 실제 매도(POST /api/sell)와 같은 검증·계산을 지나므로 값이 정확히 같다.
"""
from conftest import login

CODE = "005930"


def _buy(client, qty):
    r = client.post("/api/buy", json={"code": CODE, "quantity": qty})
    assert r.status_code == 200, r.text


def _portfolio(client):
    r = client.get("/api/portfolio")
    assert r.status_code == 200
    return r.json()["portfolio"]


def _qty(client):
    hs = _portfolio(client)["holdings"]
    return hs[0]["quantity"] if hs else 0


# ---- 소수 수량 검증 ----
def test_fractional_partial_sell_rejected_when_not_tradable(client):
    login(client)
    _buy(client, 3)
    cash = _portfolio(client)["cash_balance"]
    client.frac[CODE] = False
    r = client.post("/api/sell", json={"code": CODE, "quantity": 0.5})
    assert r.status_code == 400
    assert _qty(client) == 3 and _portfolio(client)["cash_balance"] == cash  # 거부되면 계정이 변하지 않는다


def test_integer_partial_sell_ok_when_not_tradable(client):
    # 기존 동작 회귀 방지
    login(client)
    _buy(client, 3)
    client.frac[CODE] = False
    assert client.post("/api/sell", json={"code": CODE, "quantity": 1}).status_code == 200
    assert _qty(client) == 2


def test_fractional_partial_sell_ok_when_tradable(client):
    login(client)
    _buy(client, 3)
    assert client.post("/api/sell", json={"code": CODE, "quantity": 0.5}).status_code == 200
    assert _qty(client) == 2.5


def test_full_sell_with_explicit_fractional_quantity_allowed_when_not_tradable(client):
    login(client)
    _buy(client, 2.5)  # 소수 거래가 가능했을 때 산 보유
    client.frac[CODE] = False
    assert client.post("/api/sell", json={"code": CODE, "quantity": 2.5}).status_code == 200
    assert _qty(client) == 0


def test_full_sell_without_quantity_unchanged_when_not_tradable(client):
    # 기존 동작 회귀 방지
    login(client)
    _buy(client, 2.5)
    client.frac[CODE] = False
    assert client.post("/api/sell", json={"code": CODE}).status_code == 200
    assert _qty(client) == 0


def test_partial_fractional_sell_of_fractional_holding_rejected_when_not_tradable(client):
    login(client)
    _buy(client, 2.5)
    client.frac[CODE] = False
    assert client.post("/api/sell", json={"code": CODE, "quantity": 1.5}).status_code == 400
    assert _qty(client) == 2.5


def test_sell_quantity_rounding_to_zero_rejected(client):
    login(client)
    _buy(client, 3)
    assert client.post("/api/sell", json={"code": CODE, "quantity": 0.00004}).status_code == 400
    assert _qty(client) == 3
