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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Callable

import requests

from market_data import HEADERS, safe_security_type

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


# ── 카드 ──
# 모든 build_* 는 순수 함수다(네트워크·시계 없음). 입력이 예상 모양이 아니면 예외를 올리고, get_overview 가 그 카드만 error 로 만든다.
# 값을 추측해 채우지 않는다.

ABOUT_STOCK_TITLE = "회사 소개"
ABOUT_ETF_TITLE = "이 ETF는"
DASH = "—"

# 영어 코드의 한글 이름(우리가 옮긴 표). 표에 없는 코드는 영어 원문 그대로 보인다. MISC 등 일부 뜻은 확인하지 못한 추정이다
SECTOR_LABELS = {
    "IT": "IT", "INDUSTRIALS": "산업재", "FINANCIALS": "금융", "CONSUMER_DISCRETIONARY": "경기소비재",
    "CONSUMER_STAPLES": "필수소비재", "COMMUNICATION": "커뮤니케이션", "HEALTHCARE": "헬스케어",
    "MATERIALS": "소재", "ENERGY": "에너지", "UTILITIES": "유틸리티", "REAL_ESTATE": "부동산", "UNCLASSIFIED": "미분류",
}
COUNTRY_LABELS = {"KR": "한국", "US": "미국", "JP": "일본", "HK": "홍콩", "CN": "중국", "MISC": "기타"}
ASSET_LABELS = {"EQUITY": "주식", "BOND": "채권", "CASH": "현금", "DERIVATIVES": "파생", "OTHERS": "기타"}

MAX_WEIGHT_ITEMS = 5      # 비중 카드에 보이는 항목 수(네이버 응답 순서의 앞쪽)
MAX_NEWS_ITEMS = 5        # 뉴스 클러스터 수


def error_card(title: str = "") -> dict:
    return {"status": "error", "title": title}


def _empty_about(title: str = "") -> dict:
    return {"status": "empty", "title": title, "paragraphs": []}


def _as_list(value: Any) -> list:
    """None 은 빈 목록, 목록이 아니면 예외(모양이 바뀐 응답을 값으로 채우지 않는다)."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError(f"expected a list, got {type(value).__name__}")
    return value


def build_about_stock(finance: dict) -> dict:
    summary = finance["corporationSummary"]  # 키가 없으면 KeyError → error. 값이 null 이면 소개 없음(empty)
    if summary is None:
        return _empty_about(ABOUT_STOCK_TITLE)
    if not isinstance(summary, dict):
        raise TypeError("corporationSummary is not an object")
    paragraphs = [clean_text(summary.get(key), 400) for key in ("comment1", "comment2", "comment3")]
    paragraphs = [p for p in paragraphs if p]
    if not paragraphs:
        return _empty_about(ABOUT_STOCK_TITLE)
    return {"status": "ok", "title": ABOUT_STOCK_TITLE, "paragraphs": paragraphs}


def build_about_etf(etf: dict) -> dict:
    text = clean_text(etf["etfSummary"], 3000)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return _empty_about(ABOUT_ETF_TITLE)
    return {"status": "ok", "title": ABOUT_ETF_TITLE, "paragraphs": paragraphs}


def _value_or_dash(value: Any, max_len: int = 60) -> str:
    return clean_text(value, max_len) or DASH


def build_facts_stock(integration: dict, industry_names: "dict[str, str]") -> dict:
    infos = {t["code"]: t for t in _as_list(integration.get("totalInfos")) if isinstance(t, dict) and "code" in t}

    def row(label, code, note_of):
        info = infos.get(code) or {}
        desc = clean_text(info.get("valueDesc"), 20)
        value = _value_or_dash(info.get("value"))
        return {"label": label, "value": value, "note": note_of(desc) if value != DASH else ""}  # 값이 없으면 기준도 적지 않는다

    industry_code = integration.get("industryCode")
    industry = industry_names.get(str(industry_code)) if industry_code is not None else None
    items = [
        {"label": "업종", "value": industry or DASH, "note": ""},
        row("시가총액", "marketValue", lambda d: "현재 시세 기준"),
        row("PER", "per", lambda d: f"{d} 실적 기준" if d else ""),
        row("PBR", "pbr", lambda d: f"{d} 실적 기준" if d else ""),
        row("배당수익률", "dividendYieldRatio", lambda d: f"{d} 기준" if d else ""),
        row("외인소진율", "foreignRate", lambda d: ""),
    ]
    return {"status": "ok", "items": items}


def _format_listed_date(raw: Any) -> str:
    if isinstance(raw, str) and re.fullmatch(r"\d{8}", raw):
        return f"{raw[:4]}.{raw[4:6]}.{raw[6:]}"
    return DASH


def _format_fee(raw: Any) -> str:
    number = format_weight(raw) if isinstance(raw, (int, float)) else None
    return f"{number:g}%" if number is not None else DASH  # 반올림하지 않는다("연" 도 붙이지 않는다)


def build_facts_etf(etf: dict) -> dict:
    items = [
        {"label": "기초지수", "value": _value_or_dash(etf.get("etfBaseIndex"), 80), "note": ""},
        {"label": "운용사", "value": strip_issuer_suffix(clean_text(etf.get("issuerName"), 60)) or DASH, "note": ""},
        {"label": "총보수", "value": _format_fee(etf.get("totalFee")), "note": ""},
        {"label": "상장일", "value": _format_listed_date(etf.get("listedDate")), "note": ""},
    ]
    return {"status": "ok", "items": items}


def build_holdings(etf: dict) -> dict:
    entries = _as_list(etf["etfTop10MajorConstituentAssets"])
    items = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = clean_text(entry.get("itemName"), 80)
        if not name:
            continue
        items.append({"name": name, "count": clean_text(entry.get("stockCount"), 20), "weight": format_weight(entry.get("etfWeight"))})
    return {"status": "ok" if items else "empty", "items": items}


def _weight_items(entries: list, labels: "dict[str, str]") -> list:
    items = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        code = entry.get("detailTypeCode")
        weight = format_weight(entry.get("weight"))
        if not isinstance(code, str) or weight is None or weight <= 0:
            continue
        items.append({"label": labels.get(code, clean_text(code, 40)), "weight": weight})
    return items[:MAX_WEIGHT_ITEMS]


def _first_code(entries: list) -> "str | None":
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("detailTypeCode"), str):
            return entry["detailTypeCode"]
    return None


def build_weights(etf: dict) -> dict:
    sector = _as_list(etf.get("sectorPortfolioList"))
    country = _as_list(etf.get("countryPortfolioList"))
    asset = _as_list(etf.get("assetPortfolioList"))
    equity = next((format_weight(e.get("weight")) for e in asset if isinstance(e, dict) and e.get("detailTypeCode") == "EQUITY"), None)
    # 보이는 순서는 업종 → 국가 → 자산이다. 의미 없는 카드는 숨긴다(미분류 업종, 한국 하나뿐인 국가, 주식이 대부분인 자산)
    plan = [
        ("sector", "업종별 비중", sector, SECTOR_LABELS, "sectorPortfolioTotalWeight", _first_code(sector) not in (None, "UNCLASSIFIED")),
        ("country", "국가별 비중", country, COUNTRY_LABELS, "countryPortfolioTotalWeight", _first_code(country) not in (None, "KR")),
        ("asset", "자산별 비중", asset, ASSET_LABELS, "assetPortfolioTotalWeight", equity is not None and equity < 50),
    ]
    cards = []
    for key, title, entries, labels, total_key, show in plan:
        if not show:
            continue
        items = _weight_items(entries, labels)
        if items:
            cards.append({"key": key, "title": title, "total": format_weight(etf.get(total_key)), "items": items})
    return {"status": "ok" if cards else "empty", "cards": cards}


def build_news(news: list) -> dict:
    items = []
    for cluster in _as_list(news):
        if not isinstance(cluster, dict):
            continue
        articles = cluster.get("items")
        if not isinstance(articles, list) or not articles or not isinstance(articles[0], dict):
            continue
        article = articles[0]
        title = clean_text(article.get("titleFull") or article.get("title"), 200)
        url = safe_news_url(article.get("mobileNewsUrl"))
        if not title or not url:
            continue
        total = cluster.get("total")
        more = total - 1 if isinstance(total, int) and not isinstance(total, bool) and total > 1 else 0
        items.append({"title": title, "office": clean_text(article.get("officeName"), 40),
                      "time": format_news_time(article.get("datetime")), "url": url, "more": more})
        if len(items) == MAX_NEWS_ITEMS:
            break
    return {"status": "ok" if items else "empty", "items": items}


def build_industry_names(raw: dict) -> "dict[str, str]":
    """업종 번호 → 이름(/api/stocks/industry 의 groups)."""
    names = {}
    for group in _as_list(raw["groups"]):
        if isinstance(group, dict) and "no" in group and isinstance(group.get("name"), str):
            names[str(group["no"])] = clean_text(group["name"], 40)
    return names


# ── 조립 ──

TTL_INTEGRATION = 60            # 화면의 60초 자동 갱신과 맞춘다(시총 등은 현재 시세 기준)
TTL_FINANCE = 6 * 3600          # 소개 문장은 거의 안 바뀐다
TTL_ETF = 3600                  # ETF 구성·순자산은 일 단위로 바뀐다
TTL_NEWS = 300
TTL_INDUSTRY = 24 * 3600        # 79개 고정 표
SOURCE_URL = "https://m.stock.naver.com/domestic/stock/{code}/total"  # 네이버 종목 페이지(2026-10-30 주식·ETF 모두 200 확인). 빈 값이면 화면은 링크 없이 출처 글자만 보인다

_default_cache = TtlCache()


def _load(cache: TtlCache, source: str, code: str, path: str, ttl: float) -> tuple:
    return cache.get_or_load((source, code), ttl, lambda: fetch_json(path))


def _safe_card(code: str, source: str, builder: Callable, *args, title: str = "") -> dict:
    try:
        return builder(*args)
    except Exception as e:  # 모양이 바뀐 응답은 그 카드만 error 로 두고 값을 지어내지 않는다
        print(f"Overview parse error {code} {source}: {e}")
        return error_card(title)


def get_overview(code: str, cache: "TtlCache | None" = None) -> dict:
    """종목 개요 응답. 카드마다 status(ok/empty/error)가 따로이며 한 호출이 실패해도 나머지는 그대로다."""
    cache = cache or _default_cache
    stamps = []  # 이번 응답에 쓴 네이버 응답을 가져온 시각들

    integ = None
    try:
        integ, at = _load(cache, "integration", code, f"/api/stock/{code}/integration", TTL_INTEGRATION)
        if not isinstance(integ, dict):
            raise TypeError("integration is not an object")
        stamps.append(at)
    except Exception as e:
        print(f"Overview fetch error {code} integration: {e}")
        integ = None
    kind = safe_security_type(integ.get("stockEndType")) if integ is not None else ""

    if integ is None:
        wanted = ["news"]
    elif kind == "stock":
        wanted = ["finance", "industry", "news"]
    elif kind == "etf":
        wanted = ["etf", "news"]
    else:
        wanted = ["news"]
    specs = {
        "finance": ("finance", code, f"/api/stock/{code}/finance/annual", TTL_FINANCE),
        "industry": ("industry", "", "/api/stocks/industry?page=1&pageSize=100", TTL_INDUSTRY),
        "etf": ("etf", code, f"/api/stock/{code}/etfAnalysis", TTL_ETF),
        "news": ("news", code, f"/api/news/stock/{code}?pageSize={MAX_NEWS_ITEMS}&page=1", TTL_NEWS),
    }
    results = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {name: pool.submit(_load, cache, *specs[name]) for name in wanted}
        for name, future in futures.items():
            try:
                value, at = future.result()
                results[name] = value
                if name != "industry":  # 업종 이름 표는 값이 아니라 이름 번역이라 신선도 시각에 넣지 않는다
                    stamps.append(at)
            except Exception as e:
                print(f"Overview fetch error {code} {name}: {e}")

    if integ is None:
        about = error_card()
        facts = holdings = weights = error_card()
    elif kind == "stock":
        about = (_safe_card(code, "finance", build_about_stock, results["finance"], title=ABOUT_STOCK_TITLE)
                 if "finance" in results else error_card(ABOUT_STOCK_TITLE))
        industry_names = {}
        if "industry" in results:
            try:
                industry_names = build_industry_names(results["industry"])
            except Exception as e:
                print(f"Overview parse error {code} industry: {e}")
        facts = _safe_card(code, "integration", build_facts_stock, integ, industry_names)
        holdings = {"status": "empty", "items": []}
        weights = {"status": "empty", "cards": []}
    elif kind == "etf":
        if "etf" in results:
            etf = results["etf"]
            about = _safe_card(code, "etf", build_about_etf, etf, title=ABOUT_ETF_TITLE)
            facts = _safe_card(code, "etf", build_facts_etf, etf)
            holdings = _safe_card(code, "etf", build_holdings, etf)
            weights = _safe_card(code, "etf", build_weights, etf)
        else:
            about, facts, holdings, weights = error_card(ABOUT_ETF_TITLE), error_card(), error_card(), error_card()
    else:  # ETN 이거나 종류를 알 수 없다: 소개 대신 안내 화면, 뉴스는 시도한다
        about = _empty_about()
        facts = {"status": "empty", "items": []}
        holdings = {"status": "empty", "items": []}
        weights = {"status": "empty", "cards": []}

    news = _safe_card(code, "news", build_news, results["news"]) if "news" in results else error_card()
    fetched_at = datetime.fromtimestamp(min(stamps)).strftime("%Y-%m-%d %H:%M:%S") if stamps else ""
    return {
        "success": True, "code": code, "kind": kind, "fetched_at": fetched_at,
        "source_url": SOURCE_URL.format(code=code) if SOURCE_URL else "",
        "about": about, "facts": facts, "holdings": holdings, "weights": weights, "news": news,
    }
