"""서버가 네이버 시세 응답의 로고 주소(itemLogoPngUrl)를 logo_url 로 내려준다.

일반 주식은 .../stock/Stock{코드}.png, ETF 는 운용사 로고(.../etf/StockKRETFKODEX.png), ETN 은 증권사 로고다.
종목코드로 만든 주소는 ETF 에서 404 라서, 응답이 준 주소를 쓰는 쪽이 맞다.
허용 주소(https://ssl.pstatic.net/imgstock/)가 아니면 빈 문자열로 버린다(화면이 img src 로 쓰므로).
"""
import pytest

from conftest import login

ETF_LOGO = "https://ssl.pstatic.net/imgstock/fn/real/logo/png/etf/StockKRETFKODEX.png"
STOCK_LOGO = "https://ssl.pstatic.net/imgstock/fn/real/logo/png/stock/Stock035720.png"


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload


def _basic(logo=ETF_LOGO, **extra):
    data = {"stockName": "KODEX 200", "closePrice": "95,650", "fluctuationsRatio": "7.59",
            "highPrice": "96,000", "lowPrice": "94,000", "accumulatedTradingVolume": "1,000"}
    if logo is not None:
        data["itemLogoPngUrl"] = logo
    data.update(extra)
    return data


@pytest.fixture
def md(monkeypatch):
    import market_data
    return market_data


def _fake_get(monkeypatch, md, basic=None, items=None):
    def get(url, **kw):
        if "ac.stock.naver.com" in url:
            return _Resp({"items": items or []})
        return _Resp(basic if basic is not None else _basic())
    monkeypatch.setattr(md.requests, "get", get)


def test_realtime_info_carries_the_logo_for_an_etf(md, monkeypatch):
    _fake_get(monkeypatch, md, _basic(ETF_LOGO))
    assert md.get_realtime_stock_info("069500")["logo_url"] == ETF_LOGO


def test_realtime_info_carries_the_logo_for_a_stock(md, monkeypatch):
    _fake_get(monkeypatch, md, _basic(STOCK_LOGO))
    assert md.get_realtime_stock_info("035720")["logo_url"] == STOCK_LOGO


@pytest.mark.parametrize("bad", [
    "https://evil.example.com/logo.png",          # 다른 호스트
    "http://ssl.pstatic.net/imgstock/x.png",       # http
    "javascript:alert(1)",
    "https://ssl.pstatic.net.evil.com/imgstock/x.png",
    'https://ssl.pstatic.net/imgstock/x.png" onerror="alert(1)',   # 속성 탈출 시도
    "https://ssl.pstatic.net/imgstock/x y.png",
    "",
    None,
    123,
])
def test_logo_outside_the_allowed_address_is_dropped(md, monkeypatch, bad):
    _fake_get(monkeypatch, md, _basic(bad if bad is not None else None))
    info = md.get_realtime_stock_info("035720")
    assert info["logo_url"] == ""
    assert info["current_price"] == 95650  # 다른 필드는 그대로


def test_existing_realtime_fields_are_unchanged(md, monkeypatch):
    _fake_get(monkeypatch, md, _basic())
    info = md.get_realtime_stock_info("069500")
    for key in ("code", "name", "current_price", "change_rate", "high_price", "low_price", "volume"):
        assert key in info, key


def test_search_uses_the_logo_from_the_quote(md, monkeypatch):
    _fake_get(monkeypatch, md, _basic(ETF_LOGO), items=[{"code": "069500", "name": "KODEX 200", "typeCode": "KOSPI"}])
    assert md.search_stocks("KODEX")[0]["logo_url"] == ETF_LOGO


def test_search_falls_back_to_the_code_address_when_the_quote_has_no_logo(md, monkeypatch):
    _fake_get(monkeypatch, md, _basic(None), items=[{"code": "035720", "name": "카카오", "typeCode": "KOSPI"}])
    assert md.search_stocks("카카오")[0]["logo_url"] == STOCK_LOGO


def test_search_falls_back_when_the_quote_fails(md, monkeypatch):
    monkeypatch.setattr(md, "get_realtime_stock_info", lambda code: None)
    monkeypatch.setattr(md.requests, "get", lambda url, **kw: _Resp({"items": [{"code": "035720", "name": "카카오", "typeCode": "KOSPI"}]}))
    assert md.search_stocks("카카오")[0]["logo_url"] == STOCK_LOGO


def test_stock_detail_includes_the_logo(md, monkeypatch):
    monkeypatch.setattr(md, "get_realtime_stock_info", lambda code: {
        "code": code, "name": "KODEX 200", "current_price": 95650, "change_rate": 7.59, "logo_url": ETF_LOGO})
    monkeypatch.setattr(md, "get_stock_daily_candles", lambda code, count=60: None)
    monkeypatch.setattr(md, "is_stock_fractional_tradable", lambda code: (False, ""))
    assert md.get_stock_detail_with_chart("069500")["logo_url"] == ETF_LOGO


def _holding(client):
    r = client.get("/api/portfolio")
    assert r.status_code == 200
    return r.json()["portfolio"]["holdings"][0]


def test_holding_gets_the_logo_from_the_realtime_quote(client):
    login(client)
    assert client.post("/api/buy", json={"code": "005930", "quantity": 1}).status_code == 200
    client.quotes["005930"]["logo_url"] = ETF_LOGO
    assert _holding(client)["logo_url"] == ETF_LOGO


def test_holding_logo_is_empty_when_the_quote_has_none(client):
    login(client)
    assert client.post("/api/buy", json={"code": "005930", "quantity": 1}).status_code == 200
    assert _holding(client)["logo_url"] == ""  # 화면은 코드로 만든 주소 → 첫 글자 순서로 대신한다


def test_holding_keeps_its_logo_field_when_the_quote_fails(client):
    login(client)
    assert client.post("/api/buy", json={"code": "005930", "quantity": 1}).status_code == 200
    client.quotes["005930"]["logo_url"] = ETF_LOGO
    assert _holding(client)["logo_url"] == ETF_LOGO
    del client.quotes["005930"]  # 시세 실패
    h = _holding(client)
    assert h["price_stale"] is True
    assert h["logo_url"] == ""
