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


# ---- 수량별 매도 미리보기 ----
def _preview(client, **params):
    return client.get("/api/sell/preview", params={"code": CODE, **params})


def test_preview_equals_actual_sell_for_same_quantity(client):
    # (현재가, 매수 수량, 매도 수량): 평가금액 9,999원 경계·1원짜리 시세·소수 수량·일부/전량
    cases = [(9_999, 3, 1), (1, 5, 2), (10_000, 3, 0.5), (9_999, 1, None), (11_000, 5, 2), (12_345, 7, 3)]
    for price, bought, sold in cases:
        login(client, f"u{price}_{bought}")
        _buy(client, bought)
        client.quotes[CODE]["current_price"] = price
        params = {} if sold is None else {"quantity": sold}
        p = _preview(client, **params)
        assert p.status_code == 200, p.text
        pv = p.json()["preview"]
        o = client.post("/api/sell", json={"code": CODE, **params}).json()["order"]
        assert (pv["net"], pv["fee"], pv["tax"], pv["est_realized_pnl"]) == (o["net"], o["fee"], o["tax"], o["pnl"]), (price, bought, sold)
        assert pv["quantity"] == o["quantity"] and pv["price"] == o["price"]
        client.quotes[CODE]["current_price"] = 10_000


def test_preview_does_not_change_account(client):
    login(client)
    _buy(client, 3)
    before = _portfolio(client)
    assert _preview(client, quantity=1).status_code == 200
    after = _portfolio(client)
    assert (after["cash_balance"], after["holdings"][0]["quantity"], len(after["history"])) == \
           (before["cash_balance"], before["holdings"][0]["quantity"], len(before["history"]))


def test_preview_without_quantity_means_full_sell(client):
    login(client)
    _buy(client, 3)
    full = _preview(client).json()["preview"]
    assert full["quantity"] == 3 and full["gross"] == 30_000


def test_preview_rejects_over_quantity_400(client):
    login(client)
    _buy(client, 2)
    assert _preview(client, quantity=3).status_code == 400


def test_preview_not_held_400(client):
    login(client)
    assert _preview(client, quantity=1).status_code == 400


def test_preview_fractional_not_tradable_400(client):
    login(client)
    _buy(client, 3)
    client.frac[CODE] = False
    assert _preview(client, quantity=0.5).status_code == 400
    assert _preview(client, quantity=1).status_code == 200


def test_preview_bad_quantities_rejected(client):
    login(client)
    _buy(client, 3)
    for bad in ("0", "-1", "nan", "inf", "abc"):
        assert _preview(client, quantity=bad).status_code == 422, bad
    assert _preview(client, quantity=0.00004).status_code == 400  # 4자리 반올림 뒤 0


def test_preview_quote_failure_503(client):
    login(client)
    _buy(client, 3)
    client.quotes.pop(CODE)
    assert _preview(client, quantity=1).status_code == 503


def test_preview_requires_login_401(client):
    assert _preview(client, quantity=1).status_code == 401


def test_preview_is_per_user(client):
    login(client, "alice")
    _buy(client, 3)
    client.cookies.clear()
    login(client, "bob")
    assert _preview(client, quantity=1).status_code == 400


def test_preview_rejects_extra_params_422(client):
    login(client)
    _buy(client, 3)
    assert _preview(client, quantity=1, price=1).status_code == 422


def test_sell_response_shape_unchanged(client):
    login(client)
    _buy(client, 3)
    o = client.post("/api/sell", json={"code": CODE, "quantity": 1}).json()["order"]
    assert set(o) == {"code", "price", "quantity", "pnl", "gross", "fee", "tax", "net", "message"}
