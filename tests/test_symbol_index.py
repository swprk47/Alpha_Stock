"""종목 색인(symbol_index): 이름 가운데 글자·코드 앞부분으로 종목을 찾는다.

네이버 자동완성은 이름의 맨 앞부분 일치만 되어서("삼성"은 되고 "성전자"·"반도체"·"S&P500"은 안 됨)
전체 종목 목록(약 4,300개)을 서버 메모리에 두고 직접 찾는다. 이 파일은 네트워크 없이 검증한다.
"""
import threading
import time

import pytest

import symbol_index as si
from symbol_index import Symbol, SymbolIndex, fetch_naver_symbols, normalize


def S(code, name, market="KOSPI", kind="stock", tv=0):
    return Symbol(code, name, market, kind, tv)


UNIVERSE = [
    S("005930", "삼성전자", tv=4_000),
    S("005935", "삼성전자우", tv=300),
    S("009150", "삼성전기", tv=900),
    S("000660", "SK하이닉스", tv=3_000),
    S("360750", "TIGER 미국S&P500", kind="etf", tv=1_500),
    S("379800", "KODEX 미국S&P500", kind="etf", tv=1_200),
    S("133690", "TIGER 미국나스닥100", kind="etf", tv=1_100),
    S("069500", "KODEX 200", kind="etf", tv=2_000),
    S("488770", "KODEX 머니마켓액티브", kind="etf", tv=700),
    S("091160", "KODEX 반도체", kind="etf", tv=600),
    S("091230", "TIGER 반도체", kind="etf", tv=800),
    S("0183J0", "TIGER 미국우주테크", kind="etf", tv=50),
    S("000150", "두산", tv=100),
    S("035720", "카카오", tv=2_500),
    S("035420", "NAVER", tv=2_400),
    S("123456", "KODEX CD금리액티브(합성)", kind="etf", tv=10),
]


def built(symbols=None, **kw):
    idx = SymbolIndex(lambda: list(symbols if symbols is not None else UNIVERSE), **kw)
    assert idx.refresh() is True
    return idx


def names(results):
    return [s.name for s in results]


# ── 정규화 ──


def test_normalize_lowercases_and_drops_all_whitespace_but_keeps_symbols():
    assert normalize("TIGER 미국 S&P500") == "tiger미국s&p500"
    assert normalize("  삼성 전자\t") == "삼성전자"  # 줄바꿈 없는 공백·탭도 지운다
    assert normalize(None) == ""
    assert normalize("") == ""


# ── 매칭 ──


def test_middle_of_the_name_is_found():
    idx = built()
    assert names(idx.search("성전자")) == ["삼성전자", "삼성전자우"]  # 이름 가운데 일치, 거래대금 큰 순


def test_symbols_in_the_query_are_part_of_the_name():
    idx = built()
    assert names(idx.search("S&P500")) == ["TIGER 미국S&P500", "KODEX 미국S&P500"]


def test_case_and_spaces_in_the_query_are_ignored():
    idx = built()
    assert names(idx.search("tiger 미국")) == names(idx.search("TIGER미국"))
    assert "TIGER 미국S&P500" in names(idx.search("tiger 미국"))
    assert names(idx.search("naver")) == ["NAVER"]


def test_code_matches_only_from_the_start():
    idx = built()
    assert names(idx.search("0059")) == ["삼성전자", "삼성전자우"]
    assert idx.search("930") == []  # 코드 가운데는 일치시키지 않는다
    assert names(idx.search("0183j")) == ["TIGER 미국우주테크"]  # 영숫자 코드, 대소문자 무시


def test_special_characters_are_literal_not_a_pattern():
    idx = built()
    assert names(idx.search("(합성)")) == ["KODEX CD금리액티브(합성)"]
    assert idx.search(".*") == []
    assert idx.search("[") == []
    assert idx.search("\\") == []


@pytest.mark.parametrize("q", ["", "   ", None, "\t\n"])
def test_empty_query_finds_nothing(q):
    assert built().search(q) == []


def test_overlong_query_is_truncated_not_an_error():
    idx = built()
    long_q = "삼성전자" + "가" * 200
    assert idx.search(long_q) == []  # 앞 30자만 쓰므로 일치하는 종목이 없을 뿐 오류가 아니다
    assert si.MAX_QUERY_LEN == 30


# ── 정렬 ──


def test_rank_is_exact_then_name_prefix_then_code_prefix_then_middle():
    universe = [
        S("111111", "가나다 삼성", tv=9_999),   # 이름 가운데
        S("000000", "삼성", tv=1),              # 이름 완전 일치
        S("222222", "삼성물산", tv=500),        # 이름 앞부분
        S("삼성01", "코드앞부분", tv=700),      # 코드 앞부분
    ]
    idx = built(universe)
    assert names(idx.search("삼성")) == ["삼성", "삼성물산", "코드앞부분", "가나다 삼성"]


def test_same_rank_is_ordered_by_trading_value_then_code():
    # 모두 "이름 앞부분" 순위로 같다
    universe = [S("000003", "에이가", tv=10), S("000002", "에이나", tv=10), S("000001", "에이다", tv=50)]
    idx = built(universe)
    assert [s.code for s in idx.search("에이")] == ["000001", "000002", "000003"]


def test_limit_caps_the_results():
    idx = built()
    assert len(idx.search("kodex", limit=2)) == 2
    assert len(idx.search("kodex")) == 5  # 기본 한도는 6개
    assert len(idx.search("kodex", limit=99)) == 5


def test_etfs_and_stocks_are_mixed_by_the_same_rule():
    idx = built()
    assert [s.security_type for s in idx.search("반도체")] == ["etf", "etf"]
    assert names(idx.search("반도체")) == ["TIGER 반도체", "KODEX 반도체"]  # 거래대금 큰 순


def test_result_keeps_market_and_kind():
    idx = built([S("035720", "카카오", market="KOSPI"), S("247540", "에코프로비엠", market="KOSDAQ")])
    r = idx.search("에코")[0]
    assert (r.code, r.market, r.security_type) == ("247540", "KOSDAQ", "stock")


# ── 아직 없는 색인 ──


def test_search_before_the_first_build_is_empty_and_safe():
    idx = SymbolIndex(lambda: UNIVERSE)
    assert idx.ready is False and idx.count == 0
    assert idx.search("삼성") == []


# ── 갱신 ──


def test_refresh_builds_and_records_the_time():
    now = [1_000.0]
    idx = SymbolIndex(lambda: UNIVERSE, clock=lambda: now[0])
    assert idx.refresh() is True
    assert idx.ready and idx.count == len(UNIVERSE) and idx.updated_at == 1_000.0


def test_failed_refresh_keeps_the_previous_index():
    now = [1_000.0]
    state = {"fail": False}

    def fetch():
        if state["fail"]:
            raise RuntimeError("네이버 응답 오류")
        return UNIVERSE

    idx = SymbolIndex(fetch, clock=lambda: now[0])
    assert idx.refresh() is True
    state["fail"] = True
    now[0] = 9_999.0
    assert idx.refresh() is False
    assert idx.count == len(UNIVERSE) and idx.updated_at == 1_000.0  # 이전 색인과 시각 그대로
    assert names(idx.search("성전자")) == ["삼성전자", "삼성전자우"]


def test_failed_first_build_leaves_an_empty_safe_index():
    def boom():
        raise RuntimeError("down")

    idx = SymbolIndex(boom)
    assert idx.refresh() is False
    assert idx.ready is False and idx.search("삼성") == []


def test_an_empty_list_never_replaces_a_good_index():
    state = {"items": UNIVERSE}
    idx = SymbolIndex(lambda: state["items"])
    idx.refresh()
    state["items"] = []
    assert idx.refresh() is False
    assert idx.count == len(UNIVERSE)


def test_only_one_refresh_runs_at_a_time():
    started, release, calls = threading.Event(), threading.Event(), []

    def slow():
        calls.append(1)
        started.set()
        assert release.wait(5)
        return UNIVERSE

    idx = SymbolIndex(slow)
    t = threading.Thread(target=idx.refresh)
    t.start()
    assert started.wait(5)
    assert idx.refresh() is False  # 이미 갱신 중이면 기다리지도 다시 받지도 않는다
    assert len(calls) == 1
    release.set()
    t.join(5)
    assert idx.ready


def test_search_is_served_from_the_old_index_while_refreshing():
    started, release = threading.Event(), threading.Event()
    state = {"slow": False}

    def fetch():
        if state["slow"]:
            started.set()
            assert release.wait(5)
            return [S("000001", "새종목")]
        return UNIVERSE

    idx = SymbolIndex(fetch)
    idx.refresh()
    state["slow"] = True
    t = threading.Thread(target=idx.refresh)
    t.start()
    assert started.wait(5)
    assert names(idx.search("성전자")) == ["삼성전자", "삼성전자우"]  # 갱신이 끝나기 전에는 이전 색인으로 즉시 답한다
    release.set()
    t.join(5)
    assert names(idx.search("새")) == ["새종목"]


def test_refresh_async_returns_a_daemon_thread_that_finishes():
    idx = SymbolIndex(lambda: UNIVERSE)
    t = idx.refresh_async()
    assert t is not None and t.daemon is True  # 서버 종료를 막지 않는다
    t.join(5)
    assert idx.ready


# ── 오래되면 알아서 갱신 ──


def _counting(now):
    calls = []

    def fetch():
        calls.append(now[0])
        return UNIVERSE

    return fetch, calls


def test_ensure_fresh_builds_when_never_built():
    now = [0.0]
    fetch, calls = _counting(now)
    idx = SymbolIndex(fetch, ttl=100, clock=lambda: now[0])
    t = idx.ensure_fresh()
    assert t is not None
    t.join(5)
    assert len(calls) == 1 and idx.ready


def test_ensure_fresh_does_nothing_while_fresh_and_refreshes_when_stale():
    now = [0.0]
    fetch, calls = _counting(now)
    idx = SymbolIndex(fetch, ttl=100, clock=lambda: now[0])
    idx.refresh()
    now[0] = 99.0
    assert idx.ensure_fresh() is None and len(calls) == 1
    now[0] = 101.0
    t = idx.ensure_fresh()
    assert t is not None
    t.join(5)
    assert len(calls) == 2


def test_ensure_fresh_does_not_start_a_second_refresh_in_flight():
    started, release, calls = threading.Event(), threading.Event(), []

    def slow():
        calls.append(1)
        started.set()
        assert release.wait(5)
        return UNIVERSE

    idx = SymbolIndex(slow)
    t = idx.ensure_fresh()
    assert started.wait(5)
    assert idx.ensure_fresh() is None  # 이미 받는 중
    release.set()
    t.join(5)
    assert len(calls) == 1


def test_ensure_fresh_retries_after_a_failed_first_build_but_not_in_a_burst():
    now = [0.0]
    state = {"fail": True, "calls": 0}

    def fetch():
        state["calls"] += 1
        if state["fail"]:
            raise RuntimeError("down")
        return UNIVERSE

    idx = SymbolIndex(fetch, clock=lambda: now[0])
    idx.ensure_fresh().join(5)
    assert idx.ready is False and state["calls"] == 1
    # 네이버가 죽어 있을 때 검색마다 44번씩 다시 받지 않는다: 재시도 간격 안에서는 시도하지 않는다
    now[0] = si.RETRY_SECONDS - 1
    assert idx.ensure_fresh() is None and state["calls"] == 1
    state["fail"] = False
    now[0] = si.RETRY_SECONDS + 1
    idx.ensure_fresh().join(5)  # 한 번도 못 만들었으면 간격이 지난 뒤 다음 검색 때 다시 시도한다
    assert idx.ready and state["calls"] == 2


def test_a_failed_stale_refresh_also_waits_before_trying_again():
    now = [0.0]
    state = {"fail": False, "calls": 0}

    def fetch():
        state["calls"] += 1
        if state["fail"]:
            raise RuntimeError("down")
        return UNIVERSE

    idx = SymbolIndex(fetch, ttl=100, clock=lambda: now[0])
    idx.refresh()
    state["fail"] = True
    now[0] = 200.0
    idx.ensure_fresh().join(5)       # 오래돼서 갱신 시도 → 실패, 이전 색인 유지
    assert state["calls"] == 2 and idx.ready
    now[0] = 200.0 + si.RETRY_SECONDS - 1
    assert idx.ensure_fresh() is None and state["calls"] == 2


# ── 네이버 목록 공급자 ──


class Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload


def item(code, name, kind="stock", tv="1,000", **extra):
    d = {"itemCode": code, "stockName": name, "stockEndType": kind, "accumulatedTradingValueRaw": tv}
    d.update(extra)
    return d


def fake_get(pages, calls=None):
    """pages: {(시장, 쪽): 응답 dict}. 요청 파라미터를 기록한다."""
    def get(url, params=None, headers=None, timeout=None, **kw):
        if calls is not None:
            calls.append((url, dict(params or {})))
        market = url.rstrip("/").split("/")[-1]
        page = (params or {}).get("page", 1)
        if (market, page) not in pages:
            return Resp({"stocks": [], "totalCount": 0})
        return pages[(market, page)]
    return get


def test_fetch_pages_through_both_markets_until_the_total():
    calls = []
    pages = {
        ("KOSPI", 1): Resp({"totalCount": 3, "stocks": [item("005930", "삼성전자", tv="4240229000000"), item("069500", "KODEX 200", "etf")]}),
        ("KOSPI", 2): Resp({"totalCount": 3, "stocks": [item("610063", "메리츠 KIS CD금리투자 ETN", "etn")]}),
        ("KOSDAQ", 1): Resp({"totalCount": 1, "stocks": [item("247540", "에코프로비엠")]}),
    }
    # pageSize 가 100 이라 totalCount 3 이면 한 쪽이면 끝나야 한다 — 이 테스트는 2쪽까지 필요하도록 작은 쪽 크기를 쓴다
    out = fetch_naver_symbols(get=fake_get(pages, calls), page_size=2)
    assert [(s.code, s.market, s.security_type) for s in out] == [
        ("005930", "KOSPI", "stock"), ("069500", "KOSPI", "etf"), ("610063", "KOSPI", "etn"), ("247540", "KOSDAQ", "stock")]
    assert out[0].trading_value == 4240229000000
    assert [c[1]["page"] for c in calls] == [1, 2, 1]
    assert all(c[1]["pageSize"] == 2 for c in calls)
    assert all(c[0].startswith("https://m.stock.naver.com/api/stocks/marketValue/") for c in calls)


def test_fetch_default_page_size_is_the_naver_maximum_of_100():
    calls = []
    pages = {("KOSPI", 1): Resp({"totalCount": 1, "stocks": [item("005930", "삼성전자")]}),
             ("KOSDAQ", 1): Resp({"totalCount": 1, "stocks": [item("247540", "에코프로비엠")]})}
    fetch_naver_symbols(get=fake_get(pages, calls))
    assert all(c[1]["pageSize"] == 100 for c in calls)  # 101 이상은 네이버가 400 으로 거절한다


def test_fetch_is_tolerant_of_odd_field_values():
    pages = {
        ("KOSPI", 1): Resp({"totalCount": 4, "stocks": [
            item("000001", "가", "weird"),                       # 모르는 종류 → ""
            item("000002", "나", "etf", tv=None),                # 거래대금 없음 → 0
            item("000003", "다", "etf", tv="abc"),               # 숫자 아님 → 0
            {"itemCode": "000004", "stockName": "라"},           # 필드 자체가 없음
        ]}),
        ("KOSDAQ", 1): Resp({"totalCount": 0, "stocks": []}),
    }
    out = {s.code: s for s in fetch_naver_symbols(get=fake_get(pages))}
    assert out["000001"].security_type == "" and out["000002"].trading_value == 0
    assert out["000003"].trading_value == 0 and out["000004"].security_type == ""


def test_fetch_skips_rows_without_a_code_or_name_and_duplicate_codes():
    pages = {
        ("KOSPI", 1): Resp({"totalCount": 4, "stocks": [item("005930", "삼성전자"), item("005930", "중복"), item("", "코드없음"), item("000001", "")]}),
        ("KOSDAQ", 1): Resp({"totalCount": 0, "stocks": []}),
    }
    assert [s.code for s in fetch_naver_symbols(get=fake_get(pages))] == ["005930"]


def test_fetch_raises_on_a_bad_response_so_the_old_index_is_kept():
    ok = Resp({"totalCount": 1, "stocks": [item("005930", "삼성전자")]})
    with pytest.raises(RuntimeError):
        fetch_naver_symbols(get=fake_get({("KOSPI", 1): Resp({}, status=500)}))
    with pytest.raises(RuntimeError):  # 한 시장이라도 실패하면 반쪽 색인을 만들지 않는다
        fetch_naver_symbols(get=fake_get({("KOSPI", 1): ok, ("KOSDAQ", 1): Resp({}, status=503)}))
    with pytest.raises(RuntimeError):  # 응답이 비어 있으면(이상한 응답) 실패로 본다
        fetch_naver_symbols(get=fake_get({}))


def test_a_network_exception_propagates_as_failure():
    def boom(*a, **k):
        raise ConnectionError("timeout")

    idx = SymbolIndex(lambda: fetch_naver_symbols(get=boom))
    assert idx.refresh() is False


def test_fetch_stops_even_if_the_total_count_lies():
    # totalCount 가 실제보다 커도 빈 쪽이 나오면 멈춘다(무한 반복 방지)
    pages = {("KOSPI", 1): Resp({"totalCount": 10_000, "stocks": [item("005930", "삼성전자")]}),
             ("KOSDAQ", 1): Resp({"totalCount": 1, "stocks": [item("247540", "에코프로비엠")]})}
    out = fetch_naver_symbols(get=fake_get(pages))
    assert [s.code for s in out] == ["005930", "247540"]


def test_the_shared_instance_uses_the_naver_provider():
    assert isinstance(si.symbol_index, SymbolIndex)
    assert si.symbol_index.ready is False  # 가져오기는 서버가 시작할 때 백그라운드로 한다(import 만으로는 네트워크를 쓰지 않는다)
