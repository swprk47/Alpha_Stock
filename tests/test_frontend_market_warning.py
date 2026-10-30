"""정규장이 아닐 때의 주문 확인창 경고, 내 메뉴 토글 "장 마감 중 거래", 차단 설정일 때의 사전 안내.

- 경고 문구와 차단 판단은 순수 함수 marketWarning·orderBlock(`// <market-logic>`) 하나만 쓰고 다른 곳에 문구를 복사하지 않는다.
- 차단 문구는 서버(orders.MARKET_BLOCK_MESSAGE)와 같은 글자다. 서버가 최종 판단이고, 화면은 설정이 "차단"이고 정규장이 아닐 때
  확인창을 열지 않고 같은 안내를 먼저 보인다(unknown 은 막지 않는다).
- 정규장은 경고가 없고, 확인창 아래의 기존 문구("체결가는 서버 실시간 시세로…")는 그대로 둔다.
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

BLOCK = "장 마감 중에는 주문하지 않도록 설정돼 있어요. 내 메뉴에서 바꿀 수 있어요."


def _html():
    return HTML.read_text(encoding="utf-8")


def _func(name):
    s = _html()
    m = re.search(rf"(async )?function {name}\(", s)
    assert m, f"function {name} 이 없습니다"
    return s[m.start():s.index("\n    }\n", m.start()) + len("\n    }")]


def _section(tag):
    m = re.search(rf"// <{tag}>\r?\n(.*?)// </{tag}>", _html(), re.S)
    assert m, f"{tag} 구간이 없습니다"
    return m.group(1)


@pytest.fixture
def run(tmp_path):
    src = "\n".join([_section("market-logic"), _section("trade-dialog")])

    def _run(expr):
        f = tmp_path / "t.js"
        f.write_text(src + f"\n(async () => console.log(JSON.stringify(await ({expr}))))();\n", encoding="utf-8")  # async 함수도 기다린다
        out = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    return _run


def _ms(state):
    return json.dumps({"state": state, "nxt_listed": True})


# ── 경고 문구 ──


@needs_node
@pytest.mark.parametrize("state,expected", [
    ("regular", ""),
    ("pre", "프리마켓이에요. 체결가는 전 거래일 종가로 정해져요."),
    ("after", "애프터마켓이에요. 체결가는 정규장 종가 230,500원으로 정해져요."),
    ("closed", "장 마감이에요. 마지막 정규장 종가로 체결돼요."),
    ("unknown", "장 상태를 확인하지 못했어요. 체결가는 주문 시점 시세로 정해져요."),
])
def test_warning_text_table(run, state, expected):
    assert run(f"marketWarning({_ms(state)}, 230500)") == expected


@needs_node
@pytest.mark.parametrize("ms", ["null", "undefined", "{}", "{state: 'weird'}", "'after'", "{state: 3}"])
def test_missing_or_garbage_state_gets_the_unknown_warning_never_silence(run, ms):
    assert run(f"marketWarning({ms}, 230500)") == "장 상태를 확인하지 못했어요. 체결가는 주문 시점 시세로 정해져요."


@needs_node
@pytest.mark.parametrize("price", ["undefined", "null", "NaN", "'x'"])
def test_after_market_warning_never_prints_a_bad_price(run, price):
    text = run(f"marketWarning({_ms('after')}, {price})")
    assert text == "애프터마켓이에요. 체결가는 정규장 종가로 정해져요." and "NaN" not in text and "undefined" not in text


# ── 차단 판단 ──


@needs_node
@pytest.mark.parametrize("state,allow,blocked", [
    ("pre", "false", True), ("after", "false", True), ("closed", "false", True),
    ("regular", "false", False), ("unknown", "false", False),      # 정규장·모르는 값은 막지 않는다
    ("pre", "true", False), ("after", "true", False), ("closed", "true", False),
    ("closed", "undefined", False), ("closed", "null", False),     # 설정이 없으면 기본(허용)
])
def test_order_block_table(run, state, allow, blocked):
    assert run(f"orderBlock({_ms(state)}, {allow})") == (BLOCK if blocked else None)


@needs_node
@pytest.mark.parametrize("ms", ["null", "undefined", "{}"])
def test_order_block_with_no_state_is_not_blocked(run, ms):
    assert run(f"orderBlock({ms}, false)") is None


def test_block_message_is_identical_to_the_servers():
    server = (ROOT / "backend" / "orders.py").read_text(encoding="utf-8")
    server_text = re.search(r'MARKET_BLOCK_MESSAGE = "([^"]+)"', server).group(1)
    assert server_text == BLOCK
    assert f"'{server_text}'" in _section("market-logic")


# ── 확인창 ──


@needs_node
def test_confirm_cfgs_carry_warn_and_default_to_empty(run):
    assert run("buyConfirmCfg('HMM', 2, {total: 1, remaining: 2})")["warn"] == ""
    assert run("buyConfirmCfg('HMM', 2, {total: 1, remaining: 2}, 'W')")["warn"] == "W"
    assert run("sellConfirmCfg('A', 1, false, {net: 1, pnl: 2})")["warn"] == ""
    assert run("sellConfirmCfg('A', 1, false, {net: 1, pnl: 2}, 'W')")["warn"] == "W"


@needs_node
def test_trade_view_shows_warn_only_while_confirming(run):
    cfg = "buyConfirmCfg('HMM', 2, {total: 1, remaining: 2}, 'W')"
    assert run(f"tradeView({cfg}, 'confirm')")["warn"] == "W"
    assert run(f"tradeView({cfg}, 'busy')")["warn"] == ""
    assert run(f"tradeView({cfg}, 'error', 'x')")["warn"] == ""


def test_trade_modal_has_a_warn_slot_between_lead_and_summary():
    s = _html()
    assert s.index('id="tradeDesc"') < s.index('id="tradeWarn"') < s.index('id="tradeSummary"')
    body = _func("renderTradeDialog")
    assert "tradeWarn" in body and "v.warn" in body


def test_execute_buy_and_sell_refresh_a_non_regular_state_before_blocking_or_warning():
    # 화면이 들고 있는 상태는 묵을 수 있다(추천 캐시 5분, 검색 상세·매수 시트는 한 번 받은 뒤 그대로, 백그라운드 PWA).
    # 묵은 pre/closed 로 정규장 주문을 막거나 틀린 경고를 보이지 않도록, 정규장이 아닌 상태일 때만 그 종목의 상태를 새로 받아 판단한다
    for func, item in (("executeInlineBuy", "item"), ("executeSell", "h")):
        body = _func(func)
        assert f"let ms = {item}.market_state;" in body
        assert re.search(r"if \(orderBlock\(ms, false\)\)\s*ms = await freshMarketState\(ms, ", body)
        assert f"`/api/stock/${{{item}.code}}`" in body
        assert "orderBlock(ms, userSettings.allow_closed_trading)" in body
        assert body.index("freshMarketState(") < body.index("orderBlock(ms, userSettings") < body.index("openTradeConfirm(")
        assert re.search(r"showToast\(block, 'error'\);\s*return;", body)
        assert f"marketWarning(ms, {item}.current_price)" in body


@needs_node
def test_fresh_state_replaces_a_stale_one_and_falls_back_when_it_cannot_be_had(run):
    stale = _ms("closed")
    assert run(f"freshMarketState({stale}, async () => ({_ms('regular')}))") == {"state": "regular", "nxt_listed": True}
    # 새로 받은 값이 unknown 이어도 그것이 더 신선하다
    assert run(f"freshMarketState({stale}, async () => ({_ms('unknown')}))")["state"] == "unknown"
    # 못 받거나(예외) 모양이 이상하면 가지고 있던 값을 쓴다
    assert run(f"freshMarketState({stale}, async () => {{ throw new Error('x'); }})")["state"] == "closed"
    for bad in ("null", "undefined", "{}", "'after'", "{state: 3}"):
        assert run(f"freshMarketState({stale}, async () => ({bad}))")["state"] == "closed"


@needs_node
def test_api_409_message_reaches_the_dialog_as_is(tmp_path):
    f = tmp_path / "t.js"
    f.write_text(_func("formatApiError") + f"\nconsole.log(JSON.stringify(formatApiError(409, {{detail: {json.dumps(BLOCK, ensure_ascii=False)}}})));\n", encoding="utf-8")
    out = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == BLOCK


# ── 내 메뉴 토글 ──


def test_menu_row_follows_the_notification_row():
    s = _html()
    assert s.index('id="notifBtn"') < s.index('id="closedTradingBtn"') < s.index('id="authMenuBtn"')
    row = s[s.index('id="closedTradingBtn"'):s.index("</button>", s.index('id="closedTradingBtn"'))]
    assert 'role="menuitem"' in s[s.rfind("<button", 0, s.index('id="closedTradingBtn"')):s.index('id="closedTradingBtn"')] + row
    assert "장 마감 중 거래" in row and 'id="closedTradingState"' in row and "toggleClosedTrading()" in row


def test_toggle_posts_the_opposite_value_and_trusts_the_server_answer():
    body = _func("toggleClosedTrading")
    assert "api('/api/settings'" in body and "method: 'POST'" in body and "allow_closed_trading: next" in body
    assert "acceptSettings(data)" in body and "updateClosedTradingMenu()" in body  # 서버 응답(검사를 통과한 것)으로 화면을 바꾼다
    assert "optimistic" not in body.lower()
    state = _func("updateClosedTradingMenu")
    assert "허용" in state and "차단" in state


def test_session_load_fills_the_settings_from_me():
    body = _func("loadSession")
    assert "acceptSettings(data)" in body and "userSettings" in body and "updateClosedTradingMenu()" in body
    assert re.search(r"let userSettings = \{\s*allow_closed_trading: true\s*\};", _html())  # 기본은 허용


# ── 차단 안내 토스트가 매수 시트 위에 보여야 한다 ──


def _z(element_id):
    s = _html()
    i = s.index(f'id="{element_id}"')
    tag = s[s.rfind("<", 0, i):s.index(">", i)]
    m = re.search(r"(?<![\w-])z-(?:\[(\d+)\]|(\d+))(?=[\s\"])", tag)
    assert m, f"{element_id} 에 z-index 가 없습니다"
    return int(m.group(1) or m.group(2))


def test_toast_is_above_every_dialog_so_the_block_notice_shows_over_the_buy_sheet():
    # 차단 안내는 매수 시트가 열린 채로 뜬다. 토스트가 시트(z-50)와 같은 층이면 DOM 순서상 시트에 가려진다
    toast = _z("toastNotification")
    assert all(toast > _z(i) for i in ("buyModal", "tradeModal", "marketHoursModal", "resetModal"))
