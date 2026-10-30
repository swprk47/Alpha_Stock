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


# ── 읽기 전용·저장값 검증(리뷰에서 미룬 항목) ──


def _set_stored(client, settings):
    data = _store().load(_uid())
    data["settings"] = settings
    _store().save(_uid(), data)


def test_reading_settings_does_not_create_a_user_file(client):
    import server
    mgr = server.portfolio_mgr
    assert mgr.get_settings("dev:never-seen") == {"allow_closed_trading": True}
    assert mgr.store.load("dev:never-seen") is None  # 읽기만 했으니 파일이 생기지 않는다


def test_me_for_a_session_whose_user_file_is_gone_does_not_recreate_it(client):
    import os
    login(client)
    os.remove(_store()._path(_uid()))
    r = client.get("/api/me")
    assert r.status_code == 200 and r.json()["settings"] == {"allow_closed_trading": True}
    assert _store().load(_uid()) is None


@pytest.mark.parametrize("bad", ["false", "true", 0, 1, None, [], {}, "no"])
def test_stored_non_bool_value_falls_back_to_the_default(client, bad):
    login(client)
    _set_stored(client, {"allow_closed_trading": bad})
    assert client.get("/api/me").json()["settings"] == {"allow_closed_trading": True}


@pytest.mark.parametrize("settings", ["x", 5, None, ["a"]])
def test_stored_settings_that_is_not_an_object_falls_back_to_the_default(client, settings):
    login(client)
    _set_stored(client, settings)
    assert client.get("/api/me").json()["settings"] == {"allow_closed_trading": True}


def test_stored_boolean_is_kept_and_unknown_keys_are_not_exposed(client):
    login(client)
    _set_stored(client, {"allow_closed_trading": False, "weird": 1})
    assert client.get("/api/me").json()["settings"] == {"allow_closed_trading": False}


def test_a_string_in_the_file_does_not_block_orders(client):
    # 손으로 고친 "false"(문자열)는 차단으로 읽히지 않는다: 허용(기본)이므로 정규장이 아니어도 주문이 된다
    login(client)
    _set_stored(client, {"allow_closed_trading": "false"})
    client.quotes["005930"]["market_state"] = {"state": "closed", "nxt_listed": True}
    assert client.post("/api/buy", json={"code": "005930", "quantity": 1}).status_code == 200
