"""서버가 어느 시간대에서 돌아도 화면·기록에 보이는 시각은 한국 표준시(KST, UTC+9)다.

서버 PC 의 현지 시각(datetime.now / fromtimestamp 기본값)에 기대면 UTC 서버에서 9시간 어긋난다.
"""
from datetime import datetime

import pytest

import clock
import overview
import portfolio
import server
from test_overview_cards import net  # noqa: F401  (fixture)


def test_fmt_kst_is_utc_plus_nine_whatever_the_server_zone():
    assert clock.fmt_kst(0) == "1970-01-01 09:00:00"
    assert clock.fmt_kst(1_700_000_000) == "2023-11-15 07:13:20"  # UTC 22:13:20


def test_now_and_today_are_kst(monkeypatch):
    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            # UTC 2026-11-01 15:30 == KST 2026-11-02 00:30
            return datetime(2026, 11, 1, 15, 30, tzinfo=clock.UTC).astimezone(tz)

    monkeypatch.setattr(clock, "datetime", Fixed)
    assert clock.now_kst().strftime("%Y-%m-%d %H:%M:%S") == "2026-11-02 00:30:00"
    assert str(clock.today_kst()) == "2026-11-02"


@pytest.fixture
def after_midnight_kst(monkeypatch):
    """UTC 로는 아직 11/01 이지만 한국은 11/02 00:30."""
    fixed = datetime(2026, 11, 2, 0, 30, 0, tzinfo=clock.KST)
    monkeypatch.setattr(clock, "now_kst", lambda: fixed)
    monkeypatch.setattr(clock, "today_kst", lambda: fixed.date())


def test_trade_timestamp_uses_kst(after_midnight_kst):
    assert portfolio._now() == "2026-11-02 00:30:00"


def test_buy_date_and_hold_days_use_kst_today(after_midnight_kst, tmp_path):
    from storage import UserStore
    mgr = portfolio.MultiUserPortfolioManager(initial_balance=1_000_000, store=UserStore(str(tmp_path)))
    mgr.buy("u", "005930", "삼성전자", 10_000, 1, 11_000, 9_000)
    item = mgr.get_summary("u", {"005930": 10_000})["holdings"][0]
    assert item["buy_date"] == "2026-11-02"  # UTC 로는 11/01 이지만 한국은 11/02
    assert item["hold_days"] == 0


def test_overview_fetched_at_uses_kst(net):
    from test_overview_cards import FakeClock, run, stock_routes
    stock_routes(net)
    assert run("005930", net, FakeClock(0.0))["fetched_at"] == "1970-01-01 09:00:00"


def test_recommendations_updated_at_uses_kst(client, monkeypatch):
    import recommendation_cache as rc
    monkeypatch.setattr(server, "get_market_candidate_stocks", lambda **kw: [{"code": "x"}])
    monkeypatch.setattr(server, "get_recommendations", lambda *a, **kw: [{"code": "A", "current_price": 30_500, "score": 90}])
    monkeypatch.setattr(server, "get_stock_daily_candles", lambda code, count=60: None)
    monkeypatch.setattr(server, "rec_cache", rc.RecommendationCache(server._compute_bucket, clock=lambda: 1_700_000_000.0))
    assert client.get("/api/recommendations").json()["updated_at"] == "2023-11-15 07:13:20"
