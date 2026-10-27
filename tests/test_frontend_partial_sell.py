"""부분 매도 화면 검증(시안 B 변형: − [수량 입력] + 으로만 조절).

- 수량 로직(`// <sell-logic>`)은 DOM 을 쓰지 않는 순수 함수라 node 로 그대로 실행한다. 입력 규칙은 매수와 같다.
- 기본 선택은 전량이고, 전량이면 요청에 quantity 를 넣지 않는다(기존 전량 매도와 완전히 같다).
- 일부 수량의 예상 금액은 서버 미리보기(GET /api/sell/preview)가 준 값만 보인다. 화면은 수수료·세금을 계산하지 않는다.
- 소수점 가능 여부는 서버가 보유 종목에 준 is_fractional 만 믿는다(없으면 정수만).
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


def _logic():
    m = re.search(r"// <sell-logic>\r?\n(.*?)// </sell-logic>", _html(), re.S)
    assert m, "index.html 에 sell-logic 구간이 없습니다"
    return m.group(1)


def _node(tmp_path, src, expr):
    f = tmp_path / "t.js"
    f.write_text(src + "\nconsole.log(JSON.stringify(" + expr + "));\n", encoding="utf-8")
    out = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.fixture
def logic(tmp_path):
    src = _logic()
    return lambda expr: _node(tmp_path, src, expr)


def squash(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


# ---- 수량 로직 ----
@needs_node
def test_default_and_clamp(logic):
    assert logic("clampSellQty(undefined, 3)") == 3   # 선택이 없으면 전량
    assert logic("clampSellQty(5, 3)") == 3           # 보유보다 많으면 보유 수량
    assert logic("clampSellQty(2, 3)") == 2
    assert logic("clampSellQty(0.4, 3)") == 0.4       # 소수점 가능 종목은 1주 미만도 직접 입력할 수 있다
    assert logic("clampSellQty(0, 3)") == 3           # 0 은 선택이 아니다(빈칸 상태는 sellQtyOf 가 따로 다룬다)
    assert logic("clampSellQty(undefined, 0.5)") == 0.5  # 소수 보유 1주 미만은 그대로 전량


@needs_node
def test_step_moves_by_one_within_range(logic):
    assert logic("stepSellQty(1, 1, 3)") == 2
    assert logic("stepSellQty(3, 1, 3)") == 3         # 최대에서 더 늘지 않음
    assert logic("stepSellQty(3, -1, 3)") == 2
    assert logic("stepSellQty(1, -1, 3)") == 1        # 최소 1주
    assert logic("stepSellQty(2, 1, 2.5)") == 2.5     # 소수 보유의 마지막 걸음은 전량
    assert logic("stepSellQty(2.5, -1, 2.5)") == 2
    assert logic("stepSellQty(2.2781, 1, 5)") == 3    # 소수 수량은 가까운 정수로 맞춘다
    assert logic("stepSellQty(2.2781, -1, 5)") == 2
    assert logic("stepSellQty(0, 1, 3)") == 1         # 빈칸/0 에서도 걸음은 1주부터
    assert logic("stepSellQty(0, -1, 3)") == 1


@needs_node
def test_full_sell_sends_no_quantity(logic):
    assert logic("isFullSell(3, 3)") is True
    assert logic("isFullSell(2.9999, 3)") is False
    assert logic("sellRequestBody('035720', 3, 3)") == {"code": "035720"}
    assert logic("sellRequestBody('035720', 1, 3)") == {"code": "035720", "quantity": 1}


# ---- 직접 입력 규칙(매수와 같다) ----
@needs_node
def test_typed_quantity_for_fractional_stock(logic):
    assert logic("normalizeSellQty('2.5', true, 3)") == {"qty": 2.5, "kind": "", "message": ""}
    assert logic("normalizeSellQty('0.12345', true, 3)")["qty"] == 0.1234      # 소수 4자리 내림
    r = logic("normalizeSellQty('5', true, 3)")                                 # 보유 초과 → 보유 수량
    assert r["qty"] == 3 and r["kind"] == "notice" and "보유 3주" in r["message"]
    r = logic("normalizeSellQty('0.00004', true, 3)")
    assert r["qty"] == 0 and r["kind"] == "error" and "0.0001주" in r["message"]


@needs_node
def test_typed_quantity_for_integer_only_stock(logic):
    assert logic("normalizeSellQty('2', false, 3)") == {"qty": 2, "kind": "", "message": ""}
    r = logic("normalizeSellQty('2.7', false, 3)")
    assert r["qty"] == 2 and r["kind"] == "notice" and "1주 단위" in r["message"] and "2주" in r["message"]
    r = logic("normalizeSellQty('0.5', false, 3)")
    assert r["qty"] == 0 and r["kind"] == "error" and "1주 단위" in r["message"]
    r = logic("normalizeSellQty('5', false, 3)")
    assert r["qty"] == 3 and "보유 3주" in r["message"]


@needs_node
def test_typing_the_whole_holding_is_always_allowed(logic):
    # 소수점 불가 종목이어도 보유 전량은 그대로(서버의 전량 예외와 같다). 소수 보유라도 마찬가지
    assert logic("normalizeSellQty('2.5', false, 2.5)") == {"qty": 2.5, "kind": "", "message": ""}
    r = logic("normalizeSellQty('1.5', false, 2.5)")
    assert r["qty"] == 1 and r["kind"] == "notice"


@needs_node
def test_empty_or_invalid_input_is_an_error(logic):
    for raw in ("", "   ", "abc", "0", "-1", "-0.5"):
        r = logic(f"normalizeSellQty({json.dumps(raw)}, true, 3)")
        assert r["qty"] == 0 and r["kind"] == "error" and "수량을 입력하세요" in r["message"], raw


# ---- 패널 표시(node 로 실제 렌더) ----
@pytest.fixture
def box(tmp_path):
    src = "\n".join([
        _logic(),
        "let sellSel = {}; let sellPreview = {}; let sellMsg = {};",
        "function buyQtyInputWidthCh(t) { return Math.max(1, String(t).length) + 0.2; }",
        *(_func(n) for n in ("signedWon", "pnlTextClass", "estimateRowsHtml", "sellQtyOf", "sellEstimateHtml", "sellDynHtml", "sellBoxHtml")),
    ])

    def _box(setup, mobile="false"):
        return _node(tmp_path, src, f"(() => {{ {setup}; return sellBoxHtml(H, {mobile}); }})()")

    return _box


H_JS = "const H = {code:'035720', name:'카카오', quantity:3, is_fractional:true, est_proceeds:88909, est_realized_pnl:-191};"


@needs_node
def test_panel_defaults_to_full_sell_with_an_editable_quantity(box):
    html = box(H_JS)
    text = squash(html)
    assert re.search(r'<input[^>]*id="sellQtyInput_035720"[^>]*value="3"', html)
    assert 'type="number"' in html and 'inputmode="decimal"' in html
    assert "3주 전량 모의 매도" in text
    assert "예상 수령액 (세금·수수료 반영) 88,909원" in text
    assert "예상 실현 손익 -191원" in text
    assert 'aria-label="수량 줄이기"' in html and 'aria-label="수량 늘리기"' in html
    assert "w-11 h-11" in html  # 터치 영역 44px


@needs_node
def test_panel_has_a_max_button_like_the_buy_modal(box):
    html = box(H_JS)
    assert re.search(r"""<button[^>]*onclick="sellMax\('035720'\)"[^>]*>\s*최대로 채우기""", html)
    assert "min-h-[44px]" in html  # 터치 영역
    assert "보유 3주" in squash(html)  # 보유 수량 표시는 그대로


def test_max_button_fills_the_whole_holding():
    body = _func("sellMax")
    assert "applySellQty(code, h.quantity" in body and "syncSellInput(code)" in body


@needs_node
def test_panel_has_no_percent_chips(box):
    html = box(H_JS)
    for gone in ("25%", "50%", "aria-pressed"):
        assert gone not in html, gone


@needs_node
def test_panel_shows_partial_quantity_and_server_preview(box):
    html = box(H_JS + " sellSel['035720'] = 1; sellPreview['035720'] = {qty: 1, status: 'ok', data: {net: 29637, est_realized_pnl: -63}};")
    text = squash(html)
    assert re.search(r'id="sellQtyInput_035720"[^>]*value="1"', html)
    assert "1주 모의 매도" in text and "전량 모의 매도" not in text
    assert "예상 수령액 (세금·수수료 반영) 29,637원" in text
    assert "예상 실현 손익 -63원" in text


@needs_node
def test_panel_shows_a_fractional_quantity(box):
    html = box(H_JS + " sellSel['035720'] = 0.5; sellPreview['035720'] = {qty: 0.5, status: 'ok', data: {net: 14819, est_realized_pnl: -31}};")
    assert re.search(r'id="sellQtyInput_035720"[^>]*value="0.5"', html)
    assert "0.5주 모의 매도" in squash(html)


@needs_node
def test_panel_ignores_a_preview_for_another_quantity(box):
    # 늦게 온 응답/이전 수량의 미리보기는 지금 수량의 값처럼 보이지 않는다
    html = box(H_JS + " sellSel['035720'] = 2; sellPreview['035720'] = {qty: 1, status: 'ok', data: {net: 29637, est_realized_pnl: -63}};")
    text = squash(html)
    assert "29,637" not in text
    assert "계산 중" in text


@needs_node
def test_panel_shows_loading_and_error_states(box):
    loading = squash(box(H_JS + " sellSel['035720'] = 1; sellPreview['035720'] = {qty: 1, status: 'loading'};"))
    assert "예상 금액 계산 중" in loading
    err = squash(box(H_JS + " sellSel['035720'] = 1; sellPreview['035720'] = {qty: 1, status: 'error'};"))
    assert "예상 금액을 표시하지 못해요" in err


@needs_node
def test_empty_quantity_disables_the_sell_button_and_explains(box):
    html = box(H_JS + " sellSel['035720'] = 0; sellMsg['035720'] = {kind: 'error', message: '수량을 입력하세요.'};")
    assert re.search(r'id="sellQtyInput_035720"[^>]*value=""', html)
    assert re.search(r'<button[^>]*onclick="executeSell\(\'035720\'\)"[^>]*disabled', html)
    text = squash(html)
    assert "수량을 입력하세요." in text
    assert "예상 수령액" not in text  # 금액은 보이지 않는다


@needs_node
def test_notice_message_is_shown_under_the_input(box):
    html = box(H_JS + " sellSel['035720'] = 2; sellMsg['035720'] = {kind: 'notice', message: '이 종목은 1주 단위라 2주로 적용돼요.'};")
    assert "이 종목은 1주 단위라 2주로 적용돼요." in squash(html)


# ---- 구조 ----
def test_pc_and_mobile_use_the_same_sell_box():
    pc = _func("holdingDetailHtml")
    mobile = _func("renderHoldings")
    assert "sellBoxHtml(h, false)" in pc
    assert "sellBoxHtml(h, true)" in mobile
    assert "executeSell('${h.code}')" not in pc and "executeSell('${h.code}')" not in mobile  # 버튼은 패널 안으로 옮겨짐


def test_sell_box_wires_the_controls():
    body = _func("sellBoxHtml")
    assert "sellStep(" in body and "onSellQtyInput(" in body and "onSellQtyBlur(" in body
    assert "sellBox_" in body and "sellDyn_" in _func("sellDynHtml")  # 입력칸과 예상 금액·버튼 영역을 따로 갱신
    assert "executeSell(" in _func("sellDynHtml")


def test_typing_does_not_rewrite_the_input_or_the_whole_panel():
    # 입력 도중에 입력칸을 다시 그리거나 덮어쓰면 타이핑이 끊긴다. 보정값은 칸을 벗어날 때만 쓴다
    typing = _func("onSellQtyInput")
    assert "normalizeSellQty(" in typing and "is_fractional" in typing
    assert "outerHTML" not in typing and "input.value =" not in typing and "sellBox_" not in typing
    assert "input.value =" in _func("syncSellInput")
    assert "syncSellInput(" in _func("onSellQtyBlur")
    refresh = _func("refreshSellBox")
    assert "sellDyn_" in refresh and "sellBox_" not in refresh.replace("sellDyn_", "")


def test_no_chip_code_is_left():
    s = _html()
    assert "chipSellQty" not in s and "sellChip" not in s


# ---- 주문·미리보기 ----
def test_execute_sell_sends_quantity_only_for_partial():
    body = _func("executeSell")
    assert "sellRequestBody(" in body
    assert "body: { code: code }" not in body
    assert "/api/sell'" in body


def test_execute_sell_refuses_an_empty_quantity():
    assert "!(qty > 0)" in _func("executeSell")


def test_confirm_text_names_the_quantity():
    body = _func("executeSell")
    assert "confirm(" in body
    assert "전량" in body and "주를 " in body and "매도하시겠습니까" in body


def test_preview_is_debounced_and_stale_responses_are_dropped():
    s = _html()
    assert re.search(r"const SELL_PREVIEW_DELAY_MS = 250;", s)
    body = _func("fetchSellPreview")
    assert "/api/sell/preview?code=" in body
    assert "sellPreviewSeq" in body  # 늦게 온 응답을 버리는 순번


def test_screen_does_not_calculate_fees_or_taxes():
    for name in ("sellBoxHtml", "sellDynHtml", "sellEstimateHtml", "executeSell", "fetchSellPreview", "onSellQtyInput"):
        body = _func(name)
        for forbidden in ("0.00015", "0.0015", "0.002", "0.00215", "SELL_TAX", "SELL_FEE", "estimate_sell_cost", "calc_sell"):
            assert forbidden not in body, (name, forbidden)
    logic = _logic()
    for forbidden in ("0.00015", "0.0015", "0.002", "0.00215"):
        assert forbidden not in logic
