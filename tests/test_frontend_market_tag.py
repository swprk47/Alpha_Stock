"""종목 상세의 장 상태 태그(정규장·프리마켓·애프터마켓·장 마감).

태그는 버튼이고 누르면 "장 시간 안내" 팝업이 열린다. 붙는 곳: 모바일 매수 시트 제목줄(종목 카드 안 칩 줄은 이미 빽빽해서),
PC 추천·검색·보유 상세 헤더의 칩 줄 끝. 목록 행(추천·보유·검색 드롭다운)에는 붙이지 않는다. 모르는 값이면 태그를 달지 않는다.
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


@pytest.fixture
def run(tmp_path):
    # marketTagHtml 은 tag-logic 에 있고 sessionTag·MARKET_COLORS 는 market-logic 에 있다
    src = "\n".join([_section("tag-logic"), _section("market-logic")])

    def _run(expr):
        f = tmp_path / "t.js"
        f.write_text(src + f"\nconsole.log(JSON.stringify({expr}));\n", encoding="utf-8")
        out = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    return _run


# ── 태그 HTML ──


@needs_node
@pytest.mark.parametrize("state,label,color", [
    ("regular", "정규장", "#30d158"), ("pre", "프리마켓", "#64d2ff"),
    ("after", "애프터마켓", "#bf5af2"), ("closed", "장 마감", "#8e8e93"),
])
def test_tag_html_per_state(run, state, label, color):
    html = run(f"marketTagHtml({{state: '{state}', nxt_listed: true}})")
    assert html.startswith("<button") and 'type="button"' in html
    assert label in html and 'aria-label="장 시간 안내 열기"' in html
    assert f"openMarketHours('{state}', true)" in html
    assert color in html  # 색과 글자를 함께 쓴다


@needs_node
def test_tag_passes_the_nxt_flag_exactly(run):
    assert "openMarketHours('after', false)" in run("marketTagHtml({state: 'after', nxt_listed: false})")
    assert "openMarketHours('after', false)" in run("marketTagHtml({state: 'after'})")
    assert "openMarketHours('after', false)" in run("marketTagHtml({state: 'after', nxt_listed: 'true'})")


@needs_node
@pytest.mark.parametrize("ms", ["null", "undefined", "{}", "{state: 'unknown'}", "{state: 'weird'}", "'after'"])
def test_tag_html_is_empty_for_unknown_or_missing(run, ms):
    assert run(f"marketTagHtml({ms})") == ""


def test_tag_text_is_at_least_13px():
    body = _func("marketTagHtml")
    assert re.findall(r"text-\[(\d+)px\]", body) and all(int(n) >= 13 for n in re.findall(r"text-\[(\d+)px\]", body))


# ── 붙는 곳 ──


def test_mobile_sheet_title_row_has_the_tag_slot():
    s = _html()
    i = s.index('id="buyModalTitle"')
    assert 'id="buyMarketTag"' in s[i:i + 400]               # 제목 바로 옆(같은 줄)
    assert 'id="buyMarketTag"' not in s[s.index('id="buyStockName"') - 300:s.index('id="buyStockName"') + 600]  # 종목 카드 칩 줄이 아니다
    assert "marketTagHtml(stockItem.market_state)" in _func("openCustomBuyModal")
    assert re.search(r"getElementById\('buyMarketTag'\)\.innerHTML\s*=\s*marketTagHtml\(", _func("openCustomBuyModal"))


@pytest.mark.parametrize("func,expr", [
    ("recDetailHtml", "item.market_state"),
    ("searchDetailHtml", "stock.market_state"),
    ("holdingDetailHtml", "h.market_state"),
])
def test_pc_headers_put_the_tag_at_the_end_of_the_chip_line(func, expr):
    body = _func(func)
    assert f"marketTagHtml({expr})" in body
    assert body.index("securityTagHtml(") < body.index("marketTagHtml(")
    chip_line = body[body.index("securityTagHtml("):body.index("marketTagHtml(")]
    assert "</h2>" not in chip_line and "text-2xl" not in chip_line  # 같은 칩 줄 안이다


@pytest.mark.parametrize("func", ["renderRecommendations", "renderHoldings", "renderSearchResults"])
def test_list_rows_do_not_get_the_tag(func):
    assert "marketTagHtml" not in _func(func)
