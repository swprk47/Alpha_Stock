import pytest
from fastapi.testclient import TestClient

from conftest import login


@pytest.mark.parametrize("method,path,body", [
    ("get", "/api/portfolio", None),
    ("post", "/api/buy", {"code": "005930", "quantity": 1}),
    ("post", "/api/sell", {"code": "005930"}),
    ("post", "/api/reset", None),
    ("post", "/api/portfolio/budget", {"budget": 200000}),
    ("get", "/api/me", None),
])
def test_unauthenticated_401(client, method, path, body):
    r = getattr(client, method)(path, json=body) if body else getattr(client, method)(path)
    assert r.status_code == 401


def test_user_id_field_rejected(client):
    login(client)
    r = client.post("/api/buy", json={"code": "005930", "quantity": 1, "user_id": "victim"})
    assert r.status_code == 422


def test_query_user_id_ignored_and_users_isolated(client):
    import server
    login(client, "alice")
    assert client.post("/api/buy", json={"code": "005930", "quantity": 2}).status_code == 200

    bob = TestClient(server.app)
    login(bob, "bob")
    p = bob.get("/api/portfolio?user_id=alice").json()["portfolio"]
    assert p["holdings"] == []
    assert p["cash_balance"] == 100_000


def test_tampered_cookie_401(client):
    client.cookies.set("alpha_session", "garbage.token.value")
    assert client.get("/api/portfolio").status_code == 401


def test_logout_clears_session(client):
    login(client)
    assert client.get("/api/me").status_code == 200
    client.post("/api/auth/logout")
    client.cookies.clear()
    assert client.get("/api/me").status_code == 401


def test_dev_login_disabled(client, monkeypatch):
    import config
    login(client)
    monkeypatch.setattr(config, "ALLOW_DEV_LOGIN", False)
    assert client.post("/api/auth/dev-login", json={"nickname": "x"}).status_code == 404
    # 이미 발급된 dev 세션도 무효
    assert client.get("/api/portfolio").status_code == 401


def test_refresh_requires_login(client):
    assert client.get("/api/recommendations?refresh=true").status_code == 401


def test_session_cookie_flags(client):
    r = client.post("/api/auth/dev-login", json={"nickname": "alice"})
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=lax" in sc
