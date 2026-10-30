"""종목 개요: 네이버 호출·캐시·글자 정제 도구(backend/overview.py).

네트워크는 쓰지 않는다. requests.get 은 가짜로 바꾸고, 캐시 시간은 가짜 시계로 흉내 낸다.
"""
import math
import threading
import time

import pytest
import requests

import overview


# ── 글자 정제 ──


def test_clean_text_unescapes_and_converts_br():
    assert overview.clean_text("a&quot;b<br><br>c", 100) == 'a"b\n\nc'


def test_clean_text_converts_br_variants():
    assert overview.clean_text("a<br/>b<BR />c", 100) == "a\nb\nc"


def test_clean_text_strips_other_tags_and_keeps_spacing():
    out = overview.clean_text("<script>x</script>합니다.한국거래소  끝", 100)
    assert "<" not in out and ">" not in out
    assert "합니다.한국거래소  끝" in out  # 이중 공백과 공백 없는 이음은 원문 그대로


def test_clean_text_non_string_and_length():
    assert overview.clean_text(None, 10) == ""
    assert overview.clean_text(5, 10) == ""
    assert overview.clean_text(["a"], 10) == ""
    assert len(overview.clean_text("가" * 50, 10)) == 10


def test_clean_text_strips_outer_whitespace():
    assert overview.clean_text("  가나  ", 10) == "가나"


# ── 운용사 접미사 ──


def test_strip_issuer_suffix_only_trailing_etf():
    assert overview.strip_issuer_suffix("삼성자산운용(ETF)") == "삼성자산운용"
    assert overview.strip_issuer_suffix("미래에셋자산운용") == "미래에셋자산운용"
    assert overview.strip_issuer_suffix("(ETF)운용") == "(ETF)운용"


# ── 비중 ──


@pytest.mark.parametrize("raw,expected", [
    ("34.19%", 34.19), ("2.3", 2.3), (66.12, 66.12), (5, 5.0), ("0%", 0.0),
])
def test_format_weight_accepts_numbers_and_percent_strings(raw, expected):
    assert overview.format_weight(raw) == expected


@pytest.mark.parametrize("raw", ["-", "", None, True, False, float("nan"), float("inf"), "abc", [], {}])
def test_format_weight_rejects_everything_else(raw):
    assert overview.format_weight(raw) is None


# ── 뉴스 시각·링크 ──


def test_format_news_time():
    assert overview.format_news_time("202610302159") == "10.30 21:59"
    assert overview.format_news_time("2026") == ""
    assert overview.format_news_time(None) == ""
    assert overview.format_news_time("2026103021ab") == ""


@pytest.mark.parametrize("url,ok", [
    ("https://n.news.naver.com/mnews/article/052/0002426340", True),
    ("http://n.news.naver.com/mnews/article/052/0002426340", False),
    ("javascript:alert(1)", False),
    ("https://evil.example.com/https://n.news.naver.com/", False),
    ("https://n.news.naver.com.evil.com/x", False),
    (None, False),
    (5, False),
])
def test_safe_news_url(url, ok):
    assert overview.safe_news_url(url) == (url if ok else "")


# ── 캐시 ──


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


def test_cache_returns_cached_within_ttl_and_expires():
    clock = FakeClock()
    cache = overview.TtlCache(clock=clock)
    calls = []

    def loader():
        calls.append(1)
        return {"n": len(calls)}

    v1, at1 = cache.get_or_load(("k",), 60, loader)
    clock.now += 59
    v2, at2 = cache.get_or_load(("k",), 60, loader)
    assert v2 == v1 and at2 == at1 == 1000.0 and len(calls) == 1
    clock.now += 2  # 61초 뒤
    v3, at3 = cache.get_or_load(("k",), 60, loader)
    assert v3 == {"n": 2} and at3 == 1061.0 and len(calls) == 2


def test_cache_keys_are_independent():
    cache = overview.TtlCache(clock=FakeClock())
    assert cache.get_or_load(("a",), 60, lambda: 1)[0] == 1
    assert cache.get_or_load(("b",), 60, lambda: 2)[0] == 2


def test_cache_does_not_store_failures():
    cache = overview.TtlCache(clock=FakeClock())
    calls = []

    def boom():
        calls.append(1)
        raise overview.OverviewFetchError("x")

    for _ in range(2):
        with pytest.raises(overview.OverviewFetchError):
            cache.get_or_load(("k",), 60, boom)
    assert len(calls) == 2  # 실패는 기억하지 않고 다시 시도한다


def test_cache_dedupes_concurrent_loads():
    cache = overview.TtlCache()
    started = threading.Event()
    release = threading.Event()
    calls = []

    def slow_loader():
        calls.append(1)
        started.set()
        release.wait(5)
        return "v"

    results = []

    def worker():
        results.append(cache.get_or_load(("k",), 60, slow_loader)[0])

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    assert started.wait(5)
    time.sleep(0.1)  # 나머지 스레드가 같은 키를 기다리게 둔다
    release.set()
    for t in threads:
        t.join(5)
    assert results == ["v"] * 8 and len(calls) == 1


def test_cache_dedupe_failure_is_shared_not_silently_swallowed():
    cache = overview.TtlCache()
    release = threading.Event()
    started = threading.Event()

    def failing():
        started.set()
        release.wait(5)
        raise overview.OverviewFetchError("down")

    errors = []

    def worker():
        try:
            cache.get_or_load(("k",), 60, failing)
        except overview.OverviewFetchError as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    assert started.wait(5)
    time.sleep(0.1)
    release.set()
    for t in threads:
        t.join(5)
    assert len(errors) == 3  # 기다리던 호출도 값을 지어내지 않고 같은 실패를 받는다


# ── fetch_json ──


class FakeResponse:
    def __init__(self, status=200, payload=None, text_error=False):
        self.status_code = status
        self._payload = payload
        self._text_error = text_error

    def json(self):
        if self._text_error:
            raise ValueError("not json")
        return self._payload


def test_fetch_json_returns_payload_and_uses_base_headers_timeout(monkeypatch):
    seen = {}

    def fake_get(url, headers=None, timeout=None):
        seen.update(url=url, headers=headers, timeout=timeout)
        return FakeResponse(200, {"ok": 1})

    monkeypatch.setattr(overview.requests, "get", fake_get)
    assert overview.fetch_json("/api/stock/005930/integration") == {"ok": 1}
    assert seen["url"] == "https://m.stock.naver.com/api/stock/005930/integration"
    assert seen["timeout"] == 4
    assert seen["headers"]["Referer"] == "https://m.stock.naver.com/"


@pytest.mark.parametrize("make", [
    lambda: FakeResponse(500, {}),
    lambda: FakeResponse(404, {}),
    lambda: FakeResponse(200, None, text_error=True),
])
def test_fetch_json_errors_become_overview_fetch_error(monkeypatch, make):
    monkeypatch.setattr(overview.requests, "get", lambda *a, **k: make())
    with pytest.raises(overview.OverviewFetchError):
        overview.fetch_json("/x")


@pytest.mark.parametrize("exc", [requests.Timeout("t"), requests.ConnectionError("c")])
def test_fetch_json_network_errors_become_overview_fetch_error(monkeypatch, exc):
    def fake_get(*a, **k):
        raise exc

    monkeypatch.setattr(overview.requests, "get", fake_get)
    with pytest.raises(overview.OverviewFetchError):
        overview.fetch_json("/x")


def test_fetch_json_limits_concurrency_to_six(monkeypatch):
    lock = threading.Lock()
    running = {"now": 0, "peak": 0}

    def slow_get(*a, **k):
        with lock:
            running["now"] += 1
            running["peak"] = max(running["peak"], running["now"])
        time.sleep(0.05)
        with lock:
            running["now"] -= 1
        return FakeResponse(200, {})

    monkeypatch.setattr(overview.requests, "get", slow_get)
    threads = [threading.Thread(target=overview.fetch_json, args=("/x",)) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert 2 <= running["peak"] <= 6
    assert overview.MAX_CONCURRENT_CALLS == 6
