"""매수·매도 확인창(시안 확인창 1~5, 모바일 1~3) 검증.

네이티브 confirm 대신 앱 디자인의 공용 확인창 하나를 쓴다. 화면 문구·상태는 DOM 없이 node 로 실행하는 순수 함수
(`// <trade-dialog>` 구간)로 만들고, 주문 실행의 성공/실패/401 처리도 순수 함수 runTrade 로 검증한다.
상태: 확인 → 체결 중(두 버튼 잠금, 중복 클릭 방지) → 성공하면 닫힘, 실패하면 창 안에 오류와 '닫기 / 다시 시도'.
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
    assert m, f"index.html 에 {tag} 구간이 없습니다"
    return m.group(1)


@pytest.fixture
def run(tmp_path):
    src = _section("trade-dialog")

    def _run(expr):
        f = tmp_path / "t.js"
        f.write_text(src + f"\n(async () => console.log(JSON.stringify(await ({expr}))))();\n", encoding="utf-8")
        out = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    return _run


# ---- 확인창 내용(시안 확인창 1·2·3) ----
@needs_node
def test_buy_confirm_content(run):
    cfg = run("buyConfirmCfg('HMM', 2.6842, {total: 59999, remaining: 40001})")
    assert cfg["title"] == "HMM 2.6842주를 매수할까요?"
    assert cfg["lead"] == "모의 매수예요. 실제 돈은 쓰이지 않아요."
    assert [(r["label"], r["value"]) for r in cfg["rows"]] == [
        ("매수 수량", "2.6842주"), ("총 결제 예상 (수수료 포함)", "59,999원"), ("매수 후 남는 현금", "40,001원")]
    assert "서버 실시간 시세" in cfg["note"]
    assert cfg["confirmText"] == "2.6842주 매수"
    assert [(r["label"], r["value"]) for r in cfg["errorRows"]] == [("주문", "HMM 2.6842주 매수"), ("총 결제 예상", "59,999원")]


@needs_node
def test_partial_sell_confirm_content(run):
    cfg = run("sellConfirmCfg('카카오', 1, false, {net: 29637, pnl: -63})")
    assert cfg["title"] == "카카오 1주를 매도할까요?"
    assert cfg["lead"] == "모의 매도예요. 실제 돈은 오가지 않아요."
    assert [(r["label"], r["value"], r["tone"]) for r in cfg["rows"]] == [
        ("매도 수량", "1주", ""), ("예상 수령액 (세금·수수료 반영)", "29,637원", ""), ("예상 실현 손익", "-63원", "dn")]
    assert cfg["confirmText"] == "1주 매도"
    assert [(r["label"], r["value"]) for r in cfg["errorRows"]] == [("주문", "카카오 1주 매도"), ("예상 수령액", "29,637원")]


@needs_node
def test_full_sell_confirm_content(run):
    cfg = run("sellConfirmCfg('카카오', 2, true, {net: 59274, pnl: -126})")
    assert cfg["title"] == "카카오 2주를 전량 매도할까요?"
    assert cfg["rows"][0]["value"] == "2주 (전량)"
    assert cfg["confirmText"] == "2주 전량 매도"


@needs_node
def test_profit_is_red_and_zero_has_no_tone(run):
    # 이 앱은 이익이 빨강, 손실이 파랑이다
    assert run("sellConfirmCfg('A', 1, false, {net: 10000, pnl: 5})")["rows"][2]["tone"] == "up"
    assert run("sellConfirmCfg('A', 1, false, {net: 10000, pnl: 5})")["rows"][2]["value"] == "+5원"
    assert run("sellConfirmCfg('A', 1, false, {net: 10000, pnl: 0})")["rows"][2]["tone"] == ""
    assert run("sellConfirmCfg('A', 1, false, {net: 10000, pnl: 0})")["rows"][2]["value"] == "0원"


@needs_node
def test_sell_confirm_without_an_estimate_says_so_instead_of_inventing_numbers(run):
    # 시세를 못 받아 서버가 예상 값을 못 준 경우: 숫자를 만들어 내지 않는다
    for est in ("null", "undefined", "{net: null, pnl: null}"):
        cfg = run(f"sellConfirmCfg('카카오', 1, false, {est})")
        text = json.dumps(cfg, ensure_ascii=False)
        assert "예상 금액을 표시할 수 없어요" in text, est
        assert "원" not in "".join(r["value"] for r in cfg["rows"][1:]).replace("표시할 수 없어요", ""), est
        assert cfg["errorRows"][0]["value"] == "카카오 1주 매도"


# ---- 상태(시안 확인창 4·5) ----
@needs_node
def test_confirm_phase_view(run):
    v = run("tradeView(buyConfirmCfg('HMM', 2, {total: 44706, remaining: 55294}), 'confirm')")
    assert v["iconName"] == "zap" and v["iconTone"] == "neutral"
    assert (v["cancelLabel"], v["confirmLabel"], v["busy"]) == ("취소", "2주 매수", False)
    assert v["lead"] and v["note"] and len(v["rows"]) == 3


@needs_node
def test_busy_phase_locks_the_buttons_and_hides_the_lead_and_note(run):
    v = run("tradeView(buyConfirmCfg('HMM', 2, {total: 44706, remaining: 55294}), 'busy')")
    assert v["busy"] is True and v["confirmLabel"] == "체결 중…"
    assert v["lead"] == "" and v["note"] == ""
    assert len(v["rows"]) == 3  # 무엇을 체결 중인지 요약은 남긴다


@needs_node
def test_error_phase_shows_the_message_inside_the_dialog(run):
    v = run("tradeView(sellConfirmCfg('카카오', 1, false, {net: 29637, pnl: -63}), 'error', '실시간 시세를 조회할 수 없어 주문을 거부했습니다. 잠시 후 다시 시도하세요.')")
    assert v["iconName"] == "triangle-alert" and v["iconTone"] == "warn"
    assert v["title"] == "주문하지 못했어요"
    assert v["lead"].startswith("실시간 시세를 조회할 수 없어")
    assert (v["cancelLabel"], v["confirmLabel"], v["busy"]) == ("닫기", "다시 시도", False)
    assert [(r["label"], r["value"]) for r in v["rows"]] == [("주문", "카카오 1주 매도"), ("예상 수령액", "29,637원")]


# ---- 주문 실행 흐름 ----
RUN_TRADE = """(async () => {
  const phases = [];
  await runTrade(%s, (p, m) => phases.push(m ? p + ':' + m : p));
  return phases;
})()"""


@needs_node
def test_run_trade_success_goes_busy_then_done(run):
    assert run(RUN_TRADE % "async () => {}") == ["busy", "done"]


@needs_node
def test_run_trade_failure_shows_the_server_message(run):
    r = run(RUN_TRADE % "async () => { const e = new Error('현금 잔고가 부족합니다.'); e.status = 400; throw e; }")
    assert r == ["busy", "error:현금 잔고가 부족합니다."]


@needs_node
def test_run_trade_network_failure_uses_a_generic_message(run):
    r = run(RUN_TRADE % "async () => { throw new TypeError('Failed to fetch'); }")
    assert r == ["busy", "error:서버 통신 오류가 발생했습니다."]


@needs_node
def test_run_trade_unauthorized_closes_the_dialog_for_the_login_prompt(run):
    r = run(RUN_TRADE % "async () => { const e = new Error('로그인이 필요합니다.'); e.status = 401; throw e; }")
    assert r == ["busy", "closed"]


# ---- 구조 ----
def test_dialog_markup_is_an_accessible_alertdialog_like_the_reset_dialog():
    s = _html()
    m = re.search(r'<div id="tradeModal"[^>]*>', s)
    assert m, "tradeModal 이 없습니다"
    assert "dlg-backdrop" in m.group(0) and "fixed inset-0" in m.group(0) and "hidden" in m.group(0)
    block = s[m.start():s.index("</div>\n  </div>\n", m.start())]
    assert 'role="alertdialog"' in block and 'aria-modal="true"' in block
    for needed in ('id="tradeTitle"', 'id="tradeDesc"', 'id="tradeSummary"', 'id="tradeNote"',
                   'id="tradeCancelBtn"', 'id="tradeConfirmBtn"', 'id="tradeIcon"', "dlg-panel", "max-w-[420px]"):
        assert needed in block, needed
    assert block.count("min-h-[48px]") >= 2  # 두 버튼 모두 48px


def test_keyboard_and_backdrop_behave_like_the_reset_dialog():
    s = _html()
    handler = s[s.index("document.addEventListener('keydown'"):s.index("let recsLoaded")]
    assert "closeTradeModal()" in handler and "trapTradeFocus(e)" in handler
    assert "closeTradeModal()" in re.search(r'<div id="tradeModal"[^>]*>', s).group(0)
    close = _func("closeTradeModal")
    assert "tradeBusy" in close  # 체결 중에는 닫히지 않는다
    assert "tradeReturnFocus" in close  # 닫히면 누른 버튼으로 돌아간다
    assert "tradeCancelBtn" in _func("openTradeConfirm") and "focus()" in _func("openTradeConfirm")  # 초점은 안전한 쪽(취소)


def test_confirm_runs_once_and_retry_is_possible():
    body = _func("tradeConfirm")
    assert re.search(r"if \(tradeBusy[^)]*\) return", body)  # 두 번 눌러도 주문은 한 번
    assert "runTrade(" in body
    assert "tradePhase" in _func("tradeConfirm") or "renderTradeDialog(" in body
    assert "tradeBusy = false" in body


def test_buy_and_sell_use_the_shared_dialog_and_no_native_confirm():
    for name in ("executeSell", "executeInlineBuy"):
        body = _func(name)
        assert "openTradeConfirm(" in body, name
        assert "confirm(" not in body.replace("openTradeConfirm(", ""), name
    assert "buyConfirmCfg(" in _func("executeInlineBuy")
    assert "sellConfirmCfg(" in _func("executeSell")
    # 로그아웃 확인은 이번 범위가 아니라 네이티브 그대로
    assert "confirm('로그아웃하시겠습니까?')" in _html()


def test_the_order_requests_are_unchanged():
    sell = _func("executeSell")
    assert "/api/sell" in sell and "sellRequestBody(" in sell
    buy = _func("executeInlineBuy")
    assert "/api/buy" in buy and "swingTargets(" in buy
    for forbidden in ("user_id",):
        assert forbidden not in sell and forbidden not in buy
    assert "switchTab('holdings')" in buy and "refreshData(" in buy and "refreshData(" in sell


def test_trade_dialog_code_does_not_calculate_fees():
    logic = _section("trade-dialog")
    for forbidden in ("0.00015", "0.0015", "0.002", "0.00215", "BUY_FEE_RATE", "SELL_TAX", "calc_sell"):
        assert forbidden not in logic, forbidden
    for name in ("openTradeConfirm", "tradeConfirm", "renderTradeDialog"):
        body = _func(name)
        for forbidden in ("0.00015", "0.0015", "0.002", "0.00215", "BUY_FEE_RATE"):
            assert forbidden not in body, (name, forbidden)
