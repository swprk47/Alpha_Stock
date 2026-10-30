"""
overview.py
종목 개요 탭: 네이버 증권 모바일 API 의 소개·기본 정보·ETF 구성·뉴스를 받아 정제해 카드로 돌려준다.

- 우리가 문장이나 숫자를 만들지 않는다. 네이버 값을 정제(엔티티·태그)해서 그대로 전한다.
- 호출은 타임아웃 4초, 서버 전체 동시 6개로 제한하고, 성공한 응답만 TTL 동안 캐시한다.
"""
import html
import math
import re
import threading
import time
from datetime import datetime
from typing import Any, Callable

import requests

from market_data import HEADERS

NAVER_BASE = "https://m.stock.naver.com"
CALL_TIMEOUT = 4              # 네이버 한 번 호출의 제한 시간(초). 기존 시세 조회와 같다
MAX_CONCURRENT_CALLS = 6      # 서버 전체에서 동시에 네이버로 나가는 호출 수

_call_slots = threading.Semaphore(MAX_CONCURRENT_CALLS)


class OverviewFetchError(Exception):
    """네이버 호출 실패(네트워크·상태 코드·JSON 아님). 그 카드만 error 로 표시한다."""


def fetch_json(path: str) -> Any:
    """NAVER_BASE + path 를 GET 해서 JSON 으로 돌려준다. 실패는 모두 OverviewFetchError."""
    with _call_slots:
        try:
            res = requests.get(NAVER_BASE + path, headers=HEADERS, timeout=CALL_TIMEOUT)
        except requests.RequestException as e:
            raise OverviewFetchError(f"request failed: {path}: {e}") from e
        if res.status_code != 200:
            raise OverviewFetchError(f"status {res.status_code}: {path}")
        try:
            return res.json()
        except ValueError as e:
            raise OverviewFetchError(f"not json: {path}") from e


class _Flight:
    """같은 키를 이미 받는 중인 호출. 기다리는 쪽은 결과(또는 같은 실패)를 받는다."""

    def __init__(self):
        self.event = threading.Event()
        self.value = None
        self.fetched_at = 0.0
        self.error = None


class TtlCache:
    """성공한 값만 ttl 동안 기억하는 메모리 캐시. 같은 키의 동시 호출은 한 번만 loader 를 돌린다."""

    def __init__(self, clock: Callable[[], float] = time.time):
        self._clock = clock
        self._lock = threading.Lock()
        self._items = {}    # key -> (value, fetched_at)
        self._flights = {}  # key -> _Flight

    def get_or_load(self, key: tuple, ttl_seconds: float, loader: Callable[[], Any]) -> tuple:
        """(값, 가져온 epoch). loader 가 예외면 그대로 올리고 아무것도 기억하지 않는다."""
        with self._lock:
            hit = self._items.get(key)
            if hit is not None and self._clock() - hit[1] < ttl_seconds:
                return hit
            flight = self._flights.get(key)
            leader = flight is None
            if leader:
                flight = self._flights[key] = _Flight()
        if not leader:
            flight.event.wait()
            if flight.error is not None:
                raise flight.error
            return flight.value, flight.fetched_at
        try:
            value = loader()
            fetched_at = self._clock()
            with self._lock:
                self._items[key] = (value, fetched_at)
            flight.value, flight.fetched_at = value, fetched_at
            return value, fetched_at
        except BaseException as e:
            flight.error = e
            raise
        finally:
            with self._lock:
                self._flights.pop(key, None)
            flight.event.set()


# ── 글자·숫자 정제 ──

_BR_RE = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")


def clean_text(value: Any, max_len: int) -> str:
    """
    네이버 글자를 평문으로: 엔티티(&quot; 등)를 글자로, <br> 는 줄바꿈으로, 그 밖의 태그는 제거한다.
    문자열이 아니면 "". 앞뒤 공백을 떼고 max_len 으로 자른다. 그 밖의 글자(이중 공백, 공백 없는 문장 이음)는 그대로 둔다.
    """
    if not isinstance(value, str):
        return ""
    text = html.unescape(value)
    text = _BR_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    return text.strip()[:max_len]


def strip_issuer_suffix(name: str) -> str:
    """운용사 이름 끝의 "(ETF)" 한 가지만 뗀다(ETF 화면에서 중복). 그 밖은 그대로."""
    suffix = "(ETF)"
    return name[:-len(suffix)] if name.endswith(suffix) and len(name) > len(suffix) else name


def format_weight(value: Any) -> "float | None":
    """비중: 숫자나 "34.19%"/"2.3" 는 float, "-"·빈 값·bool·NaN·inf·그 밖은 None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        try:
            number = float(value.strip().rstrip("%").strip())
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def format_news_time(raw: Any) -> str:
    """"202610302159" → "10.30 21:59". 이상하면 ""."""
    if not isinstance(raw, str):
        return ""
    try:
        when = datetime.strptime(raw, "%Y%m%d%H%M")
    except ValueError:
        return ""
    return when.strftime("%m.%d %H:%M")


_NEWS_URL_RE = re.compile(r"https://n\.news\.naver\.com/[A-Za-z0-9._~:/?#@!$&'()*+,;=%\[\]-]*")


def safe_news_url(url: Any) -> str:
    """네이버 뉴스 주소(https://n.news.naver.com/…)만 통과시킨다. 그 밖은 ""."""
    return url if isinstance(url, str) and _NEWS_URL_RE.fullmatch(url) else ""
