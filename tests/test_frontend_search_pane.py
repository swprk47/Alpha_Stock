"""검색 결과를 PC 오른쪽 패널에 바로 띄우기 검증.

PC(1024px 이상)에서 검색 결과를 누르면 오른쪽 패널에 그 종목의 상세가 나오고, 매수 버튼을 누를 때만
기존 매수 모달이 열린다. 모바일은 지금처럼 모달만 연다. 주문·수량·수수료 계산 코드는 바뀌지 않는다.
순수 함수는 index.html 의 `// <pc-logic>` 구간을 node 로 그대로 실행해 확인하고, 구조는 문자열로 확인한다.
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
    """index.html 안의 `function name(` 본문(다음 들여쓰기 4칸 닫는 중괄호까지)."""
    s = _html()
    m = re.search(rf"(async )?function {name}\(", s)
    assert m, f"function {name} 이 없습니다"
    return s[m.start():s.index("\n    }\n", m.start())]


def _logic_source():
    m = re.search(r"// <pc-logic>\r?\n(.*?)// </pc-logic>", _html(), re.S)
    assert m, "index.html 에 pc-logic 구간이 없습니다"
    return m.group(1)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    d = tmp_path_factory.mktemp("searchjs")
    src = _logic_source()

    def _run(expr):
        f = d / "t.js"
        f.write_text(src + "\nconsole.log(JSON.stringify(" + expr + "));\n", encoding="utf-8")
        out = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    return _run


RECS = "[{code:'A',name:'가'},{code:'B',name:'나'}]"
HOLDS = "[{code:'H',name:'보유'}]"
STOCK = "{code:'161390',name:'한국타이어',current_price:58600}"


# ---- 오른쪽 패널 모드: 검색으로 고른 종목이 있으면 그것이 우선 ----
@needs_node
def test_search_stock_shows_in_the_pane(run):
    st = run(f"detailPaneState('recs', -1, -1, {RECS}, {HOLDS}, {STOCK})")
    assert st["mode"] == "search" and st["item"]["code"] == "161390"


@needs_node
def test_search_stock_wins_over_a_list_selection_and_any_tab(run):
    # 목록 선택은 선택 해제로 맞추지만, 상태 판별 자체도 검색 종목이 우선이어야 어긋나지 않는다
    assert run(f"detailPaneState('recs', 1, -1, {RECS}, {HOLDS}, {STOCK})")["mode"] == "search"
    assert run(f"detailPaneState('holdings', -1, 0, {RECS}, {HOLDS}, {STOCK})")["mode"] == "search"


@needs_node
def test_without_search_stock_the_pane_works_as_before(run):
    assert run(f"detailPaneState('recs', -1, -1, {RECS}, {HOLDS})") == {"mode": "summary"}
    assert run(f"detailPaneState('recs', -1, -1, {RECS}, {HOLDS}, null)") == {"mode": "summary"}
    assert run(f"detailPaneState('recs', 1, -1, {RECS}, {HOLDS}, null)")["mode"] == "rec"
    assert run(f"detailPaneState('holdings', 1, 0, {RECS}, {HOLDS}, null)")["mode"] == "holding"


# ---- 목표가·손절가: 매수 모달이 보유 종목에 저장하는 값과 같은 식(반올림) ----
@needs_node
def test_swing_targets_use_the_same_rounding_as_the_buy_modal(run):
    # 22,500원: 서버 추천은 내림(23,962)이지만 모달·보유 종목에 저장되는 값은 반올림(23,963)
    assert run("swingTargets(22500)") == {
        "target": 23963, "stop": 21825, "targetPct": 6.5, "stopPct": -3.0, "ratio": 2.17, "holdDays": 5,
    }
    t = run("swingTargets(58600)")
    assert t["target"] == round(58600 * 1.065) and t["stop"] == round(58600 * 0.97)


def test_swing_targets_match_the_formula_the_order_stores():
    # 주문(모바일 시트·PC 패널 모두 executeInlineBuy)이 저장하는 목표가·손절가는 swingTargets 의 식이다
    body = _func("executeInlineBuy")
    assert "swingTargets(item.current_price)" in body
    assert "target_price: tg.target" in body and "stop_loss_price: tg.stop" in body and "max_hold_days: tg.holdDays" in body
    logic = _logic_source()
    assert "Math.round(price * 1.065)" in logic and "Math.round(price * 0.97)" in logic


# ---- 검색 결과 클릭: PC 는 패널, 모바일은 모달 ----
def test_search_result_passes_the_market_along():
    # /api/stock/{code} 응답에는 market 이 없어 모달이 KOSPI 로 고정 표시하던 문제를 고친다
    s = _html()
    assert re.search(r"selectSearchResult\('\$\{item\.code\}', '\$\{[^}]*item\.market[^}]*\}'\)", s)
    assert "market" in _func("selectSearchResult")
    assert "replace(/[^A-Za-z]/g" in _func("renderSearchResults")  # 속성 안에 넣는 값은 영문만


def test_pc_search_selection_goes_to_the_pane_not_the_modal():
    body = _func("selectSearchResult")
    assert "isPcLayout()" in body
    assert "searchStock = " in body
    assert "openCustomBuyModal(" in body  # 모바일 경로는 지금처럼 모달


def test_search_selection_clears_the_list_selection():
    body = _func("selectSearchResult")
    assert "expandedCardIndex = expandedHoldingIndex = -1" in body
    assert "renderRecommendations(" in body and "renderHoldings(" in body


def test_stale_search_responses_are_ignored():
    # 결과를 연달아 누르면 응답이 뒤바뀌어 도착할 수 있다
    body = _func("selectSearchResult")
    assert "searchReq" in body


def test_list_clicks_and_tab_switch_clear_the_search_stock():
    for name in ("toggleAccordion", "toggleHolding", "switchTab"):
        assert "searchStock = null" in _func(name), name


def test_pane_can_be_closed():
    assert "searchStock = null" in _func("closeSearchStock")
    assert "renderDetailPane()" in _func("closeSearchStock")
    assert 'aria-label="검색 종목 닫기"' in _func("searchDetailHtml")


# ---- 패널 내용 ----
def test_pane_dispatches_search_mode():
    body = _func("renderDetailPane")
    assert "searchDetailHtml(" in body
    assert "st.mode === 'search'" in body


def test_search_detail_has_the_same_parts_as_the_recommendation_detail():
    body = _func("searchDetailHtml")
    for needed in ("pcChartPanel(", "recAiHtml(", "swingTargets(", "statCell(", "ibBoxHtml("):
        assert needed in body, needed
    assert "sizing" not in body  # 검색 응답에는 sizing 이 없다(권장 수량·예상 수익은 만들지 않는다)


def test_search_detail_says_when_the_price_was_fetched():
    # 패널은 조회한 시점의 시세를 그대로 보여 주므로 몇 시 기준인지 알린다(체결가는 서버 실시간 시세로만 정해진다)
    assert "기준" in _func("searchDetailHtml")
    assert "fetchedAt" in _func("selectSearchResult")


def test_fetched_time_uses_the_same_hh_mm_ss_form_as_the_list_label():
    # 추천 목록의 "13:16:36 갱신"과 같은 형식. toLocaleTimeString('ko-KR')은 "14시 33분 50초"로 나온다
    body = _func("selectSearchResult")
    assert "toTimeString().slice(0, 8)" in body
    assert "toLocaleTimeString" not in body


def test_pc_search_dropdown_is_wide_enough_for_stock_names():
    # PC 검색창은 300px 라 종목명이 "카카오뱅/크"처럼 끊긴다. 오른쪽 끝을 맞춘 채 왼쪽으로 넓힌다
    s = _html()
    i = s.index('id="searchDropdown"')
    tag = s[s.rfind("<", 0, i):s.index(">", i) + 1]
    assert "lg:w-[400px]" in tag and "lg:left-auto" in tag


def test_search_detail_shows_a_skeleton_while_loading():
    body = _func("searchDetailHtml")
    assert "loading" in body and 'class="sk' in body


def test_pc_search_detail_buys_inline_and_mobile_still_opens_the_modal():
    assert "ibBoxHtml(stock)" in _func("searchDetailHtml")  # PC: 상세 안의 인라인 패널(로딩 중에는 스켈레톤이라 패널이 없다)
    assert "openCustomBuyModal(stock)" in _func("selectSearchResult")  # 모바일: 기존 매수 모달


def test_pc_chart_is_drawn_for_the_search_stock():
    assert "drawPcChart(" in _func("renderDetailPane")
    body = _func("renderDetailPane")
    assert body.count("drawPcChart(") >= 3  # rec, holding, search


def test_order_code_is_untouched_by_this_feature():
    # 주문 실행·수량·총액 계산 함수에 검색 패널 상태가 끼어들지 않는다
    for name in ("executeInlineBuy",):
        assert "searchStock" not in _func(name), name
