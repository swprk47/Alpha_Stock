"""UI 개편 단계 3(PC 2열 레이아웃) 검증: 1024px 이상 헤더·2열·행 선택·오른쪽 상세 패널.

순수 함수는 index.html 의 `// <pc-logic>` 구간을 node 로 그대로 실행해 확인하고,
화면 구조는 문자열로 확인한다. 주문·수량 로직은 이 단계에서 바뀌지 않는다
(PC 에서도 매수는 기존 매수 모달, 전량 매도는 기존 executeSell 을 쓴다).
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


def _between(s, start, end):
    i = s.index(start)
    return s[i:s.index(end, i)]


def _func(name):
    """index.html 안의 `function name` 본문(다음 들여쓰기 4칸 닫는 중괄호까지)."""
    s = _html()
    i = s.index(f"function {name}(")  # 괄호까지: renderHoldings 가 renderHoldingsLoading 과 섞이지 않게
    return s[i:s.index("\n    }\n", i)]


def _tag(s, needle):
    """needle 을 포함하는 여는 태그 전체."""
    i = s.index(needle)
    start = s.rfind("<", 0, i)
    return s[start:s.index(">", i) + 1]


def _logic_source():
    m = re.search(r"// <pc-logic>\r?\n(.*?)// </pc-logic>", _html(), re.S)
    assert m, "index.html 에 pc-logic 구간이 없습니다"
    return m.group(1)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    d = tmp_path_factory.mktemp("pcjs")
    src = _logic_source()

    def _run(expr):
        f = d / "t.js"
        f.write_text(src + "\nconsole.log(JSON.stringify(" + expr + "));\n", encoding="utf-8")
        out = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    return _run


# ---- 레이아웃 판별: 1024px 이상이 PC ----
@needs_node
def test_pc_layout_starts_at_1024(run):
    assert run("isPcWidth(1023)") is False
    assert run("isPcWidth(1024)") is True
    assert run("isPcWidth(1280)") is True
    assert run("isPcWidth(375)") is False


@needs_node
def test_pc_starts_with_nothing_selected_mobile_keeps_first_row_open(run):
    # PC 첫 화면은 요약(종목 미선택). 모바일은 지금처럼 첫 행을 펼친다.
    assert run("initialSelectedIndex(1280)") == -1
    assert run("initialSelectedIndex(1024)") == -1
    assert run("initialSelectedIndex(375)") == 0


# ---- 오른쪽 패널 모드: 미선택 = 요약, 선택 = 상세 ----
RECS = "[{code:'A',name:'가'},{code:'B',name:'나'}]"
HOLDS = "[{code:'H',name:'보유'}]"


@needs_node
def test_detail_pane_summary_when_nothing_selected(run):
    assert run(f"detailPaneState('recs', -1, -1, {RECS}, {HOLDS})") == {"mode": "summary"}


@needs_node
def test_detail_pane_shows_selected_recommendation(run):
    st = run(f"detailPaneState('recs', 1, -1, {RECS}, {HOLDS})")
    assert st["mode"] == "rec" and st["idx"] == 1 and st["item"]["code"] == "B"


@needs_node
def test_detail_pane_shows_selected_holding_on_holdings_tab(run):
    st = run(f"detailPaneState('holdings', 1, 0, {RECS}, {HOLDS})")
    assert st["mode"] == "holding" and st["idx"] == 0 and st["item"]["code"] == "H"


@needs_node
def test_detail_pane_uses_only_the_active_tab_selection(run):
    # 보유 탭인데 추천 탭의 선택(1)만 있고 보유 선택이 없으면 요약
    assert run(f"detailPaneState('holdings', 1, -1, {RECS}, {HOLDS})") == {"mode": "summary"}


@needs_node
def test_detail_pane_summary_for_out_of_range_or_missing_lists(run):
    assert run(f"detailPaneState('recs', 5, -1, {RECS}, {HOLDS})") == {"mode": "summary"}
    assert run("detailPaneState('recs', 0, -1, [], [])") == {"mode": "summary"}
    assert run("detailPaneState('recs', 0, -1, null, undefined)") == {"mode": "summary"}


# ---- 헤더: 64px, 검색창 상시, 알림 버튼 ----
def test_header_is_64px_on_pc_and_has_notification_button():
    s = _html()
    header = _between(s, "<header", "</header>")
    assert "lg:h-16" in _tag(s, "<header")
    assert 'id="notifHeaderBtn"' in header
    bell = _tag(header, 'id="notifHeaderBtn"')
    assert "hidden" in bell.split('class="')[1].split('"')[0].split() and "lg:flex" in bell
    assert "toggleNotificationSetting()" in bell
    assert 'aria-label="알림 설정"' in bell


def test_search_always_visible_on_pc_and_toggle_button_hidden():
    s = _html()
    wrap = re.search(r'<div id="searchWrap" class="([^"]*)"', s).group(1)
    assert "lg:!block" in wrap
    assert "lg:hidden" in _tag(s, 'id="searchToggleBtn"')


def test_menu_opens_on_the_left_on_pc():
    # PC 는 아바타가 헤더 왼쪽에 있다
    assert "lg:left-4" in _tag(_html(), 'id="userMenu"')


# ---- 본문 2열: 440px | 1fr ----
def test_main_is_two_columns_on_pc():
    s = _html()
    main = _tag(s, "<main")
    assert "lg:grid" in main
    assert "lg:grid-cols-[440px_minmax(0,1fr)]" in main


def test_list_column_is_a_glass_card_on_pc_and_summary_is_flat_inside_it():
    s = _html()
    assert 'id="listColumn"' in s
    style = _between(s, "<style>", "</style>")
    assert "#listColumn" in style
    assert "@media (min-width: 1024px)" in style
    # 자산 요약은 모바일에서 자기 카드, PC 에서는 왼쪽 카드 안의 평면 영역
    assert 'id="assetSummary"' in s
    assert "#assetSummary" in style


def test_detail_pane_exists_only_on_pc():
    s = _html()
    pane = _tag(s, 'id="detailPane"')
    classes = pane.split('class="')[1].split('"')[0].split()
    assert "hidden" in classes and "lg:block" in classes


def test_bottom_bar_hidden_on_pc():
    s = _html()
    assert "lg:hidden" in _tag(s, 'id="bottomBar"')
    assert "lg:pb-0" in _tag(s, "<body")


# ---- 목록 행: PC 에서는 아코디언이 아니라 선택 ----
def test_rows_do_not_expand_inline_on_pc():
    rec = _func("renderRecommendations")
    hold = _func("renderHoldings")
    for body in (rec, hold):
        assert "isPcLayout()" in body
        assert "aria-pressed" in body  # PC 는 선택 상태를 aria-pressed 로 알린다
    assert "isPcLayout()" in _func("renderBottomBar")  # PC 는 하단 바를 쓰지 않는다


@needs_node
def test_selected_row_is_highlighted_on_pc_only(run):
    sel = run("pcRowClass(true, true)")
    assert "bg-white/[0.16]" in sel and "border-white/30" in sel
    # 선택되지 않은 행도 같은 테두리 두께(투명)라 선택해도 크기가 변하지 않는다
    other = run("pcRowClass(true, false)")
    assert "bg-white/[0.16]" not in other and "border-transparent" in other
    # 모바일(아코디언)에는 PC 용 클래스를 붙이지 않는다
    assert run("pcRowClass(false, true)") == ""


def test_rows_use_the_pc_row_class():
    assert "pcRowClass(" in _func("renderRecommendations")
    assert "pcRowClass(" in _func("renderHoldings")


def test_resize_across_breakpoint_rerenders():
    s = _html()
    assert "matchMedia('(min-width: 1024px)')" in s
    assert "renderDetailPane" in s[s.index("matchMedia('(min-width: 1024px)')"):][:600]


# ---- 오른쪽 패널 내용 ----
def test_detail_pane_dispatches_by_mode():
    body = _func("renderDetailPane")
    for name in ("detailPaneState(", "recDetailHtml(", "holdingDetailHtml(", "summaryPaneHtml("):
        assert name in body, name


def test_detail_pane_recommendation_uses_the_inline_buy_panel():
    body = _func("recDetailHtml")
    assert "ibBoxHtml(" in body  # PC 매수는 상세 안의 인라인 패널(tests/test_frontend_buy_panel.py). 모달은 모바일 경로
    assert "openBuyModal(" not in body
    assert "pcChartPanel(" in body  # 차트 칸(캔버스 pcChartCanvas)은 보유 상세와 공통


def test_detail_pane_holding_has_gauge_and_full_sell():
    body = _func("holdingDetailHtml")
    assert "sellBoxHtml(h, false)" in body  # 매도 버튼은 sellBoxHtml 안에서 executeSell 을 부른다
    assert "executeSell(" in _func("sellDynHtml")
    assert "stop_loss_price" in body and "target_price" in body
    assert "pcChartPanel(" in body


def test_stat_cells_become_visible_glass_cells_on_pc():
    # 검정 바탕 위의 bg-black/35 칸은 PC 오른쪽 패널에서 보이지 않으므로 PC 에서만 글라스 칸으로 바꾼다
    s = _html()
    assert 'class="stat-cell' in _func("statCell")
    assert "#detailPane .stat-cell" in _between(s, "<style>", "</style>")


def test_pc_detail_puts_the_buy_panel_next_to_the_ai_diagnosis():
    # 시안 S1: AI 진단(1fr) | 매수 패널(360px) 2열. 차트는 낮게(h-48) 둔다
    # (800px 높이에서는 매수 버튼까지 스크롤이 필요하다. 높이가 충분하면 첫 화면에 들어온다)
    body = _func("pcChartPanel")
    assert "h-48" in body and "h-64" not in body
    rec = _func("recDetailHtml")
    assert "ibBoxHtml(" in rec.split("const buy")[1].split("return")[0]
    assert "grid-cols-[minmax(0,1fr)_360px]" in rec and rec.index("recAiHtml(") < rec.index("${buy}")


def test_pc_chart_panel_draws_on_its_canvas():
    assert 'id="pcChartCanvas"' in _func("pcChartPanel")
    assert "'pcChartCanvas'" in _func("drawPcChart")


def test_detail_pane_summary_shows_account_numbers_and_guide():
    # 단계 5 에서 요약이 패널 묶음(summaryPanelsHtml)이 되어 계좌 숫자는 내 계좌 패널이 만든다
    account = _func("accountPanelHtml")
    assert "realized_pnl" in account
    assert "total_return_pct" in account
    assert "종목을 선택하세요" in _func("summaryPaneHtml")


def test_mobile_accordion_and_pc_detail_share_the_same_pieces():
    # 핵심 수치·AI 진단은 한 곳에서 만들어 모바일 아코디언과 PC 상세가 같은 값을 보여준다
    for name in ("recStatCellsHtml", "recAiHtml", "holdingStatusBadge"):
        assert f"function {name}" in _html(), name
    assert "recStatCellsHtml(" in _func("renderRecommendations")
    assert "recStatCellsHtml(" in _func("recDetailHtml")
    assert "recAiHtml(" in _func("renderRecommendations")
    assert "recAiHtml(" in _func("recDetailHtml")
    assert "holdingStatusBadge(" in _func("renderHoldings")
    assert "holdingStatusBadge(" in _func("holdingDetailHtml")


def test_selection_rerenders_detail_pane():
    for name in ("renderRecommendations", "renderHoldings", "switchTab"):
        assert "renderDetailPane()" in _func(name), name
