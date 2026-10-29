"""서버 연결: /api/search 가 색인 갱신을 시작하고 검색어 길이를 제한하며, 서버 시작 때 색인을 백그라운드로 만든다.

색인 갱신은 검색을 기다리게 하지 않는다(ensure_fresh / refresh_async 는 스레드를 띄우고 바로 돌아온다).
이 파일은 색인·검색·추천 캐시를 가짜로 바꿔서 네트워크를 쓰지 않는다.
"""
import pytest

import config
import server
from symbol_index import MAX_QUERY_LEN


class FakeIndex:
    def __init__(self, events):
        self.events = events
        self.ensure_calls = 0
        self.refresh_async_calls = 0

    def ensure_fresh(self):
        self.ensure_calls += 1
        self.events.append("ensure_fresh")

    def refresh_async(self):
        self.refresh_async_calls += 1
        self.events.append("refresh_async")


@pytest.fixture
def wired(client, monkeypatch):
    events = []
    idx = FakeIndex(events)
    monkeypatch.setattr(server, "symbol_index", idx)

    def fake_search(q):
        events.append(f"search:{q}")
        return [{"code": "005930", "name": "삼성전자"}]

    monkeypatch.setattr(server, "search_stocks", fake_search)
    client.events, client.idx = events, idx
    return client


def test_search_starts_a_background_refresh_before_answering(wired):
    r = wired.get("/api/search", params={"q": "성전자"})
    assert r.status_code == 200
    assert r.json() == {"success": True, "results": [{"code": "005930", "name": "삼성전자"}]}  # 응답 모양은 그대로
    assert wired.events == ["ensure_fresh", "search:성전자"]  # 갱신은 시작만 하고 검색은 기다리지 않고 바로 답한다


def test_search_does_not_need_a_login(wired):
    assert wired.get("/api/search", params={"q": "삼성"}).status_code == 200  # 예전과 같다


def test_every_search_asks_the_index_to_stay_fresh(wired):
    wired.get("/api/search", params={"q": "a"})
    wired.get("/api/search", params={"q": "b"})
    assert wired.idx.ensure_calls == 2  # 실제로 받을지는 색인이 TTL·재시도 간격으로 정한다


def test_query_length_is_limited(wired):
    assert wired.get("/api/search", params={"q": "가" * MAX_QUERY_LEN}).status_code == 200
    r = wired.get("/api/search", params={"q": "가" * (MAX_QUERY_LEN + 1)})
    assert r.status_code == 422
    assert wired.events.count("ensure_fresh") == 1  # 거절된 요청은 갱신도 검색도 일으키지 않는다


def test_empty_or_missing_query_is_rejected(wired):
    assert wired.get("/api/search", params={"q": ""}).status_code == 422
    assert wired.get("/api/search").status_code == 422
    assert wired.events == []


def test_startup_builds_the_index_in_the_background_without_blocking(wired, monkeypatch):
    class FakeCache:
        def get(self, budget, force=False):
            wired.events.append(f"rec_cache.get:{budget}")

    monkeypatch.setattr(server, "rec_cache", FakeCache())
    server.startup_event()
    # 색인 구축은 시작만 하고(스레드), 추천 계산(오래 걸릴 수 있음)을 기다리는 동안 같이 진행된다
    assert wired.events == ["refresh_async", f"rec_cache.get:{config.DEFAULT_INITIAL_BALANCE}"]
    assert wired.idx.refresh_async_calls == 1
