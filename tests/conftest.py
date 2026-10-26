import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))
os.environ.setdefault("SESSION_SECRET", "test-secret-" + "x" * 40)
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("ALLOW_DEV_LOGIN", "true")

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    """임시 DATA_DIR + 시세 mock 으로 격리된 TestClient."""
    import config
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    import server
    import orders
    from portfolio import MultiUserPortfolioManager
    from storage import UserStore
    from fastapi.testclient import TestClient

    monkeypatch.setattr(server, "portfolio_mgr",
                        MultiUserPortfolioManager(initial_balance=100_000, store=UserStore(str(tmp_path))))
    quotes = {"005930": {"code": "005930", "name": "삼성전자", "current_price": 10_000}}
    frac = {"005930": True}

    def fake_quote(code):
        return quotes.get(code)

    monkeypatch.setattr(orders.market_data, "get_realtime_stock_info", fake_quote)
    monkeypatch.setattr(orders.market_data, "is_stock_fractional_tradable",
                        lambda c: (frac.get(c, False), ""))
    monkeypatch.setattr(server, "get_realtime_stock_info", fake_quote)
    monkeypatch.setattr(server, "get_stock_daily_candles", lambda c, count=30: None)

    c = TestClient(server.app)
    c.quotes, c.frac = quotes, frac
    return c


def login(c, nickname="alice"):
    r = c.post("/api/auth/dev-login", json={"nickname": nickname})
    assert r.status_code == 200
    return c
