"""장 상태(market_state) — 종목별 태그·확인창 경고·주문 강제의 근거.

네이버 시세 응답(/basic)의 marketStatus·marketSessionType·overMarketPriceInfo 로 서버가 한 번만 판단한다.
- OPEN+regularMarket → regular, OPEN+afterMarket → after, OPEN+preMarket → pre(이름은 관측 전 가정)
- CLOSE → closed, 그 밖·누락·이상한 값 → unknown(추측하지 않는다)
- nxt_listed 는 시세 응답에 overMarketPriceInfo 가 있는지(ETF 에 NXT 가 없다는 사실이 아니라 응답 관측)
strategy.py 는 바꾸지 않는다: 추천의 상태는 server._compute_bucket 이 종목별 시세로 이어 붙인다.
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


def _basic(status="CLOSE", session="afterMarket", over=True, **extra):
    data = {"stockName": "삼성전자", "closePrice": "230,500", "fluctuationsRatio": "-4.96",
            "highPrice": "240,000", "lowPrice": "228,000", "accumulatedTradingVolume": "1,000"}
    if status is not None:
        data["marketStatus"] = status
    if session is not None:
        data["marketSessionType"] = session
    if over:
        data["overMarketPriceInfo"] = {"overPrice": "230,000", "overMarketStatus": "CLOSE"}
    data.update(extra)
    return data


def _fake_get(monkeypatch, md, basic):
    monkeypatch.setattr(md.requests, "get", lambda url, **kw: _Resp(basic))


# ── 판단 규칙 ──


@pytest.mark.parametrize("status,session,expected", [
    ("OPEN", "regularMarket", "regular"),
    ("OPEN", "afterMarket", "after"),
    ("OPEN", "preMarket", "pre"),            # 가정: 프리마켓 이름은 다음 거래일 아침에 확인한다
    ("CLOSE", "afterMarket", "closed"),      # 2026-10-29 20:38 삼성전자 관측값
    ("CLOSE", "regularMarket", "closed"),    # 같은 시각 ETF 관측값
    ("CLOSE", None, "closed"),
])
def test_market_session_table(md, status, session, expected):
    assert md.market_session(status, session) == expected


@pytest.mark.parametrize("status,session", [
    (None, None), ("OPEN", None), ("OPEN", "weird"), ("open", "regularMarket"),
    (1, "regularMarket"), (["OPEN"], {}), ("", ""), ("OPEN", 3), ("OPEN", ["regularMarket"]),
    ("CLOSE ", "regularMarket"),
])
def test_anything_unrecognised_is_unknown_not_guessed(md, status, session):
    assert md.market_session(status, session) == "unknown"


def test_state_of_reads_the_nxt_listing(md):
    over = {"overPrice": "230,000"}
    assert md.market_state_of({"marketStatus": "CLOSE", "marketSessionType": "afterMarket", "overMarketPriceInfo": over}) \
        == {"state": "closed", "nxt_listed": True}
    assert md.market_state_of({"marketStatus": "CLOSE", "marketSessionType": "regularMarket"}) \
        == {"state": "closed", "nxt_listed": False}
    for not_a_dict in (None, "x", 1, [over]):
        assert md.market_state_of({"marketStatus": "OPEN", "marketSessionType": "regularMarket",
                                   "overMarketPriceInfo": not_a_dict})["nxt_listed"] is False


def test_state_of_empty_or_garbage_is_the_unknown_state(md):
    assert md.market_state_of({}) == md.UNKNOWN_MARKET_STATE == {"state": "unknown", "nxt_listed": False}
    assert md.market_state_of(None) == md.UNKNOWN_MARKET_STATE
    assert md.market_state_of("nope") == md.UNKNOWN_MARKET_STATE


# ── 응답에 붙는 곳 ──


def test_realtime_info_carries_market_state(md, monkeypatch):
    _fake_get(monkeypatch, md, _basic("CLOSE", "afterMarket"))
    info = md.get_realtime_stock_info("005930")
    assert info["market_state"] == {"state": "closed", "nxt_listed": True}
    assert info["current_price"] == 230500  # 다른 필드는 그대로


def test_realtime_info_market_state_is_unknown_without_session_fields(md, monkeypatch):
    _fake_get(monkeypatch, md, _basic(None, None, over=False))
    assert md.get_realtime_stock_info("005930")["market_state"] == md.UNKNOWN_MARKET_STATE


def test_stock_detail_includes_market_state(md, monkeypatch):
    info = {"code": "005930", "name": "삼성전자", "current_price": 230500, "change_rate": -4.96,
            "market_state": {"state": "after", "nxt_listed": True}}
    monkeypatch.setattr(md, "get_realtime_stock_info", lambda code: info)
    monkeypatch.setattr(md, "get_stock_daily_candles", lambda code, count=60: None)
    monkeypatch.setattr(md, "is_stock_fractional_tradable", lambda code: (False, ""))
    assert md.get_stock_detail_with_chart("005930")["market_state"] == {"state": "after", "nxt_listed": True}
    del info["market_state"]  # 시세 dict 에 키가 없으면 모름
    assert md.get_stock_detail_with_chart("005930")["market_state"] == md.UNKNOWN_MARKET_STATE


def _rec(code):
    return {"code": code, "name": "테스트", "market": "KOSPI", "current_price": 10_000,
            "change_rate": 1.0, "trading_value_m": 5000, "score": 70, "rsi": 50.0,
            "signals": [], "chart_data": {}, "sizing": {}}


def _candles():
    return pd.DataFrame({"date": pd.date_range("2026-07-01", periods=60, freq="B"),
                         "close": (10_000 + np.arange(60) * 20).astype(float), "volume": np.full(60, 100_000.0)})


def test_attach_market_state_per_code_keeps_everything_else(md):
    def provider(code):
        if code == "111111":
            return {"market_state": {"state": "regular", "nxt_listed": False}}
        if code == "222222":
            return None
        raise RuntimeError("network")
    recs = [{**_rec("111111"), "grade": "A"}, _rec("222222"), _rec("333333")]
    out = md.attach_market_state(recs, provider)
    assert [r["code"] for r in out] == ["111111", "222222", "333333"]
    assert out[0]["market_state"] == {"state": "regular", "nxt_listed": False}
    assert out[1]["market_state"] == md.UNKNOWN_MARKET_STATE and out[2]["market_state"] == md.UNKNOWN_MARKET_STATE
    assert out[0]["grade"] == "A" and out[0]["change_rate"] == 1.0
    assert "market_state" not in recs[0]  # 원본은 건드리지 않는다


def test_compute_bucket_attaches_market_state(monkeypatch):
    import server
    monkeypatch.setattr(server, "get_market_candidate_stocks", lambda **kw: [{"code": "222222"}, {"code": "111111"}])
    monkeypatch.setattr(server, "get_recommendations", lambda c, p, budget, top_n: [_rec("222222"), _rec("111111")])
    monkeypatch.setattr(server, "get_stock_daily_candles", lambda code, count=60: _candles())
    states = {"222222": {"state": "after", "nxt_listed": True}}
    monkeypatch.setattr(server, "get_realtime_stock_info", lambda code: {"market_state": states[code]} if code in states else None)
    out = server._compute_bucket(100_000)
    assert {r["code"]: r["market_state"]["state"] for r in out} == {"222222": "after", "111111": "unknown"}


def test_portfolio_holdings_carry_market_state(client):
    login(client)
    assert client.post("/api/buy", json={"code": "005930", "quantity": 1}).status_code == 200
    client.quotes["005930"]["market_state"] = {"state": "after", "nxt_listed": True}
    h = client.get("/api/portfolio").json()["portfolio"]["holdings"][0]
    assert h["market_state"] == {"state": "after", "nxt_listed": True}
    del client.quotes["005930"]  # 시세 실패 → 모름
    h = client.get("/api/portfolio").json()["portfolio"]["holdings"][0]
    assert h["price_stale"] is True and h["market_state"]["state"] == "unknown"


def test_recs_for_budget_keeps_the_market_state():
    from recommendation_cache import recs_for_budget
    rec = {**_rec("111111"), "market_state": {"state": "after", "nxt_listed": True}}
    out = recs_for_budget([rec], 100_000)
    assert out and out[0]["market_state"] == {"state": "after", "nxt_listed": True}
