"""UI 개편 단계 4(상태 화면) 검증: 빈 상태·로딩 스켈레톤·오류, 계좌 초기화 확인창.

순수 함수는 index.html 의 `// <state-logic>` 구간을 node 로 그대로 실행해 확인하고,
화면 구조는 문자열로 확인한다. 주문·수량 로직은 이 단계에서 바뀌지 않는다.
(로그아웃·전량 매도의 confirm() 은 이번 범위가 아니라 그대로 둔다.)
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
    m = re.search(rf"(async )?function {name}\(", s)
    assert m, f"function {name} 이 없습니다"
    return s[m.start():s.index("\n    }\n", m.start())]


def _tag(s, needle):
    """needle 을 포함하는 여는 태그 전체."""
    i = s.index(needle)
    start = s.rfind("<", 0, i)
    return s[start:s.index(">", i) + 1]


def _logic_source():
    m = re.search(r"// <state-logic>\r?\n(.*?)// </state-logic>", _html(), re.S)
    assert m, "index.html 에 state-logic 구간이 없습니다"
    return m.group(1)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    d = tmp_path_factory.mktemp("statesjs")
    src = _logic_source()

    def _run(expr):
        f = d / "t.js"
        f.write_text(src + "\nconsole.log(JSON.stringify(" + expr + "));\n", encoding="utf-8")
        out = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    return _run


# ---- 추천 목록의 상태: 로딩 / 빈 상태 / 오류 / 정상 ----
@needs_node
def test_list_has_items_is_ok_even_if_the_last_refresh_failed(run):
    # 이미 받은 목록이 있으면 갱신이 실패해도 그 목록을 계속 보여준다("마지막으로 확인된 값")
    assert run("recsViewState(true, false, '2026-10-27 11:00:00', 3)") == "ok"
    assert run("recsViewState(true, true, '2026-10-27 11:00:00', 3)") == "ok"


@needs_node
def test_nothing_received_yet_is_loading_until_it_fails(run):
    assert run("recsViewState(false, false, '', 0)") == "loading"
    assert run("recsViewState(false, true, '', 0)") == "error"


@needs_node
def test_empty_list_with_successful_calculation_is_empty_state(run):
    # 서버가 계산에 성공했지만(updated_at 있음) 이 예산에 맞는 종목이 없다
    assert run("recsViewState(true, false, '2026-10-27 11:00:00', 0)") == "empty"


@needs_node
def test_empty_list_without_updated_at_means_quote_failure_is_error(run):
    # updated_at 이 비어 있으면 시세를 못 받아 추천을 못 만든 것 → 빈 상태가 아니라 오류
    assert run("recsViewState(true, false, '', 0)") == "error"


# ---- 추천 예산: 현금을 1만~1억 사이로 맞춘다(기존 refreshData 계산과 같다) ----
@needs_node
def test_recs_budget_clamps_and_floors(run):
    assert run("recsBudget(54994.7)") == 54994
    assert run("recsBudget(5000)") == 10000
    assert run("recsBudget(250000000)") == 100000000
    assert run("recsBudget(null)") == 100000
    assert run("recsBudget(undefined)") == 100000


# ---- 초기화 확인창 요약: 화면에 있는 값 + 서버가 주는 거래 기록 ----
@needs_node
def test_reset_summary_counts_trades_holdings_and_asset_change(run):
    p = "{total_asset:100056,initial_balance:100000,holdings:[{code:'A'}],history:[{},{},{},{}]}"
    assert run(f"resetSummary({p})") == {"trades": 4, "holdings": 1, "from": 100056, "to": 100000}


@needs_node
def test_reset_summary_omits_trade_count_when_server_gives_no_history(run):
    # 서버가 거래 기록을 안 주면 건수를 지어내지 않고 그 줄을 뺀다(null)
    p = "{total_asset:90000,initial_balance:100000,holdings:[]}"
    assert run(f"resetSummary({p})") == {"trades": None, "holdings": 0, "from": 90000, "to": 100000}


@needs_node
def test_reset_summary_defaults_seed_to_100000(run):
    assert run("resetSummary({total_asset:1,holdings:[],history:[]})")["to"] == 100000


# ---- 로딩: 최종 레이아웃과 같은 모양의 스켈레톤, 1.4초 shimmer, 스피너 금지 ----
def test_skeleton_shimmers_every_1_4s_linearly():
    style = _between(_html(), "<style>", "</style>")
    assert "@keyframes sk-shimmer" in style
    assert re.search(r"\.sk\s*\{[^}]*sk-shimmer 1\.4s linear infinite", style)


def test_no_round_spinner_for_loading_and_static_pulse_skeleton_replaced():
    s = _html()
    assert "animate-pulse" not in s  # 예전 정적 스켈레톤(깜빡임)은 새 shimmer 로 교체
    assert "loader-circle" not in _func("skeletonRowsHtml")


def test_loading_state_is_announced_and_uses_row_shaped_skeleton():
    body = _func("skeletonRowsHtml")
    assert 'class="sk' in body
    assert "추천 종목을 불러오는 중이에요" in _html()
    assert 'aria-busy="true"' in body


def test_asset_card_shows_skeleton_until_the_portfolio_arrives():
    s = _html()
    assert 'id="assetSkeleton"' in s and 'id="assetContent"' in s
    assert "setAssetLoading(false)" in _func("renderPortfolio")
    assert "setAssetLoading(" in _func("refreshData")


# ---- 빈 상태: 아이콘 + 제목 + 이유 + 할 수 있는 행동 ----
def test_empty_recommendations_state_offers_budget_and_refresh():
    body = _func("stateCardHtml")
    assert "role" in body  # 오류는 alert, 나머지는 status 로 알린다
    s = _html()
    for needed in ("맞는 종목이 아직 없어요", "예산 설정", "새로 고침", "openBudgetModal()", "refreshData(true)"):
        assert needed in s, needed


def test_empty_state_icon_is_search_x_per_spec():
    s = _html()
    assert "'search-x':" in s
    assert 'icon: \'search-x\'' in _func("recsStateCard")


def test_empty_holdings_state_points_to_recommendations():
    body = _func("renderHoldings")
    assert "stateCardHtml(" in body
    s = _html()
    assert "보유 중인 종목이 없어요" in s
    assert "switchTab('recs')" in s


# ---- 오류: 불러오지 못했어요 + 다시 시도, 시세 실패 시 주문이 막히는 이유 ----
def test_error_state_explains_why_orders_are_blocked():
    s = _html()
    for needed in (
        "추천을 불러오지 못했어요",
        "다시 시도",
        "매수·매도가 막혀요",
        "체결가는 서버의 실시간 시세로만",
        "마지막으로 확인된 값",
    ):
        assert needed in s, needed


def test_state_card_text_does_not_break_inside_korean_words():
    # 좁은 폭에서 "못했어/요." 처럼 한 글자가 떨어지지 않게 어절 단위로 줄바꿈
    body = _func("stateCardHtml")
    assert body.count("break-keep") >= 2  # 제목과 이유


def test_error_state_is_an_alert_with_red_border():
    body = _func("stateCardHtml")
    # 오류 톤이면 role=alert(스크린리더가 바로 읽음), 아니면 status
    assert "'alert'" in body and "'status'" in body and 'role="${isError' in body
    assert "rgba(255,106,96,0.45)" in body


def test_refresh_marks_failure_so_the_error_state_can_show():
    assert "function markRecsFailed" in _html()
    assert "markRecsFailed(" in _func("refreshData")
    assert "recsFailed = false" in _func("applyRecsResponse")
    assert "recsBudget(" in _func("refreshData")  # 예산 계산은 한 곳(recsBudget)


def test_recommendations_render_by_view_state():
    body = _func("renderRecommendations")
    assert "recsViewState(" in body
    assert "recsStateCard(" in body


def test_pc_summary_pane_follows_the_state():
    body = _func("summaryPaneHtml")
    assert "recsViewState(" in body
    assert "매수·매도" in body  # 오류일 때 안내 카드


def test_error_note_for_mobile_sits_under_the_card():
    # PC 는 오른쪽 패널에 안내 카드가 있으므로 목록 아래 문구는 모바일에서만
    assert "lg:hidden" in _func("recsStateCard")


# ---- 계좌 초기화 확인창: confirm() 대신 새 디자인, 취소·초기화 같은 크기 ----
def test_reset_no_longer_uses_native_confirm():
    assert "confirm(" not in _func("resetAccount")
    assert "openResetModal()" in _func("resetAccount")


def test_other_native_confirms_are_out_of_scope_and_untouched():
    s = _html()
    assert "confirm('로그아웃하시겠습니까?')" in s
    assert "confirm(" not in _func("executeSell").replace("openTradeConfirm(", "")  # 매수·매도는 앱 디자인의 공용 확인창(tradeModal)


def test_reset_modal_is_an_accessible_alertdialog():
    s = _html()
    assert 'id="resetModal"' in s
    dialog = _tag(s, 'role="alertdialog"')
    assert 'aria-modal="true"' in dialog
    assert 'aria-labelledby="resetTitle"' in dialog
    assert 'id="resetTitle"' in s
    assert "계좌를 초기화할까요?" in s
    assert "되돌릴 수 없어요" in s


def test_reset_modal_buttons_are_the_same_size_with_a_red_confirm():
    s = _html()
    cancel = _tag(s, 'id="resetCancelBtn"')
    confirm_btn = _tag(s, 'id="resetConfirmBtn"')
    for tag in (cancel, confirm_btn):
        assert "min-h-[48px]" in tag
        assert "flex-1" in tag or "w-full" in tag
    assert "bg-[#ff453a]" in confirm_btn and "bg-[#ff453a]" not in cancel
    # 두 버튼은 같은 2열 격자 안에 나란히
    grid = _between(s, 'id="resetCancelBtn"', "</div>")
    assert 'id="resetConfirmBtn"' in grid or 'id="resetConfirmBtn"' in s[s.index('id="resetCancelBtn"'):][:900]
    assert 'grid-cols-2' in s[s.rfind("<div", 0, s.index('id="resetCancelBtn"')):s.index('id="resetCancelBtn"')]


def test_reset_modal_lists_what_gets_erased():
    s = _html()
    assert 'id="resetSummary"' in s
    body = _func("openResetModal")
    assert "resetSummary(" in body
    for label in ("지워지는 거래", "정리되는 보유 종목", "총 자산"):
        assert label in _func("resetSummaryRowsHtml"), label


def test_reset_modal_keyboard_and_focus():
    s = _html()
    assert re.search(r"'Escape'\)[^\n]*closeResetModal\(\)", s)  # Esc 로 닫기
    assert "resetCancelBtn" in _func("openResetModal") and ".focus()" in _func("openResetModal")  # 안전한 쪽(취소)에 초점
    assert "closeResetModal()" in _tag(s, 'id="resetModal"') or "resetBackdrop" in s  # 바깥을 눌러 닫기


def test_reset_modal_returns_focus_even_when_opened_from_the_closed_menu():
    # 내 메뉴 항목을 눌러 열면 그 항목은 이미 숨겨진 메뉴 안이라 돌아갈 수 없다 → 내 메뉴 버튼으로
    body = _func("openResetModal")
    assert "menuBtn" in body
    assert "offsetParent" in body


def test_reset_confirm_calls_api_once_and_reports():
    body = _func("confirmReset")
    assert "'/api/reset'" in body and "method: 'POST'" in body
    assert "disabled" in body  # 처리 중 중복 클릭 방지
    assert "closeResetModal()" in body
    assert "refreshData()" in body


def test_reset_modal_enters_with_a_short_ease_out_scale_not_from_zero():
    style = _between(_html(), "<style>", "</style>")
    assert "@starting-style" in style
    assert "scale(0.95)" in style
    assert "scale(0)" not in style
    assert not re.search(r"\.dlg-panel[^{]*\{[^}]*ease-in\b", style)
