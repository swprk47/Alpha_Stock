"""모바일 매수 시트의 [시세·매수 | 개요] 탭과 개요 불러오기(상태는 DOM 밖 변수).

- 시트는 열 때마다 "시세·매수" 탭으로 시작하고, 개요 탭에서는 제목이 "종목 정보"로 바뀐다. 가격 머리는 탭과 상관없이 그대로다.
- 개요는 처음 열 때만(5분 안에는 다시 받지 않음) 받고, 종목을 연달아 바꿔도 늦게 온 응답이 화면을 덮지 않는다.
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
    assert m, f"{tag} 구간이 없습니다"
    return m.group(1)


# ── 마크업 ──


def test_sheet_markup_has_tabs_between_header_card_and_body():
    s = _html()
    price = s.index('id="buyStockPrice"')
    tabs = s.index('id="buyTabs"')
    trade = s.index('id="buyTradeBody"')
    overview = s.index('id="buyOverviewBody"')
    assert price < tabs < trade < overview
    # 차트·AI 진단·매수 패널은 시세·매수 본문 안, 개요 본문은 그 밖
    for inner in ('id="buyModalChartWrap"', 'id="gradeCard"', 'id="buySheetPanel"'):
        assert trade < s.index(inner) < overview, inner
    # 종목 이름·가격 머리는 탭 위에 있고 탭과 상관없이 보인다
    assert s.index('id="buyStockName"') < tabs and 'id="buyStockPrice"' not in s[trade:overview]
    assert re.search(r'id="buyOverviewBody"[^>]*class="[^"]*\bhidden\b', s)  # 처음에는 감춰져 있다


# ── 열고 닫을 때 ──


def test_opening_always_starts_on_trade_tab():
    body = _func("openCustomBuyModal")
    assert "overviewTab = 'trade'" in body and "overviewAboutOpen = false" in body and "++overviewReq" in body
    assert body.index("overviewTab = 'trade'") < body.index("classList.remove('hidden')")
    assert body.index("applyBuyTab()") > body.index("buySheetPanel")  # 시트 내용을 채운 뒤 탭을 맞춘다


def test_close_resets_tab_and_invalidates_requests():
    body = _func("closeBuyModal")
    assert "overviewTab = 'trade'" in body and "overviewAboutOpen = false" in body and "++overviewReq" in body


# ── 탭 전환 ──


def test_apply_buy_tab_switches_title_subtitle_and_bodies():
    body = _func("applyBuyTab")
    for text in ("종목 정보", "종목 매수", "이 종목이 어떤 종목인지 살펴봐요", "시드머니 맞춤 매수 시뮬레이션"):
        assert text in body, text
    assert "buyModalTitle" in body and "buyModalSubtitle" in body
    assert "buyTradeBody" in body and "buyOverviewBody" in body and "ovTabsHtml(overviewTab)" in body
    assert "ovBodyHtml(" in body and "layout: 'one-col'" in body and "aboutOpen: overviewAboutOpen" in body
    assert "drawInteractiveChart" in body  # 시세·매수 탭으로 돌아오면 차트를 다시 그린다(감춰져 있던 캔버스)


def test_select_tab_resets_scroll_and_loads_overview():
    body = _func("selectOverviewTab")
    assert "ovNextTab(overviewTab, tab)" in body and "overviewAboutOpen = false" in body
    assert "scrollTop = 0" in body and "loadOverview(" in body and "refreshOverviewViews()" in body


def test_toggle_about_and_retry():
    assert "overviewAboutOpen = !overviewAboutOpen" in _func("toggleOverviewAbout")
    retry = _func("retryOverview")
    assert "loadOverview(" in retry and "true" in retry


# ── 불러오기 ──


def _loader_script(extra):
    """loadOverview 를 가짜 api 와 함께 node 로 돌린다(상태 변수는 최상위 let)."""
    head = f"""
{_section('overview-logic')}
let overviewTab = 'overview';
let overviewData = {{}};
let overviewFailed = {{}};
let overviewReq = 0;
let overviewInflight = {{}};
let refreshes = 0;
function refreshOverviewViews() {{ refreshes++; }}
const calls = [];
const pending = {{}};
function api(path) {{ calls.push(path); return new Promise((res, rej) => {{ pending[path] = {{ res, rej }}; }}); }}
{_func('loadOverview')}
"""
    return head + extra


def _run(script, tmp_path):
    f = tmp_path / "t.js"
    f.write_text(script, encoding="utf-8")
    out = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


GOOD = "{success: true, kind: 'stock', about: {status: 'ok'}, facts: {status: 'ok'}, holdings: {status: 'empty'}, weights: {status: 'empty'}, news: {status: 'ok'}}"
WITH_ERR = "{success: true, kind: 'stock', about: {status: 'ok'}, facts: {status: 'ok'}, holdings: {status: 'empty'}, weights: {status: 'empty'}, news: {status: 'error'}}"


def test_load_overview_uses_api_helper_and_ignores_stale_responses_in_source():
    body = _func("loadOverview")
    assert "api(`/api/stock/${code}/overview`)" in body
    assert "req !== overviewReq" in body
    assert "err.status === 401" in body and "overviewTab = 'trade'" in body  # 로그인 창은 api() 가 띄운다. 개요 탭에 멈춰 있지 않게 되돌린다


@needs_node
def test_stale_response_for_an_earlier_request_is_discarded(tmp_path):
    script = _loader_script(f"""
(async () => {{
  const a = loadOverview('AAAAAA');
  const b = loadOverview('BBBBBB');
  pending['/api/stock/BBBBBB/overview'].res({GOOD});
  await b;
  pending['/api/stock/AAAAAA/overview'].res({GOOD});
  await a;
  console.log(JSON.stringify({{keys: Object.keys(overviewData), refreshes}}));
}})();
""")
    out = _run(script, tmp_path)
    assert out["keys"] == ["BBBBBB"]  # 늦게 도착한 A 는 현재 화면(B)을 덮지 못한다


@needs_node
def test_second_load_within_five_minutes_does_not_call_api(tmp_path):
    script = _loader_script(f"""
(async () => {{
  const first = loadOverview('AAAAAA');
  pending['/api/stock/AAAAAA/overview'].res({GOOD});
  await first;
  await loadOverview('AAAAAA');
  console.log(JSON.stringify({{calls: calls.length, hasError: overviewData.AAAAAA.hasError}}));
}})();
""")
    assert _run(script, tmp_path) == {"calls": 1, "hasError": False}


@needs_node
def test_retry_refetches_only_when_a_card_failed(tmp_path):
    script = _loader_script(f"""
(async () => {{
  const first = loadOverview('AAAAAA');
  pending['/api/stock/AAAAAA/overview'].res({WITH_ERR});
  await first;
  const flagged = overviewData.AAAAAA.hasError;
  const second = loadOverview('AAAAAA', true);
  pending['/api/stock/AAAAAA/overview'].res({GOOD});
  await second;
  await loadOverview('AAAAAA', true);
  console.log(JSON.stringify({{flagged, calls: calls.length, final: overviewData.AAAAAA.hasError}}));
}})();
""")
    assert _run(script, tmp_path) == {"flagged": True, "calls": 2, "final": False}  # 다시 시도는 실패가 있을 때만 다시 받는다


@needs_node
def test_network_failure_marks_the_code_failed_and_401_returns_to_trade(tmp_path):
    script = _loader_script("""
(async () => {
  const first = loadOverview('AAAAAA');
  pending['/api/stock/AAAAAA/overview'].rej(new Error('network'));
  await first;
  const failed = { failed: !!overviewFailed.AAAAAA, hasData: 'AAAAAA' in overviewData };
  const second = loadOverview('BBBBBB');
  const e = new Error('login'); e.status = 401;
  pending['/api/stock/BBBBBB/overview'].rej(e);
  await second;
  console.log(JSON.stringify({ failed, tab: overviewTab, bFailed: !!overviewFailed.BBBBBB, bData: 'BBBBBB' in overviewData }));
})();
""")
    out = _run(script, tmp_path)
    assert out["failed"] == {"failed": True, "hasData": False}
    assert out["tab"] == "trade" and out["bFailed"] is False and out["bData"] is False


@needs_node
def test_malformed_response_is_a_failure_not_a_guess(tmp_path):
    script = _loader_script("""
(async () => {
  const first = loadOverview('AAAAAA');
  pending['/api/stock/AAAAAA/overview'].res({ success: false });
  await first;
  console.log(JSON.stringify({ failed: !!overviewFailed.AAAAAA, hasData: 'AAAAAA' in overviewData }));
})();
""")
    assert _run(script, tmp_path) == {"failed": True, "hasData": False}


def test_overview_state_lives_outside_the_dom():
    s = _html()
    for decl in (r"let overviewTab = 'trade';", r"let overviewData = \{\};", r"let overviewReq = 0;", r"let overviewAboutOpen = false;", r"let overviewFailed = \{\};"):
        assert re.search(decl, s), decl
    # 최상위 선언이다(함수 안이 아니다): 들여쓰기 4칸, 다른 블록 밖
    assert re.search(r"^    let overviewTab = ", s, re.M)


def test_overview_view_for_maps_state_to_view():
    body = _func("overviewViewFor")
    assert "'ready'" in body and "'failed'" in body and "'loading'" in body
