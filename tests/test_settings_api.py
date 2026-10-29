"""사용자별 설정(settings.allow_closed_trading) — 내 메뉴의 "장 마감 중 거래" 토글이 쓴다.

기본은 허용(true). 사용자 JSON 에 settings 키가 없는 옛 파일도 허용으로 읽는다. 요청 스키마는 extra=forbid.
설정은 서버가 저장하고 강제한다(주문 강제는 test_order_market_policy.py).
"""
import pytest

from conftest import login


def _uid(nickname="alice"):
    from auth import dev_user_id
    return dev_user_id(nickname)


def _store():
    import server
    return server.portfolio_mgr.store


def test_default_is_allowed(client):
    login(client)
    me = client.get("/api/me").json()
    assert me["settings"] == {"allow_closed_trading": True}


def test_old_user_file_without_settings_key_reads_as_allowed(client):
    login(client)
    data = _store().load(_uid())
    data.pop("settings", None)
    _store().save(_uid(), data)
    assert client.get("/api/me").json()["settings"] == {"allow_closed_trading": True}


def test_post_saves_and_survives_reload(client):
    login(client)
    r = client.post("/api/settings", json={"allow_closed_trading": False})
    assert r.status_code == 200
    assert r.json() == {"success": True, "settings": {"allow_closed_trading": False}}
    assert client.get("/api/me").json()["settings"]["allow_closed_trading"] is False
    # 파일에 실제로 저장됐다(메모리 값이 아니다)
    assert _store().load(_uid())["settings"]["allow_closed_trading"] is False
    assert client.post("/api/settings", json={"allow_closed_trading": True}).json()["settings"]["allow_closed_trading"] is True


def test_settings_are_per_user(client):
    login(client, "alice")
    client.post("/api/settings", json={"allow_closed_trading": False})
    login(client, "bob")
    assert client.get("/api/me").json()["settings"]["allow_closed_trading"] is True


def test_reset_keeps_settings(client):
    login(client)
    client.post("/api/settings", json={"allow_closed_trading": False})
    assert client.post("/api/reset").status_code == 200
    assert client.get("/api/me").json()["settings"]["allow_closed_trading"] is False


@pytest.mark.parametrize("body", [
    {"allow_closed_trading": False, "user_id": "x"},   # 알 수 없는 필드
    {"foo": 1},
    {},                                                 # 필수 필드 없음
])
def test_unknown_or_missing_fields_are_422(client, body):
    login(client)
    assert client.post("/api/settings", json=body).status_code == 422


@pytest.mark.parametrize("value", ["nope", "false", 0, None, [], {}])
def test_non_bool_is_422(client, value):
    login(client)
    assert client.post("/api/settings", json={"allow_closed_trading": value}).status_code == 422


def test_requires_login_401(client):
    assert client.post("/api/settings", json={"allow_closed_trading": False}).status_code == 401
