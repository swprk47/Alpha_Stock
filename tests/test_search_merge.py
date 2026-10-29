"""search_stocks: 종목 색인(이름 가운데 글자) + 네이버 자동완성(색인에 없는 신규 상장 등)을 합친다.

- 후보는 색인 결과가 먼저, 자동완성 결과 중 색인에 없던 것이 뒤에 온다(코드 기준 중복 제거, 최대 6개).
- 가격·등락·로고·종류는 후보마다 **실시간 시세**로 채운다(색인 값은 하루 묵은 것이라 쓰지 않는다).
- 자동완성 호출은 params 로 보낸다(예전에는 검색어를 주소에 그대로 끼워 "S&P500" 의 &가 주소를 깨뜨렸다).
- 한쪽이 실패해도 다른 쪽 결과는 돌려준다. 이 파일은 네트워크 없이 검증한다.
"""
import pytest

import market_data as md
from symbol_index import Symbol, SymbolIndex

BASE = "https://ssl.pstatic.net/imgstock/fn/real/logo/png/"


def S(code, name, market="KOSPI", kind="stock", tv=0):
    return Symbol(code, name, market, kind, tv)


class Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload


class Env:
    """색인·자동완성·시세를 가짜로 바꾸고 호출을 기록한다."""

    def __init__(self, monkeypatch):
        self.mp = monkeypatch
        self.ac_calls = []
        self.quote_calls = []
        self.ac_items = []
        self.ac_status = 200
        self.ac_raises = False
        self.quotes = {}
        self.fetches = 0
        self.index = SymbolIndex(self._fetch)
        monkeypatch.setattr(md, "symbol_index", self.index)
        monkeypatch.setattr(md.requests, "get", self._get)
        monkeypatch.setattr(md, "get_realtime_stock_info", self._quote)

    def _fetch(self):
        self.fetches += 1
        return self.symbols

    def build(self, symbols):
        self.symbols = symbols
        assert self.index.refresh() is True
        self.fetches = 0  # 검색이 색인을 다시 받지 않는지 보려고 센다

    def _get(self, url, params=None, headers=None, timeout=None, **kw):
        self.ac_calls.append((url, dict(params or {})))
        if self.ac_raises:
            raise ConnectionError("timeout")
        return Resp({"items": self.ac_items}, status=self.ac_status)

    def _quote(self, code):
        self.quote_calls.append(code)
        return self.quotes.get(code)


@pytest.fixture
def env(monkeypatch):
    return Env(monkeypatch)


def codes(results):
    return [r["code"] for r in results]


# ── 색인 결과 ──


def test_index_results_are_returned_with_live_quote_fields(env):
    env.build([S("005930", "삼성전자", tv=999), S("360750", "TIGER 미국S&P500", kind="etf", tv=5)])
    env.quotes = {
        "005930": {"current_price": 245_000, "change_rate": 10.36, "logo_url": BASE + "stock/Stock005930.png", "security_type": "stock"},
        "360750": {"current_price": 25_655, "change_rate": -0.21, "logo_url": BASE + "etf/StockKRETFTIGER.png", "security_type": "etf"},
    }
    r = env_search(env, "미국")
    assert codes(r) == ["360750"]
    assert r[0]["name"] == "TIGER 미국S&P500" and r[0]["market"] == "KOSPI"
    assert r[0]["current_price"] == 25_655 and r[0]["change_rate"] == -0.21  # 색인이 아니라 시세 값
    assert r[0]["logo_url"] == BASE + "etf/StockKRETFTIGER.png" and r[0]["security_type"] == "etf"
    assert r[0]["budget_status"] == "FIT_SPLIT"


def env_search(env, q):
    return md.search_stocks(q)


def test_middle_of_the_name_is_found_even_when_the_autocomplete_finds_nothing(env):
    env.build([S("005930", "삼성전자")])
    env.quotes = {"005930": {"current_price": 245_000, "change_rate": 1.0}}
    assert codes(env_search(env, "성전자")) == ["005930"]


def test_index_order_is_kept(env):
    env.build([S("000001", "에이다", tv=1), S("000002", "에이나", tv=500), S("000003", "에이가", tv=100)])
    assert codes(env_search(env, "에이")) == ["000002", "000003", "000001"]  # 거래대금 큰 순


def test_quote_failure_still_lists_the_stock_with_safe_defaults(env):
    env.build([S("035720", "카카오", market="KOSDAQ")])
    r = env_search(env, "카카오")[0]
    assert r["current_price"] == 0 and r["change_rate"] == 0.0
    assert r["security_type"] == "" and r["market"] == "KOSDAQ"
    assert r["logo_url"] == BASE + "stock/Stock035720.png"  # 시세가 없으면 코드로 만든 주소


# ── 자동완성과 합치기 ──


def test_autocomplete_only_candidates_are_appended_after_the_index_without_duplicates(env):
    env.build([S("000001", "에이다"), S("000002", "에이나")])
    env.ac_items = [
        {"code": "000002", "name": "에이나", "typeCode": "KOSPI"},      # 색인에도 있음 → 한 번만
        {"code": "999999", "name": "에이신규", "typeCode": "KOSDAQ"},   # 색인에 없음(신규 상장 등) → 뒤에
    ]
    r = env_search(env, "에이")
    assert codes(r) == ["000001", "000002", "999999"]
    assert r[2]["market"] == "KOSDAQ"  # 색인에 없던 후보의 시장은 자동완성의 typeCode


def test_total_is_capped_at_six_with_the_index_first(env):
    env.build([S(f"00000{i}", f"에이{i}", tv=100 - i) for i in range(5)])
    env.ac_items = [{"code": f"99999{i}", "name": f"신규{i}", "typeCode": "KOSPI"} for i in range(5)]
    r = env_search(env, "에이")
    assert len(r) == 6 and codes(r)[:5] == [f"00000{i}" for i in range(5)] and codes(r)[5] == "999990"
    assert len(env.quote_calls) == 6  # 보이지 않는 후보의 시세는 받지 않는다


def test_a_full_index_result_leaves_no_room_for_autocomplete_extras(env):
    env.build([S(f"00000{i}", f"에이{i}") for i in range(8)])
    env.ac_items = [{"code": "999999", "name": "신규", "typeCode": "KOSPI"}]
    assert "999999" not in codes(env_search(env, "에이"))


def test_when_the_index_is_not_built_it_behaves_like_before(env):
    # 서버가 막 시작해 색인이 아직 없는 몇 초 동안(또는 목록을 못 받았을 때)은 자동완성만 쓴다
    env.ac_items = [{"code": "005930", "name": "삼성전자", "typeCode": "KOSPI"}]
    env.quotes = {"005930": {"current_price": 245_000, "change_rate": 1.0}}
    assert codes(env_search(env, "삼성")) == ["005930"]
    assert env.index.ready is False


def test_autocomplete_failure_returns_the_index_results(env):
    env.build([S("005930", "삼성전자")])
    env.ac_raises = True
    assert codes(env_search(env, "성전자")) == ["005930"]
    env.ac_raises = False
    env.ac_status = 500
    assert codes(env_search(env, "성전자")) == ["005930"]


def test_both_empty_returns_an_empty_list(env):
    env.build([S("005930", "삼성전자")])
    assert env_search(env, "존재하지않는종목") == []
    assert env_search(env, "") == [] and env_search(env, "   ") == [] and env_search(env, None) == []


def test_empty_query_makes_no_network_calls(env):
    env.build([S("005930", "삼성전자")])
    env_search(env, "  ")
    assert env.ac_calls == [] and env.quote_calls == []


def test_autocomplete_rows_without_a_code_are_skipped(env):
    env.ac_items = [{"name": "코드없음"}, {"code": "", "name": "빈코드"}, {"code": "005930", "name": "삼성전자", "typeCode": "KOSPI"}]
    assert codes(env_search(env, "삼성")) == ["005930"]
    assert env.quote_calls == ["005930"]


# ── 자동완성 요청 ──


def test_autocomplete_query_goes_in_params_so_ampersand_survives(env):
    env.build([S("360750", "TIGER 미국S&P500", kind="etf")])
    env_search(env, "S&P500")
    url, params = env.ac_calls[0]
    assert url == "https://ac.stock.naver.com/ac"  # 검색어가 주소 안에 없다
    assert params == {"q": "S&P500", "target": "stock"}


@pytest.mark.parametrize("q", ["A#B", "a?b=c", "삼성 전자", "x&target=etf"])
def test_odd_queries_cannot_alter_the_request(env, q):
    env_search(env, q)
    url, params = env.ac_calls[0]
    assert url == "https://ac.stock.naver.com/ac" and params["q"] == q.strip() and params["target"] == "stock"


def test_long_query_is_trimmed_for_both_the_index_and_the_autocomplete(env):
    env.build([S("005930", "삼성전자")])
    env_search(env, "삼" * 200)
    assert len(env.ac_calls[0][1]["q"]) == 30


# ── 책임 분리 ──


def test_search_never_refreshes_the_index_itself(env):
    # 갱신 시작은 서버 라우트의 일(ensure_fresh). search_stocks 는 읽기만 해서 테스트나 호출자가 몰래 네트워크를 쓰지 않는다
    env.build([S("005930", "삼성전자")])
    env_search(env, "성전자")
    assert env.fetches == 0
