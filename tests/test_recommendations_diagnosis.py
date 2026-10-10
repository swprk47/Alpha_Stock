"""추천 응답에 AI 진단(등급)·소수점 판별이 포함되는지 검증. 네트워크 호출 없음."""
import numpy as np
import pandas as pd
import pytest

import market_data
import strategy


def make_candles(days=60, start=10_000, step=20):
    close = start + np.arange(days) * step
    return pd.DataFrame({
        "date": pd.date_range("2026-07-01", periods=days, freq="B"),
        "close": close.astype(float),
        "volume": np.full(days, 100_000.0),
    })


def make_rec(code="005930", price=10_000):
    return {"code": code, "name": "테스트", "market": "KOSPI", "current_price": price,
            "change_rate": 1.0, "trading_value_m": 5000, "score": 70, "rsi": 50.0,
            "signals": [], "chart_data": {}, "sizing": {}}


def test_attach_adds_grade_and_fractional_fields():
    candles = make_candles()
    recs = market_data.attach_diagnosis([make_rec("005930")], lambda code, count=60: candles,
                                        budget=100_000)
    r = recs[0]
    expected = strategy.get_stock_grade({"current_price": 10_000}, candles,
                                        budget=100_000, is_fractional=True)
    assert r["grade"] == expected["grade"]
    assert r["grade_score"] == expected["score"]
    assert r["grade_reasons"] == expected["grade_reasons"]
    assert r["is_fractional"] is True  # 005930 은 소수점 목록에 있음
    assert isinstance(r["fractional_desc"], str)


def test_attach_marks_non_listed_code_integer_only():
    recs = market_data.attach_diagnosis([make_rec("0183J0")], lambda code, count=60: make_candles(),
                                        budget=100_000)
    assert recs[0]["is_fractional"] is False


def test_attach_without_candles_is_na_but_keeps_fractional():
    recs = market_data.attach_diagnosis([make_rec("005930")], lambda code, count=60: None,
                                        budget=100_000)
    r = recs[0]
    assert r["grade"] == "N/A" and r["grade_score"] == 0
    assert r["grade_reasons"] == ["데이터 부족"]
    assert r["is_fractional"] is True


def test_attach_candle_provider_error_does_not_break_list():
    def boom(code, count=60):
        raise RuntimeError("network down")
    recs = market_data.attach_diagnosis([make_rec("005930"), make_rec("0183J0")], boom,
                                        budget=100_000)
    assert [r["grade"] for r in recs] == ["N/A", "N/A"]
    assert [r["is_fractional"] for r in recs] == [True, False]


def test_attach_over_budget_non_fractional_is_grade_c():
    rec = make_rec("0183J0", price=150_000)
    recs = market_data.attach_diagnosis([rec], lambda code, count=60: make_candles(),
                                        budget=100_000)
    assert recs[0]["grade"] == "C"


def test_attach_keeps_original_fields():
    rec = make_rec()
    out = market_data.attach_diagnosis([rec], lambda code, count=60: make_candles(), budget=100_000)
    assert out[0]["score"] == 70 and out[0]["code"] == "005930"


def test_recommendations_api_includes_diagnosis(client, monkeypatch):
    """/api/recommendations 응답의 각 항목에 grade·is_fractional 등이 들어 있다."""
    import server
    candles = make_candles()
    monkeypatch.setitem(server.cache, "recommendations", [])
    monkeypatch.setitem(server.cache, "last_updated", 0)
    monkeypatch.setattr(server, "get_market_candidate_stocks", lambda **kw: [make_rec()])
    monkeypatch.setattr(server, "get_recommendations",
                        lambda cands, provider, budget=100_000, top_n=3: [make_rec("005930"), make_rec("0183J0")])
    monkeypatch.setattr(server, "get_stock_daily_candles", lambda code, count=60: candles)

    r = client.get("/api/recommendations")
    assert r.status_code == 200
    items = r.json()["recommendations"]
    assert len(items) == 2
    for it in items:
        for key in ("grade", "grade_score", "grade_reasons", "is_fractional", "fractional_desc"):
            assert key in it, key
    assert items[0]["is_fractional"] is True
    assert items[1]["is_fractional"] is False
