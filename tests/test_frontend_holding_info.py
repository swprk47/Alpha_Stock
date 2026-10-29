"""보유 종목에서 종목 정보(점수·AI 진단·차트) 열기: "종목 정보 ›" 알약.

- 모바일: 행을 펼쳤을 때 펼친 카드 맨 위 왼쪽에만(접힌 목록은 그대로). 행 안이 아니라 카드 안이라 "버튼 안의 버튼"이 되지 않는다.
- PC: 보유 상세 헤더 칩 줄 끝(장 상태 태그 뒤).
- 누르면 검색 결과를 눌렀을 때와 같은 화면(모바일은 매수 시트, PC는 오른쪽 패널의 검색 종목 상세).
  PC 에서 그 화면을 닫으면 요약이 아니라 방금 보던 보유 종목 상세로 돌아온다.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "frontend" / "index.html"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node 가 필요합니다")


def _html():
    return HTML.read_text(encoding="utf-8")


def _func(name):
    s = _html()
    m = re.search(rf"(async )?function {name}\(", s)
    assert m, f"function {name} 이 없습니다"
    return s[m.start():s.index("\n    }\n", m.start()) + len("\n    }")]


def _section(tag):
    m = re.search(rf"// <{tag}>\r?\n(.*?)// </{tag}>", _html(), re.S)
    assert m, f"{tag} 구간이 없습니다"
    return m.group(1)


def _node(script, tmp_path):
    f = tmp_path / "t.js"
    f.write_text(script, encoding="utf-8")
    out = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.fixture
def run(tmp_path):
    src = _section("holding-info-logic")
    return lambda expr: _node(src + f"\nconsole.log(JSON.stringify({expr}));\n", tmp_path)


# ── 알약 HTML ──


@needs_node
def test_pill_html_for_a_valid_code(run):
    html = run("holdingInfoPillHtml('011200', 'HMM', 'min-h-[28px]')")
    assert html.startswith("<button") and 'type="button"' in html
    assert 'aria-label="HMM 종목 정보 보기"' in html
    assert "openHoldingInfo('011200')" in html
    assert "종목 정보" in html and "›" in html and "min-h-[28px]" in html
    assert "rounded-full" in html and "text-[13px]" in html  # 알약 모양, 글자 13px 이상


@needs_node
def test_pill_accepts_the_new_alphanumeric_etf_code(run):
    assert "openHoldingInfo('0183J0')" in run("holdingInfoPillHtml('0183J0', 'KODEX', '')")


@needs_node
@pytest.mark.parametrize("code", ["''", "'abc'", "'0123456'", "'011200 '", "'011200\\'); alert(1);//'", "'01120a'", "null", "undefined", "12345", "['011200']"])
def test_pill_is_empty_for_anything_that_is_not_a_stock_code(run, code):
    assert run(f"holdingInfoPillHtml({code}, 'HMM', '')") == ""


@needs_node
def test_pill_escapes_the_name(run):
    html = run("holdingInfoPillHtml('011200', '<img src=x onerror=alert(1)>\"&', '')")
    assert "<img" not in html and "&lt;img" in html and "&quot;" in html and "&amp;" in html


@needs_node
@pytest.mark.parametrize("holdings,code,expected", [
    ("[{code:'005930'},{code:'011200'}]", "'011200'", 1),
    ("[{code:'005930'},{code:'011200'}]", "'000000'", -1),
    ("[]", "'011200'", -1), ("null", "'011200'", -1), ("undefined", "'011200'", -1),
    ("[{code:'005930'}]", "''", -1), ("[{code:'005930'}]", "null", -1), ("'x'", "'011200'", -1),
])
def test_holding_index_by_code(run, holdings, code, expected):
    assert run(f"holdingIndexByCode({holdings}, {code})") == expected


# ── 붙는 곳 ──


def test_mobile_pill_is_the_first_thing_in_the_expanded_card_and_not_in_the_row():
    body = _func("renderHoldings")
    assert body.count("holdingInfoPillHtml(") == 1
    expanded = body[body.index("${isExpanded ? `"):]
    assert "holdingInfoPillHtml(h.code, h.name," in expanded
    assert expanded.index("holdingInfoPillHtml(") < expanded.index("mobileChartBlockHtml(")  # 차트 위, 카드 맨 위
    call = expanded[expanded.index("holdingInfoPillHtml("):expanded.index("holdingInfoPillHtml(") + 200]
    # 보이는 알약은 얇게(30px), 누르는 영역은 보이지 않는 ::before 로 위아래를 넓혀 44px 을 확보한다
    assert "min-h-[30px]" in call and "min-h-[44px]" not in call
    assert "relative" in call and "before:absolute" in call and "before:-inset-y-[7px]" in call and "before:inset-x-0" in call
    row = body[:body.index("${isExpanded ? `")]
    assert "holdingInfoPillHtml" not in row  # 접힌 행(펼침 버튼) 안에는 넣지 않는다
    assert "statusBadge" in expanded[expanded.index("holdingInfoPillHtml("):expanded.index("mobileChartBlockHtml(")]  # 상태 칩과 같은 줄


def test_pc_header_has_the_pill_at_the_end_of_the_chip_line():
    body = _func("holdingDetailHtml")
    assert "holdingInfoPillHtml(h.code, h.name," in body
    assert body.index("marketTagHtml(h.market_state)") < body.index("holdingInfoPillHtml(")
    chip_line = body[body.index("securityTagHtml("):body.index("holdingInfoPillHtml(")]
    assert "</h2>" not in chip_line and "text-2xl" not in chip_line  # 같은 칩 줄 안이다
    assert "min-h-[28px]" in body[body.index("holdingInfoPillHtml("):body.index("holdingInfoPillHtml(") + 120]


@pytest.mark.parametrize("func", ["renderRecommendations", "renderSearchResults", "recDetailHtml", "searchDetailHtml"])
def test_other_places_do_not_get_the_pill(func):
    assert "holdingInfoPillHtml" not in _func(func)


# ── 열기와 돌아오기 ──


def test_open_uses_the_search_flow_and_remembers_where_it_came_from():
    assert "openHoldingInfo(" in _html()
    assert re.search(r"selectSearchResult\(code, '', code\)", _func("openHoldingInfo"))
    sel = _func("selectSearchResult")
    assert re.search(r"async function selectSearchResult\(code, market = '', fromHolding = ''\)", sel)
    assert "searchFromHolding = fromHolding;" in sel  # 검색 결과로 열면 ''(기억 지움)
    assert re.search(r"let searchFromHolding = '';", _html())


def _close_script(tmp_path, origin, holdings, pc="true"):
    stubs = (
        "let searchStock = {x: 1}; let expandedHoldingIndex = -1; let activeTab = 'holdings';\n"
        f"let searchFromHolding = {json.dumps(origin)}; let currentPortfolio = {{holdings: {holdings}}};\n"
        "const calls = [];\n"
        "function renderHoldings() { calls.push('holdings'); }\n"
        "function renderDetailPane() { calls.push('pane'); }\n"
        f"function isPcLayout() {{ return {pc}; }}\n"
    )
    script = (_section("holding-info-logic") + stubs + _func("closeSearchStock")
              + "\ncloseSearchStock();\nconsole.log(JSON.stringify({searchStock, expandedHoldingIndex, searchFromHolding, calls}));\n")
    return _node(script, tmp_path)


@needs_node
def test_closing_a_search_opened_from_a_holding_returns_to_that_holding(tmp_path):
    r = _close_script(tmp_path, "011200", "[{code:'005930'},{code:'011200'}]")
    assert r["searchStock"] is None and r["expandedHoldingIndex"] == 1 and r["searchFromHolding"] == ""
    assert "holdings" in r["calls"]  # 목록을 다시 그려 그 행을 선택하고 패널도 갱신된다


@needs_node
def test_closing_a_normal_search_goes_to_the_summary_as_before(tmp_path):
    r = _close_script(tmp_path, "", "[{code:'005930'},{code:'011200'}]")
    assert r["searchStock"] is None and r["expandedHoldingIndex"] == -1 and r["calls"] == ["pane"]


@needs_node
def test_closing_when_the_holding_is_gone_goes_to_the_summary(tmp_path):
    r = _close_script(tmp_path, "011200", "[{code:'005930'}]")
    assert r["expandedHoldingIndex"] == -1 and r["searchFromHolding"] == "" and r["calls"] == ["pane"]


@needs_node
def test_closing_without_a_portfolio_does_not_crash(tmp_path):
    f = tmp_path / "t.js"
    script = (_section("holding-info-logic")
              + "let searchStock = {x: 1}; let expandedHoldingIndex = -1; let searchFromHolding = '011200'; let currentPortfolio = null;\n"
              + "function renderHoldings() {} function renderDetailPane() {} function isPcLayout() { return true; }\n"
              + _func("closeSearchStock") + "\ncloseSearchStock();\nconsole.log(JSON.stringify({searchStock, expandedHoldingIndex}));\n")
    f.write_text(script, encoding="utf-8")
    out = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == {"searchStock": None, "expandedHoldingIndex": -1}


# ── 시장을 모르면 지어내지 않는다 ──


def test_buy_sheet_does_not_invent_a_market_when_the_stock_has_none():
    # 보유 종목에는 시장(KOSPI/KOSDAQ) 정보가 없다. 시트가 모를 때 'KOSPI' 를 기본값으로 쓰면 코스닥 종목이 틀리게 보인다 → 칩을 숨긴다
    body = _func("openCustomBuyModal")
    assert "|| 'KOSPI'" not in body
    assert re.search(r"classList\.toggle\('hidden', !stockItem\.market\)", body)
