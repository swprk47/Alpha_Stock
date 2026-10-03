"""종목코드 검증: 영숫자 6자리(예: 0183J0) 허용, 그 외 거부."""
import re

import pytest

from conftest import login
from schemas import CODE_PATTERN


@pytest.mark.parametrize("code", ["005930", "0183J0", "ABCDEF"])
def test_pattern_accepts(code):
    assert re.fullmatch(CODE_PATTERN, code)


@pytest.mark.parametrize("code", ["12345", "1234567", "0183j0", "01-3J0", "0183J ", ""])
def test_pattern_rejects(code):
    assert not re.fullmatch(CODE_PATTERN, code)


def test_stock_detail_accepts_alnum_code(client, monkeypatch):
    import server
    monkeypatch.setattr(server, "get_stock_detail_with_chart",
                        lambda code, budget=100000: {"code": code, "name": "TIGER 미국우주테크"})
    r = client.get("/api/stock/0183J0")
    assert r.status_code == 200 and r.json()["stock"]["code"] == "0183J0"


@pytest.mark.parametrize("code", ["12345", "0183j0", "0183J01"])
def test_stock_detail_rejects_bad_code(client, code):
    assert client.get(f"/api/stock/{code}").status_code == 400


def test_buy_sell_alnum_etf_integer_only(client):
    login(client)
    client.quotes["0183J0"] = {"code": "0183J0", "name": "TIGER 미국우주테크", "current_price": 7_600}
    # ETF 는 소수점 불가(frac 기본 False): 소수 수량 400, 정수 수량 200
    assert client.post("/api/buy", json={"code": "0183J0", "quantity": 0.5}).status_code == 400
    assert client.post("/api/buy", json={"code": "0183J0", "quantity": 2}).status_code == 200
    assert client.post("/api/sell", json={"code": "0183J0"}).status_code == 200


def test_order_rejects_lowercase_code_422(client):
    login(client)
    assert client.post("/api/buy", json={"code": "0183j0", "quantity": 1}).status_code == 422
