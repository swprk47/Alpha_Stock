from conftest import login


def portfolio(c):
    return c.get("/api/portfolio").json()["portfolio"]


def test_buy_uses_server_price(client):
    login(client)
    r = client.post("/api/buy", json={"code": "005930", "quantity": 3})
    assert r.status_code == 200, r.text
    o = r.json()["order"]
    assert o["price"] == 10_000 and o["name"] == "삼성전자"
    p = portfolio(client)
    assert p["cash_balance"] == 100_000 - 30_004  # 30,000 + 수수료 4
    assert p["holdings"][0]["avg_price"] == 10_000


def test_client_price_field_rejected(client):
    login(client)
    r = client.post("/api/buy", json={"code": "005930", "quantity": 1, "price": -1_000_000})
    assert r.status_code == 422
    assert portfolio(client)["cash_balance"] == 100_000


def test_client_name_logo_rejected(client):
    login(client)
    r = client.post("/api/buy", json={"code": "005930", "quantity": 1, "name": "가짜"})
    assert r.status_code == 422


def test_quote_failure_503(client):
    login(client)
    client.quotes["005930"] = None
    assert client.post("/api/buy", json={"code": "005930", "quantity": 1}).status_code == 503


def test_zero_price_quote_503(client):
    login(client)
    client.quotes["005930"] = {"code": "005930", "name": "x", "current_price": 0}
    assert client.post("/api/buy", json={"code": "005930", "quantity": 1}).status_code == 503


def test_invalid_inputs_422(client):
    login(client)
    for body in [
        {"code": "5930", "quantity": 1},
        {"code": "../../x", "quantity": 1},
        {"code": "005930", "quantity": 0},
        {"code": "005930", "quantity": -1},
        {"code": "005930", "quantity": 10**9},
        {"code": "005930", "quantity": 1, "max_hold_days": 0},
        {"code": "005930", "quantity": 1, "max_hold_days": 31},
    ]:
        assert client.post("/api/buy", json=body).status_code == 422, body


def test_insufficient_cash_400(client):
    login(client)
    r = client.post("/api/buy", json={"code": "005930", "quantity": 10})
    assert r.status_code == 400  # 100,000 + 수수료 > 잔고


def test_target_stop_order_validation(client):
    login(client)
    r = client.post("/api/buy", json={"code": "005930", "quantity": 1, "target_price": 9_000})
    assert r.status_code == 400
    r = client.post("/api/buy", json={"code": "005930", "quantity": 1, "stop_loss_price": 11_000})
    assert r.status_code == 400


def test_fractional_not_allowed(client):
    login(client)
    client.frac["005930"] = False
    assert client.post("/api/buy", json={"code": "005930", "quantity": 0.5}).status_code == 400
    assert client.post("/api/buy", json={"code": "005930", "quantity": 1}).status_code == 200


def test_fractional_allowed(client):
    login(client)
    assert client.post("/api/buy", json={"code": "005930", "quantity": 0.5}).status_code == 200


def test_sell_uses_server_price_and_pnl(client):
    login(client)
    client.post("/api/buy", json={"code": "005930", "quantity": 5})
    client.quotes["005930"]["current_price"] = 11_000
    r = client.post("/api/sell", json={"code": "005930", "quantity": 2})
    assert r.status_code == 200
    o = r.json()["order"]
    # 22,000 - 수수료 3 - 세금 39 = 21,958 ; 원가 20,000
    assert o["net"] == 21_958 and o["pnl"] == 1_958


def test_oversell_400(client):
    login(client)
    client.post("/api/buy", json={"code": "005930", "quantity": 2})
    r = client.post("/api/sell", json={"code": "005930", "quantity": 3})
    assert r.status_code == 400
    assert portfolio(client)["holdings"][0]["quantity"] == 2


def test_sell_not_held_400(client):
    login(client)
    assert client.post("/api/sell", json={"code": "005930"}).status_code == 400


def test_sell_all_default(client):
    login(client)
    client.post("/api/buy", json={"code": "005930", "quantity": 2})
    assert client.post("/api/sell", json={"code": "005930"}).status_code == 200
    assert portfolio(client)["holdings"] == []


def test_budget_range(client):
    login(client)
    assert client.post("/api/portfolio/budget", json={"budget": 0}).status_code == 422
    assert client.post("/api/portfolio/budget", json={"budget": 10**10}).status_code == 422
    assert client.post("/api/portfolio/budget", json={"budget": 200_000}).status_code == 200
    assert portfolio(client)["cash_balance"] == 200_000


def test_concurrent_buys_no_overdraft(client):
    import threading
    import server
    login(client)
    from auth import dev_user_id
    uid = dev_user_id("alice")
    from orders import place_buy
    from schemas import BuyRequest
    errors = []

    def worker():
        try:
            place_buy(server.portfolio_mgr, uid, BuyRequest(code="005930", quantity=1))
        except Exception as e:
            errors.append(e)

    ts = [threading.Thread(target=worker) for _ in range(20)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    p = portfolio(client)
    assert p["cash_balance"] >= 0
    assert p["holdings"][0]["quantity"] == 9  # 10,001원×9 ≤ 100,000
