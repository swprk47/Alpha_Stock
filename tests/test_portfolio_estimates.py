"""보유 종목의 예상 수령액·예상 실현 손익(est_proceeds, est_realized_pnl) 검증.

서버가 실제 매도와 같은 함수(fees.calc_sell_proceeds)로 미리 계산해 내려주므로, 지금 팔았을 때의 순수령액·기록되는
손익과 정확히 같아야 한다. 기존 필드(unrealized_pnl 등)의 계산은 바뀌지 않는다. 시세를 못 받은 종목은 추정하지 않는다(None).
"""
import pytest

from conftest import login
from fees import estimate_sell_cost


def holding(c):
    p = c.get("/api/portfolio").json()["portfolio"]
    assert len(p["holdings"]) == 1
    return p["holdings"][0]


def buy_then_quote(c, qty, price):
    login(c)
    r = c.post("/api/buy", json={"code": "005930", "quantity": qty})
    assert r.status_code == 200, r.text
    c.quotes["005930"]["current_price"] = price


# 합산 절사와 개별 절사가 달라지는 경계(9,999원), 소수점 수량, 큰 수, 1원짜리 시세까지
CASES = [(1, 9_999), (3, 10_000), (3, 12_345), (0.5, 9_999), (2, 7_777), (1, 1), (5, 11_111), (4, 10_001)]


@pytest.mark.parametrize("qty,price", CASES)
def test_estimate_equals_what_an_actual_sell_returns(client, qty, price):
    buy_then_quote(client, qty, price)
    h = holding(client)
    sold = client.post("/api/sell", json={"code": "005930"})  # 전량 매도(기본)
    assert sold.status_code == 200, sold.text
    o = sold.json()["order"]
    assert h["est_proceeds"] == o["net"]
    assert h["est_realized_pnl"] == o["pnl"]


@pytest.mark.parametrize("qty,price", CASES)
def test_estimated_realized_pnl_is_what_the_account_records(client, qty, price):
    buy_then_quote(client, qty, price)
    est = holding(client)["est_realized_pnl"]
    client.post("/api/sell", json={"code": "005930"})
    assert client.get("/api/portfolio").json()["portfolio"]["realized_pnl"] == est


def test_boundary_case_shows_why_the_screen_must_not_calculate_it(client):
    # 평가금액 9,999원: 실제 매도는 수수료 1 + 세금 19 = 20원, 기존 예상(unrealized_pnl)은 합산 절사로 21원
    buy_then_quote(client, 1, 9_999)
    h = holding(client)
    assert h["est_proceeds"] == 9_979  # 9,999 - 20
    assert h["est_realized_pnl"] == -21  # 9,979 - 매입 10,000
    assert estimate_sell_cost(9_999) == 21
    assert h["unrealized_pnl"] == 9_999 - 10_000 - 21  # 기존 필드는 그대로(1원 다른 값)


def test_existing_fields_are_unchanged(client):
    buy_then_quote(client, 3, 12_345)
    h = holding(client)
    ev = int(12_345 * 3)
    assert h["eval_amount"] == ev and h["invested_amount"] == 30_000
    assert h["unrealized_pnl"] == ev - 30_000 - estimate_sell_cost(ev)
    assert h["pnl_pct"] == round((ev - estimate_sell_cost(ev) - 30_000) / 30_000 * 100, 2)
    assert h["current_price"] == 12_345 and h["price_stale"] is False
    for key in ("code", "name", "quantity", "avg_price", "target_price", "stop_loss_price", "hold_days", "signal_status"):
        assert key in h


def test_estimates_are_integers(client):
    buy_then_quote(client, 0.5, 9_999)
    h = holding(client)
    assert isinstance(h["est_proceeds"], int) and isinstance(h["est_realized_pnl"], int)


def test_no_estimate_when_the_quote_failed(client):
    # 시세를 못 받으면 서버는 현재가를 평균단가로 대신한다(price_stale). 그 값으로 만든 수령액을 실시간처럼 내려주지 않는다
    login(client)
    client.post("/api/buy", json={"code": "005930", "quantity": 2})
    client.quotes.pop("005930")
    h = holding(client)
    assert h["price_stale"] is True
    assert h["est_proceeds"] is None and h["est_realized_pnl"] is None
    assert h["current_price"] == h["avg_price"]  # 기존 동작(평균단가로 대체)은 그대로


def test_estimates_follow_the_configured_rates(client, monkeypatch):
    import config
    monkeypatch.setattr(config, "SELL_TAX_RATE", 0.001)
    monkeypatch.setattr(config, "SELL_FEE_RATE", 0.0005)
    buy_then_quote(client, 3, 12_345)
    h = holding(client)
    o = client.post("/api/sell", json={"code": "005930"}).json()["order"]
    assert h["est_proceeds"] == o["net"] and h["est_realized_pnl"] == o["pnl"]
    assert o["tax"] == int(12_345 * 3 * 0.001) and o["fee"] == int(12_345 * 3 * 0.0005)  # 바뀐 세율이 실제로 적용됨


def test_manager_summary_without_quotes_has_no_estimate(tmp_path):
    from portfolio import MultiUserPortfolioManager
    from storage import UserStore

    mgr = MultiUserPortfolioManager(initial_balance=100_000, store=UserStore(str(tmp_path)))
    mgr.buy("dev:x", "A", "가", 10_000, 1, 10_650, 9_700)
    only_a = mgr.get_summary("dev:x", current_prices={"A": 10_500})["holdings"][0]
    assert only_a["est_proceeds"] is not None
    none = mgr.get_summary("dev:x", current_prices={})["holdings"][0]
    assert none["est_proceeds"] is None and none["est_realized_pnl"] is None
    zero = mgr.get_summary("dev:x", current_prices={"A": 0})["holdings"][0]
    assert zero["est_proceeds"] is None  # 0원 시세는 시세가 아니다(주문도 503)
