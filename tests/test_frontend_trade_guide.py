"""내 메뉴의 '거래 안내' 팝업: 수수료·세금·스윙 룰을 서버(/api/trade-rules)에서 받아 보여 준다.

- 팝업은 '장 시간 안내'와 같은 모양(440px)이고, 메뉴의 '장 마감 중 거래'와 '로그아웃' 사이 항목으로 연다.
- 숫자는 화면에 적어 두지 않는다. 받는 중·실패일 때 숫자를 지어내지 않고, 실패하면 다시 시도할 수 있다.
- Escape·Tab·포커스는 다른 팝업과 같은 규칙을 따른다(매수 시트 위에서도 팝업만 닫는다).
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

RULES = "{buy_fee_pct: 0.015, sell_fee_pct: 0.015, sell_tax_pct: 0.2, target_pct: 6.5, stop_pct: -3, max_hold_days: 5}"


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


def _node(script, tmp_path):
    f = tmp_path / "t.js"
    f.write_text(script, encoding="utf-8")
    out = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


# ── 마크업 ──


def test_menu_item_sits_between_closed_trading_and_logout():
    s = _html()
    menu = s[s.index('id="userMenu"'):s.index("<!-- /userMenu -->")]
    assert menu.index('id="closedTradingBtn"') < menu.index("openTradeGuide()") < menu.index('id="authMenuBtn"')
    item = re.search(r'<button[^>]*openTradeGuide\(\)[^>]*>.*?</button>', menu, re.S).group(0)
    assert 'role="menuitem"' in item and "closeMenu()" in item and "min-h-[44px]" in item
    assert "거래 안내" in item and "수수료·스윙 룰" in item


def test_modal_markup_follows_the_market_hours_popup():
    s = _html()
    modal = s[s.index('id="tradeGuideModal"'):]
    modal = modal[:modal.index("<!-- 💰")] if "<!-- 💰" in modal else modal[:3000]
    assert "hidden" in re.search(r'id="tradeGuideModal"[^>]*class="([^"]*)"', s).group(1).split()
    assert "closeTradeGuide()" in re.search(r'id="tradeGuideModal"[^>]*>', s).group(0)  # 바깥을 누르면 닫는다
    assert 'role="dialog"' in modal and 'aria-modal="true"' in modal and 'aria-labelledby="tradeGuideTitle"' in modal
    # 모바일에서는 좌우 여백을 넓혀 가로를 줄이고(32px), 한 칸 넓은 화면(sm 이상)부터 기본 여백(16px)
    backdrop_class = re.search(r'id="tradeGuideModal"[^>]*class="([^"]*)"', s).group(1).split()
    assert "px-8" in backdrop_class and "sm:px-4" in backdrop_class and "py-4" in backdrop_class and "p-4" not in backdrop_class
    assert "max-w-[440px]" in modal and "z-[65]" in s[s.index('id="tradeGuideModal"') - 10:s.index('id="tradeGuideModal"') + 200]
    assert 'id="tradeGuideTitle"' in modal and "거래 안내" in modal
    close = re.search(r'<button[^>]*id="tradeGuideCloseBtn"[^>]*>', modal).group(0)
    assert 'aria-label="닫기"' in close and "closeTradeGuide()" in close and "w-11 h-11" in close
    assert 'id="tradeGuideBody"' in modal


# ── 표시 형식·본문 ──


@needs_node
def test_rate_and_swing_formats(tmp_path):
    out = _node(_section("trade-guide-logic") + """
console.log(JSON.stringify([tgRate(0.015), tgRate(0.2), tgRate(0.03), tgRate(0.1), tgRate(0.0123), tgSwing(6.5), tgSwing(-3), tgSwing(0)]));
""", tmp_path)
    assert out == ["0.015", "0.20", "0.03", "0.10", "0.0123", "+6.5", "-3.0", "0.0"]


@needs_node
def test_rules_validation_rejects_anything_that_is_not_a_full_set_of_numbers(tmp_path):
    out = _node(_section("trade-guide-logic") + f"""
const good = {RULES};
const bad = (patch) => tgRulesValid(Object.assign({{}}, good, patch));
console.log(JSON.stringify([tgRulesValid(good), tgRulesValid(null), tgRulesValid({{}}), bad({{buy_fee_pct: '0.015'}}),
  bad({{sell_tax_pct: NaN}}), bad({{target_pct: null}}), bad({{max_hold_days: Infinity}}), bad({{stop_pct: undefined}})]));
""", tmp_path)
    assert out == [True, False, False, False, False, False, False, False]


@needs_node
def test_ready_body_shows_the_server_numbers_and_the_caveats(tmp_path):
    out = _node(_section("trade-guide-logic") + f"""
console.log(JSON.stringify(tgBodyHtml({{status: 'ready', rules: {RULES}}})));
""", tmp_path)
    for text in ("수수료와 세금", "매수 수수료", "0.015%", "매도 수수료", "0.20%", "증권거래세·농어촌특별세 합계",
                 "스윙 룰", "+6.5%", "-3.0%", "5영업일", "코넥스", "모의투자 계산 기준"):
        assert text in out, text
    assert "[" not in re.sub(r"<[^>]*>", "", out)  # 자리표시가 남아 있지 않다
    # 한글 문장이 "있어 / 요."처럼 단어 중간에서 끊기지 않게 한다
    assert out.count("word-break: keep-all") >= 3


@needs_node
def test_loading_and_failed_bodies_never_show_numbers(tmp_path):
    out = _node(_section("trade-guide-logic") + """
console.log(JSON.stringify({loading: tgBodyHtml({status: 'loading'}), failed: tgBodyHtml({status: 'failed'}), unknown: tgBodyHtml(null)}));
""", tmp_path)
    assert "불러오는 중" in out["loading"] and 'aria-busy="true"' in out["loading"]
    assert "불러오지 못했어요" in out["failed"] and 'onclick="retryTradeGuide()"' in out["failed"] and "min-h-[44px]" in out["failed"]
    for html in out.values():
        assert not re.search(r"\d+\.\d+%", html) and "영업일" not in html
    assert "불러오지 못했어요" in out["unknown"]  # 모르는 상태는 숫자 대신 오류로 본다


# ── 불러오기 ──


def _loader(extra):
    return f"""
{_section('trade-guide-logic')}
let tradeGuideRules = null, tradeGuideFailed = false, tradeGuideReq = 0;
let renders = 0;
function renderTradeGuide() {{ renders++; }}
const calls = [], pending = [];
function api(path) {{ calls.push(path); return new Promise((res, rej) => pending.push({{res, rej}})); }}
{_func('loadTradeGuide')}
{extra}
"""


def test_loader_uses_the_api_helper_and_a_request_counter():
    body = _func("loadTradeGuide")
    assert "api('/api/trade-rules')" in body and "++tradeGuideReq" in body and "req !== tradeGuideReq" in body


@needs_node
def test_success_is_cached_and_validated(tmp_path):
    out = _node(_loader(f"""
(async () => {{
  const a = loadTradeGuide(); pending[0].res({{success: true, rules: {RULES}}}); await a;
  await loadTradeGuide();               // 받아 둔 값이 있으면 다시 받지 않는다
  const b = loadTradeGuide(true); pending[1].res({{success: true, rules: {RULES}}}); await b;  // 다시 시도는 강제로 받는다
  console.log(JSON.stringify({{calls: calls.length, ok: !!tradeGuideRules, failed: tradeGuideFailed}}));
}})();
"""), tmp_path)
    assert out == {"calls": 2, "ok": True, "failed": False}


@needs_node
def test_failures_and_malformed_responses_mark_failed_without_data(tmp_path):
    out = _node(_loader("""
(async () => {
  const a = loadTradeGuide(); pending[0].rej(new Error('network')); await a;
  const r1 = {failed: tradeGuideFailed, rules: tradeGuideRules};
  const b = loadTradeGuide(); pending[1].res({success: true, rules: {buy_fee_pct: 'x'}}); await b;
  const r2 = {failed: tradeGuideFailed, rules: tradeGuideRules};
  const c = loadTradeGuide(); pending[2].res({success: false}); await c;
  console.log(JSON.stringify({r1, r2, r3: {failed: tradeGuideFailed, rules: tradeGuideRules}}));
})();
"""), tmp_path)
    for key in ("r1", "r2", "r3"):
        assert out[key] == {"failed": True, "rules": None}, key


@needs_node
def test_a_stale_response_does_not_overwrite_a_newer_request(tmp_path):
    out = _node(_loader(f"""
(async () => {{
  const a = loadTradeGuide(); const b = loadTradeGuide(true);
  pending[1].res({{success: true, rules: {RULES}}}); await b;
  pending[0].rej(new Error('late'));  await a;   // 먼저 보낸 요청의 늦은 실패가 성공한 결과를 덮지 않는다
  console.log(JSON.stringify({{ok: !!tradeGuideRules, failed: tradeGuideFailed}}));
}})();
"""), tmp_path)
    assert out == {"ok": True, "failed": False}


# ── 열기·닫기·키보드 ──


def test_open_and_close_follow_the_market_hours_popup():
    opened = _func("openTradeGuide")
    assert "tradeGuideReturnFocus" in opened and "classList.remove('hidden')" in opened
    assert "loadTradeGuide(" in opened and "tradeGuideCloseBtn" in opened and ".focus()" in opened
    closed = _func("closeTradeGuide")
    assert "classList.add('hidden')" in closed and "tradeGuideReturnFocus.focus()" in closed
    assert "tradeGuideIsOpen()" in closed
    assert "loadTradeGuide(true)" in _func("retryTradeGuide")


def test_escape_and_tab_handling_include_the_new_popup():
    s = _html()
    assert s.count("['tradeModal', 'resetModal', 'marketHoursModal', 'tradeGuideModal']") == 2  # Escape 와 매수 시트의 Tab 순환
    assert "closeTradeGuide();" in s[s.index("if (e.key === 'Escape')"):s.index("if (e.key === 'Tab')")]
    assert "trapGuideFocus(e)" in s[s.index("if (e.key === 'Tab')"):s.index("if (e.key === 'Tab')") + 200]
    trap = _func("trapGuideFocus")
    assert "tradeGuideModal" in trap and "preventDefault()" in trap
