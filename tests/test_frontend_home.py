"""헤더의 앱 이름("Alpha Stock")을 누르면 홈(메인 요약 화면)으로 간다.

- PC: 검색 종목·추천·보유 선택을 모두 풀어 오른쪽 패널이 요약이 되고, 왼쪽 목록은 '스윙 추천' 탭(처음 상태)이다.
- 모바일: '요약' 탭으로 가고 맨 위로 스크롤한다.
- 어디서든 진행 중인 검색 응답은 버리고, 열린 검색 패널·매수 시트는 닫는다.
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


# ── 마크업 ──


def test_header_name_is_a_44px_home_button_inside_the_h1():
    s = _html()
    header = s[s.index("<header"):s.index("</header>")]
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", header, re.S).group(1)
    button = re.search(r"<button[^>]*>", h1).group(0)
    assert 'type="button"' in button and 'onclick="goHome()"' in button and 'aria-label="홈으로"' in button
    assert "min-h-[44px]" in button
    assert "Alpha Stock" in h1


# ── 동작 ──


def test_go_home_source_clears_search_sheet_and_requests():
    body = _func("goHome")
    for part in ("++searchReq", "searchStock = null", "searchFromHolding = ''", "clearSearch()", "closeBuyModal()",
                 "initialSelectedIndex(window.innerWidth)", "scrollTo("):
        assert part in body, part
    assert "switchTab(isPcLayout() ? 'recs' : 'summary')" in body


def _harness(pc, tail, wrap_open=False):
    return f"""
let searchReq = 5, searchStock = {{code: '005930'}}, searchFromHolding = '000660';
let expandedCardIndex = 3, expandedHoldingIndex = 2, activeTab = 'holdings';
let currentRecs = [], currentPortfolio = {{holdings: []}};
const calls = [];
const window = {{ innerWidth: {1280 if pc else 375}, scrollTo: o => calls.push('scroll:' + o.top) }};
const document = {{ getElementById: id => id === 'searchWrap' ? {{ classList: {{ contains: () => {str(not wrap_open).lower()} }} }} : null }};
function isPcLayout() {{ return {str(pc).lower()}; }}
function initialSelectedIndex(w) {{ return w >= 1024 ? -1 : 0; }}
function clearSearch() {{ calls.push('clearSearch'); }}
function toggleSearch() {{ calls.push('toggleSearch'); }}
function closeBuyModal() {{ calls.push('closeBuyModal'); }}
function switchTab(tab) {{ activeTab = tab; calls.push('tab:' + tab); }}
function renderRecommendations() {{ calls.push('renderRecs'); }}
function renderHoldings() {{ calls.push('renderHoldings'); }}
{_func('goHome')}
{tail}
"""


def _run(script, tmp_path):
    f = tmp_path / "t.js"
    f.write_text(script, encoding="utf-8")
    out = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


STATE = "console.log(JSON.stringify({ searchReq, searchStock, searchFromHolding, expandedCardIndex, expandedHoldingIndex, activeTab, calls }));"


@needs_node
def test_go_home_on_pc_unselects_everything_and_shows_recs_tab(tmp_path):
    out = _run(_harness(True, "goHome();\n" + STATE), tmp_path)
    assert out["searchReq"] == 6 and out["searchStock"] is None and out["searchFromHolding"] == ""
    assert out["expandedCardIndex"] == -1 and out["expandedHoldingIndex"] == -1  # 종목 미선택 = 오른쪽 패널이 요약
    assert out["activeTab"] == "recs"
    assert "clearSearch" in out["calls"] and "closeBuyModal" in out["calls"]
    assert out["calls"].index("tab:recs") < out["calls"].index("renderRecs")  # 탭을 바꾼 뒤 목록을 다시 그려 선택 표시를 지운다


@needs_node
def test_go_home_on_mobile_opens_summary_tab_and_scrolls_to_top(tmp_path):
    out = _run(_harness(False, "goHome();\n" + STATE), tmp_path)
    assert out["activeTab"] == "summary"
    assert out["expandedCardIndex"] == 0 and out["expandedHoldingIndex"] == 0  # 모바일은 처음 상태(첫 행 펼침)로 둔다
    assert "scroll:0" in out["calls"]
    assert out["searchReq"] == 6 and out["searchStock"] is None


@needs_node
def test_go_home_on_mobile_closes_an_open_search_bar_but_pc_leaves_it(tmp_path):
    mobile = _run(_harness(False, "goHome();\n" + STATE, wrap_open=True), tmp_path)
    assert "toggleSearch" in mobile["calls"]
    pc = _run(_harness(True, "goHome();\n" + STATE, wrap_open=True), tmp_path)
    assert "toggleSearch" not in pc["calls"]  # PC 의 검색창은 항상 보이는 헤더 부분이다
    closed = _run(_harness(False, "goHome();\n" + STATE, wrap_open=False), tmp_path)
    assert "toggleSearch" not in closed["calls"]  # 이미 닫혀 있으면 건드리지 않는다


@needs_node
def test_go_home_when_already_home_only_scrolls_and_is_safe_to_repeat(tmp_path):
    out = _run(_harness(True, "goHome(); goHome();\n" + STATE), tmp_path)
    assert out["activeTab"] == "recs" and out["expandedCardIndex"] == -1 and out["searchReq"] == 7
