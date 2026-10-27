"""PC 인라인 매수 패널(추천 상세·검색 종목 상세 안) 검증.

시안 S1: `금액으로 매수 | 수량으로 매수` 전환, 수량 − [입력] +, 최대 N주 가능·최대로 채우기, 총 결제 예상(수수료 포함),
매수 후 남는 현금, "N주 모의 매수". 매수 전 확인은 네이티브 confirm. 모바일은 기존 하단 바와 모달을 그대로 쓴다.
- 총 결제·남는 현금은 buyTotals(서버 fees.calc_buy_cost 와 같은 계산)만 쓴다. 이 파일이 화면 표시값을 서버와 1원 단위로 대조한다.
- 입력 규칙은 매수 모달과 같다(normalizeBuyQty·stepBuyQty·buyQtyMax 계열 재사용).
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "frontend" / "index.html"
sys.path.insert(0, str(ROOT / "backend"))

import fees  # noqa: E402

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
    assert m, f"index.html 에 {tag} 구간이 없습니다"
    return m.group(1)


def squash(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


@pytest.fixture
def render(tmp_path):
    src = "\n".join([
        _section("buy-calc"),
        _section("qty-logic"),
        "let ibSel = {}; let currentRecs = []; let searchStock = null; let currentPortfolio = null;",
        *(_func(n) for n in ("ibCash", "ibQtyOf", "ibStateOf", "ibDynHtml", "ibBoxHtml")),
    ])

    def _render(setup, expr="ibBoxHtml(ITEM)"):
        f = tmp_path / "t.js"
        f.write_text(src + f"\nconsole.log(JSON.stringify((() => {{ {setup}; return {expr}; }})()));\n", encoding="utf-8")
        out = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    return _render


REC = ("const ITEM = {code:'161390', name:'한국타이어앤테크놀로지', market:'KOSPI', current_price:58600, change_rate:-2.5, "
       "grade:'A', is_fractional:true, sizing:{recommended_quantity:1}}; currentPortfolio = {cash_balance:69496, total_asset:100056};")
SEARCH = ("const ITEM = {code:'005930', name:'삼성전자', market:'KOSPI', current_price:20000, change_rate:0.5, grade:'A', "
          "is_fractional:false}; currentPortfolio = {cash_balance:100000, total_asset:100000};")


# ---- 표시 ----
@needs_node
def test_recommendation_defaults_to_quantity_mode_with_the_recommended_quantity(render):
    html = render(REC)
    text = squash(html)
    assert "금액으로 매수" in text and "수량으로 매수" in text
    assert re.search(r'<input[^>]*id="ibQtyInput_161390"[^>]*value="1"', html)
    assert "총 결제 예상 (수수료 포함) 58,608원" in text      # 시안과 같은 값
    assert "매수 후 남는 현금 10,888원" in text
    assert "1주 모의 매수" in text
    assert "최대 1주 가능" in text and "최대로 채우기" in text
    assert 'aria-label="수량 줄이기"' in html and 'aria-label="수량 늘리기"' in html
    assert "w-11 h-11" in html  # 터치 영역 44px


@needs_node
def test_search_stock_defaults_to_amount_mode_like_the_modal(render):
    html = render(SEARCH)
    text = squash(html)
    assert re.search(r'<input[^>]*id="ibAmtInput_005930"[^>]*value="30000"', html)  # 모달의 기본 금액: min(현금, max(가격, 3만))
    for quick in ("+1만", "+3만", "+5만", "전액(최대)"):
        assert quick in text, quick
    assert "1주" in text                                   # 이 금액으로 살 수 있는 수량
    assert "총 결제 예상 (수수료 포함) 20,003원" in text     # 20,000 + 수수료 3원(서버와 같음)


@needs_node
def test_mode_toggle_marks_the_active_mode(render):
    qty = render(REC)
    assert re.search(r'aria-pressed="true"[^>]*>\s*수량으로 매수', qty)
    assert re.search(r'aria-pressed="false"[^>]*>\s*금액으로 매수', qty)
    amount = render(SEARCH)
    assert re.search(r'aria-pressed="true"[^>]*>\s*금액으로 매수', amount)


@needs_node
def test_button_states_match_the_modal(render):
    short = squash(render(REC.replace("cash_balance:69496", "cash_balance:30000")))
    assert "잔여 현금 부족" in short
    zero = render(REC + " ibStateOf(ITEM).qty = 0;")
    assert "매수 수량 0" in squash(zero)
    assert re.search(r'<button[^>]*onclick="executeInlineBuy\(\'161390\'\)"[^>]*disabled', zero)
    grade_c = squash(render(REC.replace("grade:'A'", "grade:'C'")))
    assert "비추천 종목 1주 매수" in grade_c


@needs_node
def test_input_rules_are_reused_from_the_modal(render):
    # 소수점 가능 종목이면 직접 입력 상한 안내가 소수 기준, 아니면 정수 기준
    frac = squash(render(REC))
    assert "소수점" in frac
    integer = squash(render(REC.replace("is_fractional:true", "is_fractional:false")))
    assert "1주 단위" in integer


# ---- 서버와 1원 단위 대조 ----
@needs_node
def test_displayed_total_equals_the_servers_total(render):
    cases = [(20000, 1), (40000, 1), (100000, 1), (29700, 3), (88905, 2), (50000, 2), (1000, 7), (58600, 1)]
    for price, qty in cases:
        setup = (f"const ITEM = {{code:'000001', name:'t', market:'KOSPI', current_price:{price}, change_rate:0, grade:'A', is_fractional:false,"
                 f" sizing:{{recommended_quantity:{qty}}}}}; currentPortfolio = {{cash_balance:10000000, total_asset:10000000}};")
        text = squash(render(setup))
        s = fees.calc_buy_cost(price, qty)
        assert f"총 결제 예상 (수수료 포함) {s['total']:,}원" in text, (price, qty, s)
        assert f"매수 후 남는 현금 {10000000 - s['total']:,}원" in text, (price, qty, s)


# ---- 구조 ----
def test_recommendation_and_search_details_use_the_inline_panel():
    assert "ibBoxHtml(" in _func("recDetailHtml")
    assert "ibBoxHtml(" in _func("searchDetailHtml")
    # 모바일의 기존 경로(하단 바·모달)는 그대로
    s = _html()
    assert "function openBuyModal(" in s and "bottomBarBuyBtn" in s and "function buySearchStock(" not in s


def test_panel_wires_the_controls():
    box = _func("ibBoxHtml")
    for handler in ("ibMode(", "ibStep(", "ibMax(", "ibQuick(", "onIbQtyInput(", "onIbAmtInput(", "onIbBlur("):
        assert handler in box, handler
    assert "ibBox_" in box and "ibDyn_" in _func("ibDynHtml")
    assert "executeInlineBuy(" in _func("ibDynHtml")


def test_typing_does_not_rewrite_the_inputs_or_the_whole_panel():
    for name in ("onIbQtyInput", "onIbAmtInput"):
        body = _func(name)
        assert "outerHTML" not in body and "input.value =" not in body and "ibBox_" not in body, name
    assert "input.value =" in _func("ibSyncInput")
    assert "ibSyncInput(" in _func("onIbBlur")
    refresh = _func("ibRefresh")
    assert "ibDyn_" in refresh and "ibBox_" not in refresh.replace("ibDyn_", "")


def test_execute_inline_buy_confirms_and_sends_the_same_order_as_the_modal():
    body = _func("executeInlineBuy")
    assert "openTradeConfirm(" in body and "buyConfirmCfg(" in body  # 확인창 내용은 tests/test_frontend_trade_dialog.py 가 검증
    assert "/api/buy" in body and "quantity" in body
    assert "swingTargets(" in body          # 목표가·손절가는 모달이 저장하는 값과 같은 식
    assert "target_price" in body and "stop_loss_price" in body and "max_hold_days" in body
    assert "refreshData(" in body and "switchTab('holdings')" in body
    assert "user_id" not in body
    # 요청 본문에 체결가·종목명을 넣지 않는다(서버가 실시간 시세로 정한다). target_price 같은 필드와 구분하려고 앞 글자를 본다
    assert not re.search(r"[^A-Za-z_]price\s*:", body) and not re.search(r"[^A-Za-z_]name\s*:", body)


def test_inline_buy_code_does_not_calculate_fees_by_itself():
    for name in ("ibDynHtml", "ibBoxHtml", "ibStateOf", "executeInlineBuy", "onIbQtyInput", "onIbAmtInput", "ibQuick", "ibStep", "ibMax"):
        body = _func(name)
        for forbidden in ("0.00015", "1.00015", "BUY_FEE_RATE", "* 0.0"):
            assert forbidden not in body, (name, forbidden)
    assert "buyTotals(" in _func("ibDynHtml")
    assert "qtyForAmount(" in _func("onIbAmtInput")


def test_number_inputs_hide_the_browser_spin_arrows():
    # 입력칸 오른쪽의 위아래 화살표가 숫자를 가리지 않게 한다(매수 모달·매도 패널·인라인 매수 패널의 숫자 칸 모두)
    s = _html()
    style = s[s.index("<style>"):s.index("</style>")]
    for prefix in ("buyQtyInput", "sellQtyInput_", "ibQtyInput_", "ibAmtInput_"):
        assert re.search(rf'{prefix}[^{{]*::-webkit-inner-spin-button\s*{{[^}}]*-webkit-appearance:\s*none', style), prefix
        assert re.search(rf'{prefix}[^{{]*{{[^}}]*appearance:\s*textfield', style), prefix


# ---- 모드 전환: 수량 ↔ 금액이 서로 이어받는다 ----
@pytest.fixture
def mode(tmp_path):
    """ibMode 를 DOM 없이 실행한다(다시 그리는 부분은 요소가 없어 건너뛴다)."""
    src = "\n".join([
        _section("buy-calc"),
        _section("qty-logic"),
        "let ibSel = {}; let currentRecs = []; let searchStock = null; let currentPortfolio = null;",
        "const document = { getElementById: () => null };",
        *(_func(n) for n in ("ibCash", "ibItemOf", "ibQtyOf", "ibStateOf", "ibDynHtml", "ibBoxHtml", "ibRerender", "ibMode")),
    ])

    def _run(body):
        f = tmp_path / "m.js"
        f.write_text(src + f"\nconsole.log(JSON.stringify((() => {{ {body} }})()));\n", encoding="utf-8")
        out = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    return _run


HMM = ("currentPortfolio = {cash_balance: 100000, total_asset: 100000};"
       "currentRecs = [{code:'011200', name:'HMM', market:'KOSPI', current_price:22350, change_rate:0, grade:'A', is_fractional:true, sizing:{recommended_quantity:2}}];"
       "const item = currentRecs[0]; const st = ibStateOf(item);")


@needs_node
def test_switching_to_amount_keeps_the_quantity_as_its_total(mode):
    # 수량 모드에서 1주로 바꾼 뒤 금액 모드로 오면, 금액은 그 1주의 총 결제(수수료 포함)가 된다
    r = mode(HMM + "st.qty = 1; ibMode('011200', 'amount'); return {amount: st.amount, qty: st.qty, mode: st.mode, total: buyTotals(22350, 1, 0).total};")
    assert r["mode"] == "amount" and r["amount"] == r["total"] == 22353 and r["qty"] == 1
    assert fees.calc_buy_cost(22350, 1)["total"] == 22353  # 서버와 같은 값


@needs_node
def test_switching_to_quantity_keeps_the_quantity_derived_from_the_amount(mode):
    r = mode(HMM + "ibMode('011200', 'amount'); st.amount = 50000; st.qty = qtyForAmount(22350, 50000, true); ibMode('011200', 'qty'); return {qty: st.qty, mode: st.mode};")
    assert r["mode"] == "qty" and r["qty"] == 2.2368


@needs_node
def test_round_trip_does_not_leave_a_stale_amount(mode):
    # 금액 5만 원 → 수량 모드에서 1주로 → 다시 금액 모드: 5만 원이 아니라 1주의 총 결제
    r = mode(HMM + "ibMode('011200', 'amount'); st.amount = 50000; st.qty = qtyForAmount(22350, 50000, true);"
                   "ibMode('011200', 'qty'); st.qty = 1; ibMode('011200', 'amount'); return {amount: st.amount, qty: st.qty};")
    assert r["amount"] == 22353 and r["qty"] == 1


@needs_node
def test_amount_mode_shows_the_quantity_derived_from_the_amount_only(mode):
    # 금액 모드의 "이 금액으로 N주"와 버튼 수량은 금액에서만 계산한다(다른 모드에서 바꾼 수량의 영향을 받지 않는다)
    text = squash(mode(HMM + "st.mode = 'amount'; st.amount = 60000; st.qty = 1; return ibDynHtml(item);"))
    assert "이 금액으로 2.6842주" in text and "살 수 있어요" in text
    assert "2.6842주 모의 매수" in text and "1주 모의 매수" not in text
    assert f"총 결제 예상 (수수료 포함) {fees.calc_buy_cost(22350, 2.6842)['total']:,}원" in text


def test_inline_buy_executes_the_quantity_the_panel_shows():
    # 실행 수량도 화면과 같은 ibQtyOf 에서 얻는다(금액 모드에서 stale 수량으로 주문하지 않는다)
    assert "ibQtyOf(" in _func("executeInlineBuy") and "ibQtyOf(" in _func("ibDynHtml")
