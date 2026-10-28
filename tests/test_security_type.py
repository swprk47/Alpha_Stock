"""종목 종류(security_type: stock/etf/etn) — 화면의 ETF 태그가 쓴다.

출처는 네이버 시세 응답(/basic)과 추천 후보 목록(marketValue)의 stockEndType 이다.
알 수 없거나 다른 값이면 빈 문자열(화면은 태그를 달지 않는다: 모르는 종목에 ETF 라고 틀리게 달지 않기 위해서).
검색 자동완성 응답은 ETF 도 stock 으로 분류해서 쓰지 않는다.
strategy.py 는 바꾸지 않는다: 추천의 종류는 server._compute_bucket 이 후보에서 코드별로 이어 붙인다.
"""
import numpy as np
import pandas as pd
import pytest

from conftest import login


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload


@pytest.fixture
def md():
    import market_data
    return market_data


def _basic(kind="etf", **extra):
    data = {"stockName": "KODEX 200", "closePrice": "95,650", "fluctuationsRatio": "7.59",
            "highPrice": "96,000", "lowPrice": "94,000", "accumulatedTradingVolume": "1,000"}
    if kind is not None:
        data["stockEndType"] = kind
    data.update(extra)
    return data


def _fake_get(monkeypatch, md, basic=None, items=None, stocks=None):
    def get(url, **kw):
        if "ac.stock.naver.com" in url:
            return _Resp({"items": items or []})
        if "marketValue" in url:
            return _Resp({"stocks": stocks or []})
        return _Resp(basic if basic is not None else _basic())
    monkeypatch.setattr(md.requests, "get", get)


@pytest.mark.parametrize("kind", ["stock", "etf", "etn"])
def test_security_type_normalizer_keeps_known_kinds(md, kind):
    assert md.safe_security_type(kind) == kind


@pytest.mark.parametrize("bad", ["ETF", "fund", "", None, 1, ["etf"], "etf; drop"])
def test_security_type_normalizer_drops_everything_else(md, bad):
    assert md.safe_security_type(bad) == ""


@pytest.mark.parametrize("kind", ["stock", "etf", "etn"])
def test_realtime_info_carries_the_kind(md, monkeypatch, kind):
    _fake_get(monkeypatch, md, _basic(kind))
    assert md.get_realtime_stock_info("069500")["security_type"] == kind


def test_realtime_info_kind_is_empty_when_the_quote_has_none(md, monkeypatch):
    _fake_get(monkeypatch, md, _basic(None))
    info = md.get_realtime_stock_info("069500")
    assert info["security_type"] == ""
    assert info["current_price"] == 95650  # 다른 필드는 그대로


def test_search_uses_the_quote_kind_not_the_autocomplete_category(md, monkeypatch):
    # 자동완성은 ETF 도 category 'stock' 으로 준다
    _fake_get(monkeypatch, md, _basic("etf"), items=[{"code": "069500", "name": "KODEX 200", "typeCode": "KOSPI", "category": "stock"}])
    assert md.search_stocks("KODEX")[0]["security_type"] == "etf"


def test_search_kind_is_empty_when_the_quote_fails(md, monkeypatch):
    monkeypatch.setattr(md, "get_realtime_stock_info", lambda code: None)
    monkeypatch.setattr(md.requests, "get", lambda url, **kw: _Resp({"items": [{"code": "069500", "name": "KODEX 200", "typeCode": "KOSPI"}]}))
    assert md.search_stocks("KODEX")[0]["security_type"] == ""


def test_stock_detail_includes_the_kind(md, monkeypatch):
    monkeypatch.setattr(md, "get_realtime_stock_info", lambda code: {
        "code": code, "name": "KODEX 200", "current_price": 95650, "change_rate": 7.59, "security_type": "etf"})
    monkeypatch.setattr(md, "get_stock_daily_candles", lambda code, count=60: None)
    monkeypatch.setattr(md, "is_stock_fractional_tradable", lambda code: (False, ""))
    assert md.get_stock_detail_with_chart("069500")["security_type"] == "etf"


def test_candidates_carry_the_kind(md, monkeypatch):
    def item(code, kind):
        return {"itemCode": code, "stockName": code, "tradableStatus": "tradable", "closePriceRaw": 20000,
                "accumulatedTradingValueRaw": 9_000_000_000, "fluctuationsRatio": "1.0", "stockEndType": kind}
    _fake_get(monkeypatch, md, stocks=[item("111111", "stock"), item("222222", "etf"), item("333333", "etn"), item("444444", "weird")])
    kinds = {c["code"]: c["security_type"] for c in md.get_market_candidate_stocks()}
    assert kinds == {"111111": "stock", "222222": "etf", "333333": "etn", "444444": ""}


def _rec(code):
    return {"code": code, "name": "테스트", "market": "KOSPI", "current_price": 10_000,
            "change_rate": 1.0, "trading_value_m": 5000, "score": 70, "rsi": 50.0,
            "signals": [], "chart_data": {}, "sizing": {}}


def _candles():
    return pd.DataFrame({"date": pd.date_range("2026-07-01", periods=60, freq="B"),
                         "close": (10_000 + np.arange(60) * 20).astype(float), "volume": np.full(60, 100_000.0)})


def test_attach_diagnosis_adds_the_kind_by_code(md):
    recs = md.attach_diagnosis([_rec("222222"), _rec("111111"), _rec("999999")], lambda code, count=60: _candles(),
                               budget=100_000, security_types={"222222": "etf", "111111": "stock"})
    assert [r["security_type"] for r in recs] == ["etf", "stock", ""]  # 후보에 없던 코드는 모름("")


def test_attach_diagnosis_without_kinds_keeps_working(md):
    recs = md.attach_diagnosis([_rec("005930")], lambda code, count=60: _candles(), budget=100_000)
    assert recs[0]["security_type"] == ""
    assert recs[0]["grade"] in ("S", "A", "B", "C", "N/A")  # 기존 필드는 그대로


def test_compute_bucket_passes_candidate_kinds_to_the_recommendations(monkeypatch):
    import server
    cands = [{"code": "222222", "security_type": "etf"}, {"code": "111111", "security_type": "stock"}]
    monkeypatch.setattr(server, "get_market_candidate_stocks", lambda **kw: cands)
    monkeypatch.setattr(server, "get_recommendations", lambda c, p, budget, top_n: [_rec("222222"), _rec("111111")])
    monkeypatch.setattr(server, "get_stock_daily_candles", lambda code, count=60: _candles())
    out = server._compute_bucket(100_000)
    assert {r["code"]: r["security_type"] for r in out} == {"222222": "etf", "111111": "stock"}


def _holding(client):
    r = client.get("/api/portfolio")
    assert r.status_code == 200
    return r.json()["portfolio"]["holdings"][0]


def test_holding_gets_the_kind_from_the_realtime_quote(client):
    login(client)
    assert client.post("/api/buy", json={"code": "005930", "quantity": 1}).status_code == 200
    client.quotes["005930"]["security_type"] = "etf"
    assert _holding(client)["security_type"] == "etf"


def test_holding_kind_is_empty_when_the_quote_fails(client):
    login(client)
    assert client.post("/api/buy", json={"code": "005930", "quantity": 1}).status_code == 200
    client.quotes["005930"]["security_type"] = "etf"
    del client.quotes["005930"]  # 시세 실패 → 종류를 모른다
    h = _holding(client)
    assert h["price_stale"] is True
    assert h["security_type"] == ""
