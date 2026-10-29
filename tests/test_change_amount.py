"""전일 대비 금액(change_amount) — 화면이 "+4.2% (+5,000원)" 로 보이는 데 쓴다.

출처는 네이버 시세 응답(/basic)과 추천 후보 목록(marketValue)의 compareToPreviousClosePrice(부호가 붙은 문자열, 예 "-13,000")이다.
- 값이 없거나 이상하면 None(0 으로 꾸미지 않는다: 화면은 %만 보인다)
- 등락률과 부호가 어긋나면 부호를 추측해 뒤집지 않고 None
strategy.py 는 바꾸지 않는다: 추천의 금액은 server._compute_bucket 이 후보에서 코드별로 이어 붙인다.
"""
import numpy as np
import pandas as pd
import pytest


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload


@pytest.fixture
def md():
    import market_data
    return market_data


def _basic(amount="-13,000", rate="-5.37", **extra):
    data = {"stockName": "삼성전자", "closePrice": "229,000", "fluctuationsRatio": rate,
            "highPrice": "240,000", "lowPrice": "228,000", "accumulatedTradingVolume": "1,000"}
    if amount is not None:
        data["compareToPreviousClosePrice"] = amount
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


# ── 파싱 ──


@pytest.mark.parametrize("raw,rate,expected", [
    ("-13,000", -5.37, -13000),      # 쉼표·음수 부호
    ("5,000", 4.0, 5000),            # 부호 없는 양수
    ("+5,000", 4.0, 5000),           # 양수 부호
    ("0", 0.0, 0),                   # 보합
    ("-20", -0.08, -20),
    (-13000, -5.37, -13000),         # 이미 숫자로 온 경우
    (5000, 4.0, 5000),
    (" 5,000 ", 4.0, 5000),          # 공백
])
def test_parses_the_signed_amount(md, raw, rate, expected):
    assert md.parse_change_amount(raw, rate) == expected


@pytest.mark.parametrize("raw", [None, "", "  ", "abc", "1.5", "5,0,0x", "--5", ["5000"], {"a": 1}, True, float("nan")])
def test_missing_or_malformed_amount_is_none_not_zero(md, raw):
    assert md.parse_change_amount(raw, 4.0) is None


@pytest.mark.parametrize("raw,rate", [
    ("5,000", -4.0),     # 내렸다는데 금액은 양수
    ("-5,000", 4.0),     # 올랐다는데 금액은 음수
    ("5,000", 0.0),      # 보합인데 금액이 있다
    ("0", 1.2),          # 올랐다는데 금액이 0
])
def test_amount_that_contradicts_the_rate_sign_is_dropped_never_flipped(md, raw, rate):
    assert md.parse_change_amount(raw, rate) is None


# ── 응답에 들어가는지 ──


def test_realtime_info_carries_the_amount(md, monkeypatch):
    _fake_get(monkeypatch, md, _basic("-13,000", "-5.37"))
    info = md.get_realtime_stock_info("005930")
    assert info["change_amount"] == -13000
    assert info["change_rate"] == -5.37 and info["current_price"] == 229000  # 다른 필드는 그대로


def test_realtime_info_amount_is_none_when_the_quote_has_none(md, monkeypatch):
    _fake_get(monkeypatch, md, _basic(None))
    info = md.get_realtime_stock_info("005930")
    assert info["change_amount"] is None
    assert info["change_rate"] == -5.37


def test_realtime_info_amount_is_none_when_it_contradicts_the_rate(md, monkeypatch):
    _fake_get(monkeypatch, md, _basic("13,000", "-5.37"))
    assert md.get_realtime_stock_info("005930")["change_amount"] is None


def test_search_results_carry_the_amount(md, monkeypatch):
    _fake_get(monkeypatch, md, _basic("-13,000", "-5.37"),
              items=[{"code": "005930", "name": "삼성전자", "typeCode": "KOSPI"}])
    assert md.search_stocks("삼성")[0]["change_amount"] == -13000


def test_search_amount_is_none_when_the_quote_fails(md, monkeypatch):
    monkeypatch.setattr(md, "get_realtime_stock_info", lambda code: None)
    monkeypatch.setattr(md.requests, "get", lambda url, **kw: _Resp({"items": [{"code": "005930", "name": "삼성전자", "typeCode": "KOSPI"}]}))
    assert md.search_stocks("삼성")[0]["change_amount"] is None


def test_stock_detail_includes_the_amount(md, monkeypatch):
    monkeypatch.setattr(md, "get_realtime_stock_info", lambda code: {
        "code": code, "name": "삼성전자", "current_price": 229000, "change_rate": -5.37, "change_amount": -13000})
    monkeypatch.setattr(md, "get_stock_daily_candles", lambda code, count=60: None)
    monkeypatch.setattr(md, "is_stock_fractional_tradable", lambda code: (False, ""))
    assert md.get_stock_detail_with_chart("005930")["change_amount"] == -13000


def test_stock_detail_amount_is_none_when_the_info_lacks_it(md, monkeypatch):
    monkeypatch.setattr(md, "get_realtime_stock_info", lambda code: {
        "code": code, "name": "삼성전자", "current_price": 229000, "change_rate": -5.37})
    monkeypatch.setattr(md, "get_stock_daily_candles", lambda code, count=60: None)
    monkeypatch.setattr(md, "is_stock_fractional_tradable", lambda code: (False, ""))
    assert md.get_stock_detail_with_chart("005930")["change_amount"] is None


def test_candidates_carry_the_amount(md, monkeypatch):
    def item(code, amount, rate):
        d = {"itemCode": code, "stockName": code, "tradableStatus": "tradable", "closePriceRaw": 20000,
             "accumulatedTradingValueRaw": 9_000_000_000, "fluctuationsRatio": rate}
        if amount is not None:
            d["compareToPreviousClosePrice"] = amount
        return d
    _fake_get(monkeypatch, md, stocks=[item("111111", "-1,000", "-4.8"), item("222222", "300", "1.5"),
                                       item("333333", None, "2.0"), item("444444", "500", "-2.0")])
    got = {c["code"]: c["change_amount"] for c in md.get_market_candidate_stocks()}
    assert got == {"111111": -1000, "222222": 300, "333333": None, "444444": None}  # 부호 불일치는 None


# ── 추천: strategy.py 를 바꾸지 않고 서버가 이어 붙인다 ──


def _rec(code):
    return {"code": code, "name": "테스트", "market": "KOSPI", "current_price": 10_000,
            "change_rate": 1.0, "trading_value_m": 5000, "score": 70, "rsi": 50.0,
            "signals": [], "chart_data": {}, "sizing": {}}


def _candles():
    return pd.DataFrame({"date": pd.date_range("2026-07-01", periods=60, freq="B"),
                         "close": (10_000 + np.arange(60) * 20).astype(float), "volume": np.full(60, 100_000.0)})


def test_attach_diagnosis_adds_the_amount_by_code(md):
    recs = md.attach_diagnosis([_rec("222222"), _rec("111111"), _rec("999999")], lambda code, count=60: _candles(),
                               budget=100_000, change_amounts={"222222": 300, "111111": -1000})
    assert [r["change_amount"] for r in recs] == [300, -1000, None]  # 후보에 없던 코드는 None


def test_attach_diagnosis_without_amounts_keeps_working(md):
    recs = md.attach_diagnosis([_rec("005930")], lambda code, count=60: _candles(), budget=100_000)
    assert recs[0]["change_amount"] is None
    assert recs[0]["grade"] in ("S", "A", "B", "C", "N/A")  # 기존 필드는 그대로
    assert recs[0]["change_rate"] == 1.0


def test_compute_bucket_passes_candidate_amounts_to_the_recommendations(monkeypatch):
    import server
    cands = [{"code": "222222", "change_amount": 300}, {"code": "111111", "change_amount": None}]
    monkeypatch.setattr(server, "get_market_candidate_stocks", lambda **kw: cands)
    monkeypatch.setattr(server, "get_recommendations", lambda c, p, budget, top_n: [_rec("222222"), _rec("111111")])
    monkeypatch.setattr(server, "get_stock_daily_candles", lambda code, count=60: _candles())
    out = server._compute_bucket(100_000)
    assert {r["code"]: r["change_amount"] for r in out} == {"222222": 300, "111111": None}
