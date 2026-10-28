"""모바일 매수 시트(B안): 아래쪽 절반을 PC 인라인 매수 패널과 같은 코드로 그린다.

- 위쪽(종목 카드·차트·AI 진단)은 한 화면에 들어오게 줄이고, 금액/수량 입력·총 결제·버튼은 ibBoxHtml 이 그린다.
- 버튼은 흰색 하나이고 공용 확인창을 거친다(예전 팝업의 빨간 '주문 실행' 버튼과 전용 계산 함수는 없다).
- role=dialog·Esc·초점 복귀, 확인창 아래에 놓이는 쌓임 순서.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "frontend" / "index.html"


def _html():
    return HTML.read_text(encoding="utf-8")


def _func(name):
    s = _html()
    m = re.search(rf"(async )?function {name}\(", s)
    assert m, f"function {name} 이 없습니다"
    return s[m.start():s.index("\n    }\n", m.start()) + len("\n    }")]


def _sheet_markup():
    s = _html()
    start = s.index('id="buyModal"')
    return s[start:s.index("<script>", start)]


# ── 마크업 ──


def test_sheet_is_an_accessible_dialog():
    m = _sheet_markup()
    assert 'role="dialog"' in m and 'aria-modal="true"' in m
    assert 'aria-labelledby="buyModalTitle"' in m and 'id="buyModalTitle"' in m
    assert 'onclick="if (event.target === this) closeBuyModal()"' in m  # 바깥을 누르면 닫힌다
    assert "sheet-backdrop" in m and "sheet-panel" in m


def test_lower_half_is_the_inline_panel_container():
    m = _sheet_markup()
    assert 'id="buySheetPanel"' in m
    # 예전 팝업 전용 요소는 모두 없다(금액/수량 영역, 총 결제 블록, 빨간 주문 버튼)
    for old in ("buyAmountSection", "buyQtySection", "confirmBuyBtn", "buyModeAmountBtn", "buyModeQtyBtn",
                "buyTotalCost", "buyRemainingCash", "buyQtyInput", "buyAmountInput", "buyCalcQtyResult",
                "executeSelectedBuy", "bg-[#ff453a]"):
        assert old not in m, old


def test_top_part_keeps_the_stock_card_chart_and_diagnosis():
    m = _sheet_markup()
    for needed in ("buyStockLogo", "buyKindTag", "buyFractionalTag", "buyStockName", "buyStockCode", "buyStockMarket",
                   "buyStockPrice", "buyStockChange", "buyModalChart", "gradeCard", "gradeBadge", "gradeScoreTag",
                   "gradeReasonsList"):
        assert f'id="{needed}"' in m, needed
    assert "h-[112px]" in m  # 차트는 보기 좋은 높이(예전 팝업 128px), 대신 AI 근거를 접어 한 화면에 넣는다
    assert "h-[72px]" not in m


# ── 옛 팝업 전용 코드는 없다 ──


OLD_FUNCTIONS = ("setBuyMode", "onBuyAmountChange", "setQuickBuyAmount", "calculateQtyFromAmount", "fitBuyQtyInput",
                 "writeBuyQtyInput", "changeBuyQty", "onBuyQtyInput", "onBuyQtyBlur", "fillMaxBuyQty",
                 "renderBuyQtyControls", "updateBuyModalCalcs", "executeSelectedBuy")


@pytest.mark.parametrize("name", OLD_FUNCTIONS)
def test_modal_only_functions_are_removed(name):
    assert f"function {name}(" not in _html(), name


@pytest.mark.parametrize("state", ("selectedRecForBuy", "currentBuyQty", "currentBuyAmount", "maxPossibleBuyQty",
                                    "maxPossibleBuyQtyFrac", "buyQtyMsg", "buyMode"))
def test_modal_only_state_is_removed(state):
    assert not re.search(rf"\blet {state}\b", _html()), state


# ── 열고 닫기 ──


def test_open_renders_the_shared_inline_panel_from_a_fresh_state():
    body = _func("openCustomBuyModal")
    assert "function openCustomBuyModal(stockItem)" in body  # 수량 미리 채우기 인자(presetQty)는 인라인 패널의 초기 규칙이 대신한다
    assert "buySheetItem = stockItem" in body
    assert "delete ibSel[stockItem.code]" in body  # 열 때마다 추천 수량/기본 금액으로 다시 시작(예전 팝업과 같은 동작)
    assert re.search(r"buySheetPanel'\)\.innerHTML = ibBoxHtml\(stockItem\)", body)
    assert "presetQty" not in body


def test_bottom_bar_and_search_both_open_the_same_sheet():
    assert "openCustomBuyModal(item)" in _func("openBuyModal")
    assert "openBuyModal(st.idx)" in _func("renderBottomBar")
    assert "openCustomBuyModal(stock)" in _func("selectSearchResult")


def test_inline_panel_finds_the_item_shown_in_the_sheet():
    assert "buySheetItem" in _func("ibItemOf")  # 모바일 검색 종목은 추천 목록에도 PC 검색 상태에도 없다


def test_close_resets_the_item_and_restores_focus():
    body = _func("closeBuyModal")
    assert "classList.add('hidden')" in body
    assert "buySheetItem = null" in body
    assert "buySheetReturnFocus" in body


def test_open_remembers_the_opener_and_moves_focus_into_the_sheet():
    body = _func("openCustomBuyModal")
    assert "buySheetReturnFocus" in body
    assert "buyModalCloseBtn" in body and ".focus()" in body  # 숫자 칸이 아니라 닫기 버튼(모바일 키보드가 저절로 뜨지 않게)
    assert 'id="buyModalCloseBtn"' in _sheet_markup()


def test_successful_buy_closes_the_sheet_but_a_failed_one_keeps_it():
    body = _func("executeInlineBuy")
    run = body[body.index("async () => {"):]
    assert "closeBuyModal()" in run
    assert run.index("api('/api/buy'") < run.index("closeBuyModal()")  # 주문이 성공한 뒤에만 닫는다


def test_escape_closes_only_the_top_layer_and_tab_stays_inside():
    s = _html()
    m = re.search(r"document\.addEventListener\('keydown'.*?\n    \}\);", s, re.S)
    assert m
    handler = m.group(0)
    assert "closeBuyModal()" in handler and "trapBuySheetFocus(e)" in handler
    # 확인창이 위에 떠 있을 때 Esc 한 번에 시트까지 같이 닫히지 않는다
    assert "tradeModal" in handler


def test_sheet_focus_trap_yields_to_the_confirm_dialog():
    body = _func("trapBuySheetFocus")
    assert "tradeModal" in body and "resetModal" in body


def test_switching_between_phone_and_pc_layout_closes_the_sheet():
    s = _html()
    handler = s[s.index("pcMql.addEventListener('change'"):]
    handler = handler[:handler.index("\n    });")]
    assert "closeBuyModal()" in handler


# ── 모양 ──


def test_sheet_stays_under_the_confirm_dialog():
    s = _html()
    assert 'id="buyModal"' in s and "z-50" in s[s.index('id="buyModal"'):s.index('id="buyModal"') + 200]
    assert re.search(r'id="tradeModal"[^>]*z-\[60\]', s)


def test_sheet_slides_up_and_respects_reduced_motion():
    s = _html()
    css = s[:s.index("</style>")]
    assert ".sheet-panel" in css and ".sheet-backdrop" in css
    assert re.search(r"@starting-style\s*\{[^}]*\.sheet-panel", css, re.S) or ".sheet-panel { transform" in css
    assert "prefers-reduced-motion" in css


def test_tall_content_scrolls_inside_the_sheet():
    m = _sheet_markup()
    # 812px 높이에서 금액 모드(가장 큼, AI 근거 접힘)가 스크롤 없이 들어오는 높이(95%). 더 낮은 화면이나 근거를 펼치면 시트 안에서 스크롤한다
    assert "max-h-[95vh]" in m and "overflow-y-auto" in m


# ── AI 진단: 한 줄만 보이고 근거 문장은 눌러서 펼친다 ──


def test_diagnosis_reasons_are_collapsed_behind_a_toggle():
    m = _sheet_markup()
    btn = re.search(r'<button[^>]*id="gradeToggleBtn"[^>]*>', m)
    assert btn, "근거를 펼치는 버튼이 없습니다"
    tag = btn.group(0)
    assert 'aria-expanded="false"' in tag and 'aria-controls="gradeReasonsList"' in tag
    assert 'onclick="toggleGradeReasons()"' in tag and "min-h-[44px]" in tag  # 터치 크기
    assert re.search(r'id="gradeReasonsList"[^>]*class="[^"]*\bhidden\b', m) or re.search(r'class="[^"]*\bhidden\b[^"]*"[^>]*id="gradeReasonsList"', m)
    # 등급 원·점수 한 줄은 접혀도 보인다
    assert m.index('id="gradeBadge"') > m.index('id="gradeToggleBtn"')
    assert m.index('id="gradeScoreTag"') < m.index('id="gradeReasonsList"')


def test_sheet_children_never_shrink_so_tall_content_scrolls_instead_of_being_clipped():
    # overflow-hidden 인 AI 카드는 세로 flex 안에서 높이가 모자라면 줄어들며 펼친 근거를 잘라 버린다.
    # 모든 직접 자식이 줄어들지 않게 하고, 넘치는 것은 시트가 스크롤한다
    m = _sheet_markup()
    assert "[&>*]:shrink-0" in m[:m.index('id="buyModalTitle"')]


def test_toggle_flips_the_list_aria_state_and_chevron():
    body = _func("toggleGradeReasons")
    assert "gradeReasonsList" in body and "classList.toggle('hidden'" in body
    assert "aria-expanded" in body and "rotate-180" in body


def test_opening_the_sheet_starts_collapsed_and_still_fills_the_reasons():
    body = _func("openCustomBuyModal")
    assert "grade_reasons" in body and "gradeReasonsList').innerHTML" in body
    # 이전 종목에서 펼쳐 둔 채로 닫았어도 새로 열면 접힌 상태로 시작
    assert "gradeReasonsList').classList.add('hidden')" in body
    assert "gradeToggleBtn').setAttribute('aria-expanded', 'false')" in body


def test_old_spinner_hiding_rule_for_the_removed_input_is_gone():
    assert "#buyQtyInput" not in _html()
