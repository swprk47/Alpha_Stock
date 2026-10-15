import json

import pytest

import fractional
import market_data


@pytest.fixture(autouse=True)
def _fresh():
    fractional._reset_cache()
    yield
    fractional._reset_cache()


def test_samsung_listed():
    ok, desc = fractional.is_fractional_tradable("005930")
    assert ok and desc == "소수점 거래 가능 종목"


def test_a_prefix_normalized():
    assert fractional.is_fractional_tradable("A005930")[0]


def test_unlisted_and_etf_not_allowed():
    assert not fractional.is_fractional_tradable("0183J0")[0]   # ETF
    assert not fractional.is_fractional_tradable("069500")[0]   # KODEX 200
    assert not fractional.is_fractional_tradable("999999")[0]


def test_list_integrity():
    d = fractional._load("miraeasset")
    assert d["count"] == len(d["stocks"]) == 328
    assert d["updated_at"] == "2026-10-01"
    assert all(len(c) == 6 for c in d["stocks"])


def test_missing_list_is_safe():
    assert fractional.is_fractional_tradable("005930", broker="nobroker")[0] is False
    assert fractional.is_fractional_tradable("005930", broker="../x")[0] is False


def test_market_data_uses_list_without_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network call")
    monkeypatch.setattr(market_data.requests, "get", boom)
    assert market_data.is_stock_fractional_tradable("005930")[0] is True
    assert market_data.is_stock_fractional_tradable("0183J0")[0] is False


def test_import_script_rejects_etf(tmp_path):
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import pandas as pd
    import import_fractional as imp
    x = tmp_path / "a.xlsx"
    pd.DataFrame([["A005930", "삼성전자"], ["A069500", "KODEX 200"]]).to_excel(x, header=False, index=False)
    with pytest.raises(SystemExit):
        imp.convert(str(x), "t", "2026-10-01")
    y = tmp_path / "b.xlsx"
    pd.DataFrame([["A005930", "삼성전자"]]).to_excel(y, header=False, index=False)
    assert imp.convert(str(y), "t", "2026-10-01")["stocks"] == {"005930": "삼성전자"}
