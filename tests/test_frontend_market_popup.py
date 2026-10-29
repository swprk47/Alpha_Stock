"""'장 시간 안내' 팝업(#marketHoursModal): NXT·KRX 탭, 얇은 색 막대, 현재 시각 V.

구조·접근성 검사(소스). 값 계산은 test_frontend_market_logic.py 가 순수 함수로 검사한다.
Esc 는 맨 위 겹만 닫는다: 팝업이 매수 시트 위에 떠 있으면 팝업만 닫고 시트는 남는다.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "frontend" / "index.html"


def _html():
    return HTML.read_text(encoding="utf-8")


def _func(name):
    s = _html()
    m = re.search(rf"(async )?function {name}\(", s)
    assert m, f"function {name} 이 없습니다"
    return s[m.start():s.index("\n    }\n", m.start()) + len("\n    }")]


def _modal_markup():
    s = _html()
    start = s.index('id="marketHoursModal"')
    end = s.index("<!--", start) if "<!--" in s[start:start + 4000] else start + 3000
    return s[start:end]


def test_popup_is_an_accessible_dialog_with_the_spec_title():
    m = _modal_markup()
    assert 'role="dialog"' in m and 'aria-modal="true"' in m and 'aria-labelledby="marketHoursTitle"' in m
    assert re.search(r'id="marketHoursTitle"[^>]*>\s*장 시간 안내\s*<', m)
    assert 'onclick="if (event.target === this) closeMarketHours()"' in m  # 바깥을 누르면 닫힘
    assert 'aria-label="닫기"' in m and "closeMarketHours()" in m


def test_tabs_are_a_tablist_filled_by_script_with_the_exchange_names():
    m = _modal_markup()
    assert 'role="tablist"' in m and 'id="marketHoursTabs"' in m
    body = _func("renderMarketHours")
    assert 'role="tab"' in body and "aria-selected" in body
    assert "NXT 넥스트레이드" in body and "KRX 한국거래소" in body


def test_footer_explains_the_fill_price_and_holidays():
    m = _modal_markup()
    assert "모의 주문은 정규장 종가로 체결돼요." in m and "공휴일·휴장일에는 열리지 않아요." in m
    assert 'id="marketHoursAsOf"' in m
    assert "marketAsOfText()" in _func("renderMarketHours")


def test_marker_is_a_round_v_chevron_that_screen_readers_skip():
    body = _func("renderMarketHours")
    assert 'aria-hidden="true"' in body and 'stroke-linecap="round"' in body and 'stroke-linejoin="round"' in body
    assert "지금은 시간표 밖이에요" not in body  # 문구는 순수 함수(stateLine)가 만든다
    assert "model.marker" in body and "model.stateLine" in body


def test_legend_names_every_segment_so_colour_is_not_the_only_signal():
    body = _func("renderMarketHours")
    assert "seg.name" in body and "seg.text" in body and "model.breaks" in body and "model.note" in body


def test_open_close_select_functions_exist_and_use_tab_defaults():
    opener = _func("openMarketHours")
    assert "availableTabs(" in opener and "'krx'" in opener  # 기본 탭은 KRX
    assert "kstClock(" in _func("renderMarketHours")
    assert "classList.remove('hidden')" in opener
    assert "classList.add('hidden')" in _func("closeMarketHours")
    assert "marketTab" in _func("selectMarketTab")


def test_escape_closes_only_the_popup_when_it_is_on_top_of_the_sheet():
    s = _html()
    handler = s[s.index("document.addEventListener('keydown'"):]
    handler = handler[:handler.index("let recsLoaded")]
    assert "'marketHoursModal'" in handler               # 맨 위 겹 목록에 포함
    assert "closeMarketHours()" in handler
    assert re.search(r"if \(!dialogOpen\)\s*closeBuyModal\(\)", handler)  # 겹이 열려 있으면 시트는 그대로
    assert "ArrowRight" in handler and "ArrowLeft" in handler          # 탭 이동
    assert "trapMarketFocus(e)" in handler


def test_buy_sheet_focus_trap_stands_down_while_the_popup_is_open():
    assert "'marketHoursModal'" in _func("trapBuySheetFocus")


def test_focus_is_trapped_in_the_popup_and_returned_on_close():
    trap = _func("trapMarketFocus")
    assert "marketHoursModal" in trap and "preventDefault" in trap
    assert "marketReturnFocus" in _func("openMarketHours") and "marketReturnFocus" in _func("closeMarketHours")
