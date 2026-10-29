"""
symbol_index.py
종목 색인: 이름 가운데 글자·코드 앞부분으로 종목을 찾는다.

네이버 자동완성(ac.stock.naver.com)은 이름의 맨 앞부분 일치만 되어서 "삼성"은 찾아도 "성전자"·"반도체"·"S&P500"은
못 찾는다. 그래서 전체 종목 목록(KOSPI·KOSDAQ, ETF·ETN 포함 약 4,300개)을 서버 메모리에 두고 직접 찾는다.
4천 건 정도라 전수 스캔이 한 번에 0.5ms 안팎이라 색인 구조를 따로 만들지 않는다.

- 목록을 가져오는 함수(fetch)를 SymbolIndex 에 넣어 주는 구조라 공급자를 바꾸기 쉽다(지금은 네이버 marketValue).
- 색인은 어떤 종목인지만 정한다. 검색 결과의 가격·등락·로고는 호출하는 쪽이 실시간 시세로 채운다(여기 값은 하루 묵은 것).
- 갱신은 백그라운드: 갱신 중에도 이전 색인으로 즉시 답하고, 실패하면 이전 색인을 그대로 둔다. 한 번도 못 만들었으면 빈 결과다.
"""
import threading
import time
from typing import Callable, List, NamedTuple, Optional

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://m.stock.naver.com/",
}

SYMBOL_TTL_SECONDS = 24 * 60 * 60   # 이 시간이 지나면 다음 검색 때 백그라운드로 다시 받는다
RETRY_SECONDS = 60                  # 받기에 실패한 뒤 다시 시도하기까지의 최소 간격(네이버 장애 때 검색마다 44번씩 받지 않는다)
MAX_QUERY_LEN = 30                  # 검색어는 앞 30자만 쓴다
NAVER_PAGE_SIZE = 100               # 네이버 marketValue 의 쪽 크기 상한(101 이상은 400 으로 거절한다)
_MARKETS = ("KOSPI", "KOSDAQ")
_MAX_PAGES = 100                    # totalCount 가 이상해도 무한 반복하지 않는다
_KINDS = ("stock", "etf", "etn")    # market_data.SECURITY_TYPES 와 같은 값


class Symbol(NamedTuple):
    code: str
    name: str
    market: str
    security_type: str   # stock / etf / etn, 모르면 ""
    trading_value: int   # 거래대금(원). 같은 일치 순위 안에서 큰 종목을 먼저 보이는 데 쓴다


def normalize(text) -> str:
    """대소문자와 모든 공백을 없앤다. 기호(&, ( 등)는 이름의 일부라 그대로 둔다."""
    if text is None:
        return ""
    return "".join(str(text).split()).lower()


def _int(value) -> int:
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0


def fetch_naver_symbols(get: Optional[Callable] = None, page_size: int = NAVER_PAGE_SIZE) -> List[Symbol]:
    """네이버 marketValue 로 KOSPI·KOSDAQ 전체 종목을 받는다(약 44번 요청, 순차 3초 안팎).

    한 시장이라도 실패하거나 목록이 비면 예외를 던진다: 반쪽짜리 색인으로 이전 색인을 덮어쓰지 않기 위해서다.
    """
    get = get or requests.get
    out: List[Symbol] = []
    seen = set()
    for market in _MARKETS:
        page = 1
        while page <= _MAX_PAGES:
            res = get(f"https://m.stock.naver.com/api/stocks/marketValue/{market}",
                      params={"page": page, "pageSize": page_size}, headers=HEADERS, timeout=10)
            if res.status_code != 200:
                raise RuntimeError(f"{market} {page}쪽 응답 오류 {res.status_code}")
            data = res.json()
            stocks = data.get("stocks") if isinstance(data, dict) else None
            if not isinstance(stocks, list):
                raise RuntimeError(f"{market} {page}쪽 응답 형식 오류")
            if not stocks:
                break
            for s in stocks:
                code = str(s.get("itemCode") or "").strip()
                name = str(s.get("stockName") or "").strip()
                if not code or not name or code in seen:
                    continue
                seen.add(code)
                kind = s.get("stockEndType")
                out.append(Symbol(code, name, market, kind if kind in _KINDS else "",
                                  _int(s.get("accumulatedTradingValueRaw"))))
            total = data.get("totalCount")
            if isinstance(total, int) and page * page_size >= total:
                break
            page += 1
    if not out:
        raise RuntimeError("종목 목록이 비어 있습니다")
    return out


class SymbolIndex:
    def __init__(self, fetch: Callable[[], List[Symbol]], ttl: float = SYMBOL_TTL_SECONDS,
                 clock: Callable[[], float] = time.time, retry_seconds: float = RETRY_SECONDS):
        self._fetch = fetch
        self._ttl = ttl
        self._clock = clock
        self._retry = retry_seconds
        self._entries: tuple = ()          # (정규화한 이름, 정규화한 코드, Symbol). 통째로 바꿔 끼우므로 읽는 쪽은 잠금이 필요 없다
        self._updated = 0.0
        self._ready = False
        self._refreshing = False
        self._last_attempt: Optional[float] = None
        self._guard = threading.Lock()

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def count(self) -> int:
        return len(self._entries)

    @property
    def updated_at(self) -> float:
        return self._updated

    def refresh(self) -> bool:
        """목록을 새로 받아 색인을 바꾼다. 이미 받는 중이면 기다리지 않고 False. 실패하면 이전 색인을 그대로 둔다."""
        with self._guard:
            if self._refreshing:
                return False
            self._refreshing = True
            self._last_attempt = self._clock()
        try:
            symbols = self._fetch()
            if not symbols:
                print("Symbol index refresh: empty list, keeping the previous index")
                return False
            entries = tuple((normalize(s.name), normalize(s.code), s) for s in symbols)
            with self._guard:
                self._entries = entries
                self._updated = self._clock()
                self._ready = True
            return True
        except Exception as e:  # 네트워크·형식 오류 모두: 이전 색인을 지키는 것이 우선이다
            print(f"Symbol index refresh error: {e}")
            return False
        finally:
            with self._guard:
                self._refreshing = False

    def refresh_async(self) -> threading.Thread:
        t = threading.Thread(target=self.refresh, name="symbol-index-refresh", daemon=True)  # 서버 종료를 막지 않는다
        t.start()
        return t

    def ensure_fresh(self) -> Optional[threading.Thread]:
        """색인이 없거나 오래됐으면 백그라운드로 갱신을 시작한다(검색을 기다리게 하지 않는다). 할 일이 없으면 None."""
        with self._guard:
            if self._refreshing:
                return None
            now = self._clock()
            if self._ready and now - self._updated < self._ttl:
                return None
            if self._last_attempt is not None and now - self._last_attempt < self._retry:
                return None
        return self.refresh_async()

    def search(self, query, limit: int = 6) -> List[Symbol]:
        """일치 순위: 이름 완전 일치 → 이름 앞부분 → 코드 앞부분 → 이름 가운데. 같은 순위는 거래대금이 큰 순, 그다음 코드순."""
        q = normalize(query)[:MAX_QUERY_LEN]
        if not q:
            return []
        scored = []
        for name, code, sym in self._entries:
            if name == q:
                rank = 0
            elif name.startswith(q):
                rank = 1
            elif code.startswith(q):
                rank = 2
            elif q in name:
                rank = 3
            else:
                continue
            scored.append((rank, -sym.trading_value, sym.code, sym))
        scored.sort(key=lambda x: x[:3])
        return [x[3] for x in scored[:limit]]


# 서버가 공유하는 색인. import 만으로는 네트워크를 쓰지 않는다(server.py 의 시작 훅이 백그라운드로 채운다)
symbol_index = SymbolIndex(fetch_naver_symbols)
