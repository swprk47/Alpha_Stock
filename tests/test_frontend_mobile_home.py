"""UI 개편 단계 2(모바일 홈) 검증: 헤더·내 메뉴·검색 토글·아코디언·하단 고정 바.

순수 함수는 index.html 의 `// <home-logic>` 구간을 node 로 그대로 실행해 확인하고,
화면 구조는 문자열로 확인한다. 주문·수량 로직은 이 단계에서 바뀌지 않는다.
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


def _logic_source():
    m = re.search(r"// <home-logic>\r?\n(.*?)// </home-logic>", _html(), re.S)
    assert m, "index.html 에 home-logic 구간이 없습니다"
    return m.group(1)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    d = tmp_path_factory.mktemp("homejs")
    src = _logic_source()

    def _run(expr):
        f = d / "t.js"
        f.write_text(src + "\nconsole.log(JSON.stringify(" + expr + "));\n", encoding="utf-8")
        out = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    return _run


# ---- 아코디언: 한 번에 하나만 펼침, 같은 행을 다시 누르면 접힘 ----
@needs_node
def test_accordion_opens_clicked_row(run):
    assert run("nextExpandedIndex(-1, 0)") == 0
    assert run("nextExpandedIndex(0, 2)") == 2


@needs_node
def test_accordion_closes_when_same_row_clicked(run):
    assert run("nextExpandedIndex(0, 0)") == -1
    assert run("nextExpandedIndex(3, 3)") == -1


# ---- 하단 고정 바: 추천 탭에서 펼친 종목이 있을 때만 ----
RECS = (
    "[{current_price:22450,sizing:{recommended_quantity:2,total_cost:44900}},"
    "{current_price:20300,sizing:{recommended_quantity:3,total_cost:60900}}]"
)


@needs_node
def test_bottom_bar_shows_expanded_recommendation(run):
    # 총 결제 = 가격×수량 + 수수료 0.015%(내림). 20,300×3 = 60,900, 수수료 floor(9.135) = 9
    assert run(f"bottomBarState('recs', 1, {RECS})") == {"idx": 1, "qty": 3, "total": 60909}


@needs_node
def test_bottom_bar_total_includes_fee_like_buy_modal(run):
    # 22,450×2 = 44,900, 수수료 floor(6.735) = 6 (서버 sizing.total_cost 는 수수료 제외라 그대로 쓰지 않는다)
    assert run(f"bottomBarState('recs', 0, {RECS})")["total"] == 44906


@needs_node
def test_bottom_bar_hidden_when_nothing_expanded(run):
    assert run(f"bottomBarState('recs', -1, {RECS})") is None


@needs_node
def test_bottom_bar_hidden_on_holdings_tab(run):
    assert run(f"bottomBarState('holdings', 0, {RECS})") is None


@needs_node
def test_bottom_bar_hidden_for_missing_or_unsized_item(run):
    assert run("bottomBarState('recs', 0, [])") is None
    assert run("bottomBarState('recs', 5, " + RECS + ")") is None
    assert run("bottomBarState('recs', 0, [{}])") is None


# ---- 헤더: 초기화·알림 버튼은 내 메뉴로 ----
def test_header_has_search_refresh_menu_only():
    header = _between(_html(), "<header", "</header>")
    for needed in ('id="searchToggleBtn"', 'id="refreshBtn"', 'id="menuBtn"'):
        assert needed in header, needed
    assert "resetAccount" not in header
    assert 'id="notifBtn"' not in header
    assert 'aria-haspopup="menu"' in header


def test_search_bar_hidden_until_toggled():
    s = _html()
    m = re.search(r'<div id="searchWrap" class="([^"]*)"', s)
    assert m, "searchWrap 이 없습니다"
    assert "hidden" in m.group(1).split()
    assert "function toggleSearch" in s


# ---- 내 메뉴 ----
def test_user_menu_items():
    menu = _between(_html(), 'id="userMenu"', "<!-- /userMenu -->")
    assert 'role="menu"' in menu
    assert menu.count('role="menuitem"') >= 3
    assert "toggleNotificationSetting()" in menu
    assert "resetAccount()" in menu
    assert "logout()" in menu
    # 계좌 초기화는 빨강, 모든 항목은 터치 영역 44px 이상
    reset = _between(menu, "resetAccount()", "</button>")
    assert "text-[#ff6a60]" in reset
    for btn in re.findall(r'<button[^>]*role="menuitem"[^>]*>', menu):
        assert "min-h-[44px]" in btn, btn


def test_menu_closes_on_outside_click_and_escape():
    s = _html()
    assert 'id="menuBackdrop"' in s
    assert "function closeMenu" in s
    assert "'Escape'" in s


# ---- 하단 고정 바 / 푸터 ----
def test_bottom_bar_structure():
    s = _html()
    for needed in ('id="bottomBar"', 'id="bottomBarBuy"', 'id="bottomBarTip"', "function renderBottomBar"):
        assert needed in s, needed
    # 주문은 기존 모달을 연다(이 단계에서 즉시 매수로 바꾸지 않는다)
    assert "openBuyModal(" in _between(s, "function renderBottomBar", "\n    }\n")


def test_bar_buy_opens_modal_with_the_recommended_quantity():
    # 바에 "N주 모의 매수"라고 보이면 모달도 그 N주(수량 방식)로 열려야 한다.
    # 금액 방식 기본값으로 열면 1주 가격에 수수료가 더해져 0.9998주가 되는 불일치가 생긴다.
    s = _html()
    body = _between(s, "function openBuyModal", "\n    }\n")
    assert "sizing.recommended_quantity" in body
    assert "openCustomBuyModal(item," in body
    modal = s[s.index("function openCustomBuyModal"):]
    modal = modal[:modal.index("\n    }\n")]
    assert "presetQty" in modal
    assert "setBuyMode('qty')" in modal


def test_modal_total_matches_bottom_bar_total():
    # 모달의 "총 결제 예상 금액 (수수료 포함)" 은 가격×수량 + 수수료 여야 한다(바와 같은 금액).
    s = _html()
    calc = _between(s, "function updateBuyModalCalcs", "\n    }\n")
    assert "getElementById('buyTotalCost').textContent = totalRequired" in calc


def test_in_card_buy_button_removed():
    assert "모의 매수하기" not in _html()


# ---- 아코디언 접근성 / 보유 종목 ----
def test_rows_are_accessible_accordion_headers():
    s = _html()
    assert s.count('aria-expanded="${') >= 2, "추천·보유 행에 aria-expanded 가 필요합니다"
    assert "function toggleHolding" in s
    assert "eval_amount" in s
    assert "전량 모의 매도" in s
