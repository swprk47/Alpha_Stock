"""GET /api/stock/{code}/overview — 로그인 필요, 코드 형식 검사, 개요 응답 전달."""
import pytest

from conftest import login

PAYLOAD = {
    "success": True, "code": "005930", "kind": "stock", "fetched_at": "2026-10-30 21:40:12", "source_url": "",
    "about": {"status": "ok", "title": "회사 소개", "paragraphs": ["a"]},
    "facts": {"status": "empty", "items": []}, "holdings": {"status": "empty", "items": []},
    "weights": {"status": "empty", "cards": []}, "news": {"status": "empty", "items": []},
}


@pytest.fixture
def fake_overview(monkeypatch):
    import server
    calls = []

    def fake(code):
        calls.append(code)
        return dict(PAYLOAD, code=code)

    monkeypatch.setattr(server, "get_overview", fake)
    return calls


def test_requires_login_401(client, fake_overview):
    assert client.get("/api/stock/005930/overview").status_code == 401
    assert fake_overview == []  # 로그인 없이는 네이버 호출이 없다


@pytest.mark.parametrize("code", ["abc", "00593", "005930X", "0183j0", "삼성전자"])
def test_bad_code_400(client, fake_overview, code):
    login(client)
    assert client.get(f"/api/stock/{code}/overview").status_code == 400
    assert fake_overview == []


def test_new_format_code_is_accepted(client, fake_overview):
    login(client)
    r = client.get("/api/stock/0183J0/overview")
    assert r.status_code == 200 and r.json()["code"] == "0183J0"
    assert fake_overview == ["0183J0"]


def test_returns_overview_payload(client, fake_overview):
    login(client)
    r = client.get("/api/stock/005930/overview")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True and body["kind"] == "stock"
    assert {"about", "facts", "holdings", "weights", "news"} <= set(body)
    assert body["about"]["paragraphs"] == ["a"]


def test_existing_stock_detail_stays_public(client, monkeypatch):
    import server
    monkeypatch.setattr(server, "get_stock_detail_with_chart", lambda code, budget=100000: {"code": code, "name": "삼성전자"})
    r = client.get("/api/stock/005930")
    assert r.status_code == 200 and r.json()["stock"]["code"] == "005930"  # 지금처럼 로그인 없이 열린다


def test_overview_route_is_not_shadowed_by_stock_detail(client, fake_overview):
    login(client)
    body = client.get("/api/stock/005930/overview").json()
    assert "about" in body and "stock" not in body
