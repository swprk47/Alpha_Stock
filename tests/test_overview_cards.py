"""종목 개요: 네이버 응답 → 카드(소개·기본 정보·보유 자산·비중·뉴스)와 get_overview.

네트워크 없이, 2026-10-30 에 받은 실응답 발췌(tests/fixtures/overview)로 확인한다.
"""
import copy
import json
from datetime import datetime
from pathlib import Path

import pytest

import overview

FIX = Path(__file__).parent / "fixtures" / "overview"
INDUSTRY = "/api/stocks/industry?page=1&pageSize=100"


def fx(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def p_int(code):
    return f"/api/stock/{code}/integration"


def p_fin(code):
    return f"/api/stock/{code}/finance/annual"


def p_etf(code):
    return f"/api/stock/{code}/etfAnalysis"


def p_news(code):
    return f"/api/news/stock/{code}?pageSize=5&page=1"


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class Net:
    """overview.fetch_json 대신 쓰는 가짜 네이버. routes 의 값이 예외면 그 호출만 실패한다."""

    def __init__(self):
        self.routes = {}
        self.calls = []

    def __call__(self, path):
        self.calls.append(path)
        if path not in self.routes:
            raise overview.OverviewFetchError(f"no route {path}")
        value = self.routes[path]
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)

    def count(self, path):
        return self.calls.count(path)


@pytest.fixture
def net(monkeypatch):
    n = Net()
    monkeypatch.setattr(overview, "fetch_json", n)
    return n


def run(code, net, clock=None):
    return overview.get_overview(code, cache=overview.TtlCache(clock=clock or FakeClock()))


def stock_routes(net, code="005930", finance="finance_005930.json"):
    net.routes.update({
        p_int(code): fx("integration_005930.json"),
        p_fin(code): fx(finance),
        INDUSTRY: fx("industry.json"),
        p_news(code): fx("news_005930.json"),
    })


def etf_routes(net, code, etf_fixture):
    net.routes.update({
        p_int(code): fx("integration_069500.json"),
        p_etf(code): fx(etf_fixture),
        p_news(code): fx("news_005930.json"),
    })


# ── 주식 ──


def test_stock_about_has_three_paragraphs_verbatim(net):
    stock_routes(net)
    out = run("005930", net)
    assert out["success"] is True and out["kind"] == "stock" and out["code"] == "005930"
    about = out["about"]
    assert about["status"] == "ok" and about["title"] == "회사 소개" and len(about["paragraphs"]) == 3
    assert about["paragraphs"][1] == ("DX 부문은 TV, 냉장고, 스마트폰을, DS 부문은 DRAM, NAND Flash 등의 반도체를, "
                                      "SDC는 OLED 패널을, Harman은 전장부품 및 오디오 제품을 생산·판매하고 있음.")


def test_preferred_share_null_summary_is_empty_not_error(net):
    stock_routes(net, code="005935", finance="finance_005935.json")
    out = run("005935", net)
    assert out["about"]["status"] == "empty"  # 네이버는 404 가 아니라 200 + null 을 준다


def test_stock_facts_order_values_and_notes(net):
    stock_routes(net)
    facts = run("005930", net)["facts"]
    assert facts["status"] == "ok"
    rows = {i["label"]: i for i in facts["items"]}
    assert [i["label"] for i in facts["items"]] == ["업종", "시가총액", "PER", "PBR", "배당수익률", "외인소진율"]
    assert rows["업종"]["value"] == "반도체와반도체장비"
    assert (rows["시가총액"]["value"], rows["시가총액"]["note"]) == ("1,289조 1,044억", "현재 시세 기준")
    assert (rows["PER"]["value"], rows["PER"]["note"]) == ("9.89배", "2026.06. 실적 기준")
    assert (rows["PBR"]["value"], rows["PBR"]["note"]) == ("2.56배", "2026.06. 실적 기준")
    assert (rows["배당수익률"]["value"], rows["배당수익률"]["note"]) == ("0.76%", "2025.12. 기준")
    assert (rows["외인소진율"]["value"], rows["외인소진율"]["note"]) == ("46.17%", "")


def test_unknown_industry_code_and_missing_values_show_dash(net):
    stock_routes(net)
    integ = fx("integration_005930.json")
    integ["industryCode"] = "99999"
    integ["totalInfos"] = [t for t in integ["totalInfos"] if t["code"] != "per"]
    net.routes[p_int("005930")] = integ
    rows = {i["label"]: i for i in run("005930", net)["facts"]["items"]}
    assert rows["업종"]["value"] == "—" and rows["PER"]["value"] == "—" and rows["PER"]["note"] == ""


def test_industry_table_failure_only_blanks_the_industry_cell(net):
    stock_routes(net)
    net.routes[INDUSTRY] = overview.OverviewFetchError("down")
    out = run("005930", net)
    rows = {i["label"]: i for i in out["facts"]["items"]}
    assert out["facts"]["status"] == "ok" and rows["업종"]["value"] == "—" and rows["시가총액"]["value"] == "1,289조 1,044억"


def test_stock_has_no_etf_cards_and_does_not_call_etf_analysis(net):
    stock_routes(net)
    out = run("005930", net)
    assert out["holdings"]["status"] == "empty" and out["weights"]["status"] == "empty"
    assert p_etf("005930") not in net.calls


# ── ETF ──


def test_etf_domestic(net):
    etf_routes(net, "069500", "etf_069500.json")
    out = run("069500", net)
    assert out["kind"] == "etf" and p_fin("069500") not in net.calls
    assert out["about"]["title"] == "이 ETF는" and out["about"]["status"] == "ok"
    rows = {i["label"]: i["value"] for i in out["facts"]["items"]}
    assert rows == {"기초지수": rows["기초지수"], "운용사": "삼성자산운용", "총보수": "0.15%", "상장일": "2002.10.14"}
    assert [i["label"] for i in out["facts"]["items"]] == ["기초지수", "운용사", "총보수", "상장일"]
    holds = out["holdings"]["items"]
    assert len(holds) == 10 and holds[0]["weight"] == 34.19 and holds[0]["count"] == "6,969"
    cards = out["weights"]["cards"]
    assert [c["key"] for c in cards] == ["sector"]  # 국가는 한국이라, 자산은 주식 비중이 높아서 숨김
    assert [i["label"] for i in cards[0]["items"]] == ["IT", "산업재", "금융", "경기소비재", "커뮤니케이션"]
    assert cards[0]["items"][0]["weight"] == 66.12 and cards[0]["total"] == 99.05
    assert cards[0]["title"] == "업종별 비중"
    # 앱이 더해서 만든 값은 어디에도 없다(네이버가 준 합계만 있다)
    assert "total_top10" not in json.dumps(out) and "rest" not in out["holdings"]


def test_etf_overseas_names_only_and_sector_above_country(net):
    etf_routes(net, "360750", "etf_360750.json")
    out = run("360750", net)
    assert all(h["weight"] is None for h in out["holdings"]["items"])
    assert out["holdings"]["items"][0]["name"] == "NVIDIA CORP" and out["holdings"]["items"][0]["count"] == "348"
    assert [c["key"] for c in out["weights"]["cards"]] == ["sector", "country"]
    country = out["weights"]["cards"][1]
    assert country["title"] == "국가별 비중" and country["items"][0] == {"label": "미국", "weight": 94.73}
    rows = {i["label"]: i["value"] for i in out["facts"]["items"]}
    assert rows["총보수"] == "0.0068%"
    paragraphs = out["about"]["paragraphs"]
    assert len(paragraphs) == 2 and all("<" not in p and ">" not in p for p in paragraphs)


def test_etf_bond_hides_sector_and_shows_asset(net):
    etf_routes(net, "153130", "etf_153130.json")
    out = run("153130", net)
    cards = out["weights"]["cards"]
    assert [c["key"] for c in cards] == ["asset"]
    assert [i["label"] for i in cards[0]["items"]] == ["채권", "현금"]
    assert out["holdings"]["items"][0]["weight"] is None and out["holdings"]["items"][0]["count"] == "-"
    assert len(out["about"]["paragraphs"]) == 1 and len(out["about"]["paragraphs"][0]) > 500  # 긴 설명도 자르지 않는다


def test_unknown_codes_keep_raw_label(net):
    etf = fx("etf_069500.json")
    etf["sectorPortfolioList"] = [{"detailTypeCode": "SPACE", "weight": 40.0}, {"detailTypeCode": "IT", "weight": 30.0}]
    net.routes.update({p_int("069500"): fx("integration_069500.json"), p_etf("069500"): etf, p_news("069500"): fx("news_005930.json")})
    items = run("069500", net)["weights"]["cards"][0]["items"]
    assert [i["label"] for i in items] == ["SPACE", "IT"]


def test_zero_weights_are_dropped_and_at_most_five_shown(net):
    etf = fx("etf_069500.json")
    etf["sectorPortfolioList"] = [{"detailTypeCode": c, "weight": w} for c, w in
                                  [("IT", 30.0), ("FINANCIALS", 20.0), ("MATERIALS", 10.0), ("ENERGY", 9.0), ("UTILITIES", 8.0), ("HEALTHCARE", 7.0), ("REAL_ESTATE", 0.0)]]
    net.routes.update({p_int("069500"): fx("integration_069500.json"), p_etf("069500"): etf, p_news("069500"): fx("news_005930.json")})
    items = run("069500", net)["weights"]["cards"][0]["items"]
    assert len(items) == 5 and all(i["weight"] > 0 for i in items)


def test_etf_without_any_displayable_weights_is_empty(net):
    etf = fx("etf_069500.json")
    etf["sectorPortfolioList"] = []
    etf["countryPortfolioList"] = []
    etf["assetPortfolioList"] = []
    net.routes.update({p_int("069500"): fx("integration_069500.json"), p_etf("069500"): etf, p_news("069500"): fx("news_005930.json")})
    assert run("069500", net)["weights"]["status"] == "empty"


# ── 뉴스 ──


def test_news_more_link_whitelist_time_and_max_five(net):
    stock_routes(net)
    news = fx("news_005930.json")
    news[0]["total"] = 4
    news[1]["items"][0]["mobileNewsUrl"] = "https://evil.example.com/x"
    news[2]["items"][0]["title"] = "a&quot;b"
    news[2]["items"][0]["titleFull"] = "a&quot;b 전체"
    news += copy.deepcopy(news[:3])  # 5개를 넘겨도 5개까지
    net.routes[p_news("005930")] = news
    items = run("005930", net)["news"]["items"]
    assert len(items) <= 5
    assert items[0]["more"] == 3 and items[0]["time"] == "10.30 23:05"
    assert all(i["url"].startswith("https://n.news.naver.com/") for i in items)  # 허용되지 않는 주소의 기사는 빠진다
    assert not any(i["url"] == "https://evil.example.com/x" for i in items)
    assert any(i["title"] == 'a"b 전체' for i in items)  # 엔티티는 글자로, titleFull 을 쓴다


def test_news_empty_when_no_article_survives(net):
    stock_routes(net)
    net.routes[p_news("005930")] = []
    assert run("005930", net)["news"]["status"] == "empty"


# ── ETN·종류 불명·실패 격리 ──


def test_etn_and_unknown_kind_only_try_news(net):
    integ = fx("integration_005930.json")
    integ["stockEndType"] = "etn"
    net.routes.update({p_int("500001"): integ, p_news("500001"): fx("news_005930.json")})
    out = run("500001", net)
    assert out["kind"] == "etn"
    assert out["about"]["status"] == "empty" and out["facts"]["status"] == "empty"
    assert out["holdings"]["status"] == "empty" and out["weights"]["status"] == "empty"
    assert out["news"]["status"] == "ok"
    assert p_fin("500001") not in net.calls and p_etf("500001") not in net.calls
    integ["stockEndType"] = "weird"
    net.routes[p_int("500002")] = integ
    net.routes[p_news("500002")] = fx("news_005930.json")
    assert run("500002", net)["kind"] == ""


def test_integration_failure_marks_cards_error_but_news_still_loads(net):
    net.routes.update({p_int("005930"): overview.OverviewFetchError("down"), p_news("005930"): fx("news_005930.json")})
    out = run("005930", net)
    assert out["kind"] == ""
    for card in ("about", "facts", "holdings", "weights"):
        assert out[card]["status"] == "error", card
    assert out["news"]["status"] == "ok"


def test_one_source_failure_is_isolated(net):
    stock_routes(net)
    net.routes[p_fin("005930")] = overview.OverviewFetchError("down")
    out = run("005930", net)
    assert out["about"]["status"] == "error" and out["about"]["title"] == "회사 소개"
    assert out["facts"]["status"] == "ok" and out["news"]["status"] == "ok"


def test_news_failure_only_affects_news(net):
    etf_routes(net, "069500", "etf_069500.json")
    net.routes[p_news("069500")] = overview.OverviewFetchError("down")
    out = run("069500", net)
    assert out["news"]["status"] == "error" and out["about"]["status"] == "ok" and out["holdings"]["status"] == "ok"


def test_all_fail_returns_all_cards_error(net):
    out = run("005930", net)  # 가짜 네이버에 길이 없어 모든 호출이 실패한다
    assert out["success"] is True and out["kind"] == "" and out["fetched_at"] == ""
    for card in ("about", "facts", "holdings", "weights", "news"):
        assert out[card]["status"] == "error", card


def test_malformed_source_is_error_not_guess(net, capsys):
    etf_routes(net, "069500", "etf_069500.json")
    bad = fx("etf_069500.json")
    bad["etfSummary"] = ["not", "a", "string"]
    bad["etfTop10MajorConstituentAssets"] = "oops"
    bad["sectorPortfolioList"] = {"nope": 1}
    net.routes[p_etf("069500")] = bad
    out = run("069500", net)
    assert out["holdings"]["status"] == "error" and out["weights"]["status"] == "error"
    assert out["about"]["status"] in ("empty", "error")  # 글자가 아니면 값을 채우지 않는다
    assert out["about"].get("paragraphs", []) == []
    assert "069500" in capsys.readouterr().out  # 로그에 코드가 남는다


def test_malformed_integration_is_error(net):
    net.routes.update({p_int("005930"): ["not", "a", "dict"], p_news("005930"): fx("news_005930.json")})
    out = run("005930", net)
    assert out["kind"] == "" and out["about"]["status"] == "error" and out["news"]["status"] == "ok"


# ── 시각·캐시 ──


def test_fetched_at_is_the_oldest_source_time(net):
    clock = FakeClock(1000.0)
    cache = overview.TtlCache(clock=clock)
    stock_routes(net)
    net.routes[p_news("005930")] = overview.OverviewFetchError("down")
    overview.get_overview("005930", cache=cache)  # t=1000: integration·finance·industry 를 받는다
    net.routes[p_news("005930")] = fx("news_005930.json")
    clock.now = 1030.0
    overview.get_overview("005930", cache=cache)  # 뉴스는 1030 에 받는다
    clock.now = 1070.0
    out = overview.get_overview("005930", cache=cache)  # integration 은 1070 에 다시 받지만 finance·industry 는 1000 의 것
    assert out["fetched_at"] == datetime.fromtimestamp(1000.0).strftime("%Y-%m-%d %H:%M:%S")


@pytest.mark.parametrize("path_of,code,ttl,fixtures", [
    (p_int, "005930", 60, None),
    (p_fin, "005930", 6 * 3600, None),
    (p_news, "005930", 300, None),
    (lambda code: INDUSTRY, "005930", 24 * 3600, None),
])
def test_cache_ttls_applied_per_source(net, path_of, code, ttl, fixtures):
    stock_routes(net)
    clock = FakeClock(1000.0)
    cache = overview.TtlCache(clock=clock)
    path = path_of(code)
    overview.get_overview(code, cache=cache)
    assert net.count(path) == 1
    clock.now = 1000.0 + ttl - 1
    overview.get_overview(code, cache=cache)
    assert net.count(path) == 1  # TTL 직전: 다시 받지 않는다
    clock.now = 1000.0 + ttl + 1
    overview.get_overview(code, cache=cache)
    assert net.count(path) == 2  # TTL 직후: 다시 받는다


def test_etf_analysis_ttl_is_one_hour(net):
    etf_routes(net, "069500", "etf_069500.json")
    clock = FakeClock(1000.0)
    cache = overview.TtlCache(clock=clock)
    overview.get_overview("069500", cache=cache)
    clock.now = 1000.0 + 3599
    overview.get_overview("069500", cache=cache)
    assert net.count(p_etf("069500")) == 1
    clock.now = 1000.0 + 3601
    overview.get_overview("069500", cache=cache)
    assert net.count(p_etf("069500")) == 2


def test_failures_are_not_cached(net):
    stock_routes(net)
    net.routes[p_fin("005930")] = overview.OverviewFetchError("down")
    cache = overview.TtlCache(clock=FakeClock())
    assert overview.get_overview("005930", cache=cache)["about"]["status"] == "error"
    net.routes[p_fin("005930")] = fx("finance_005930.json")
    assert overview.get_overview("005930", cache=cache)["about"]["status"] == "ok"  # 바로 다시 시도한다


def test_source_url_is_empty_or_naver_https(net):
    stock_routes(net)
    url = run("005930", net)["source_url"]
    assert url == "" or url.startswith("https://m.stock.naver.com/")


def test_source_url_points_to_the_naver_stock_page(net):
    # 2026-10-30 에 주식(005930)·ETF(069500, 0183J0) 모두 이 주소가 200 으로 열리는 것을 확인했다
    stock_routes(net)
    assert run("005930", net)["source_url"] == "https://m.stock.naver.com/domestic/stock/005930/total"
    etf_routes(net, "0183J0", "etf_069500.json")
    assert run("0183J0", net)["source_url"] == "https://m.stock.naver.com/domestic/stock/0183J0/total"
