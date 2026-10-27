"""/api/portfolio 보유 종목의 is_fractional: 화면이 소수 수량 입력을 허용할지 정하는 데 쓴다.

값은 주문 계층의 판별(orders._is_fractional)과 같다. 목록에 없거나 판별에 실패하면 False(정수만).
"""
from conftest import login

CODE = "005930"


def _holding(client):
    r = client.get("/api/portfolio")
    assert r.status_code == 200
    return r.json()["portfolio"]["holdings"][0]


def _buy(client, qty=1):
    assert client.post("/api/buy", json={"code": CODE, "quantity": qty}).status_code == 200


def test_holding_reports_fractional_tradable(client):
    login(client)
    _buy(client)
    assert _holding(client)["is_fractional"] is True


def test_holding_reports_not_fractional_tradable(client):
    login(client)
    _buy(client)
    client.frac[CODE] = False
    assert _holding(client)["is_fractional"] is False


def test_lookup_failure_means_integer_only(client, monkeypatch):
    login(client)
    _buy(client)
    import orders

    def boom(code):
        raise RuntimeError("목록 조회 실패")

    monkeypatch.setattr(orders.market_data, "is_stock_fractional_tradable", boom)
    assert _holding(client)["is_fractional"] is False


def test_existing_holding_fields_are_unchanged(client):
    login(client)
    _buy(client, 2)
    h = _holding(client)
    for key in ("code", "name", "quantity", "avg_price", "current_price", "eval_amount",
                "unrealized_pnl", "pnl_pct", "est_proceeds", "est_realized_pnl", "price_stale"):
        assert key in h, key
