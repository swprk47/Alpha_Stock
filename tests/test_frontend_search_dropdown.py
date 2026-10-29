"""검색 드롭다운 행 레이아웃 (시안: 이름 / 메타 두 줄).

이름이 긴 ETF 가 많이 나오면서 한 줄에 이름·시장·뱃지를 담던 옛 구조가 모바일에서 뱃지("10만원 적합")와
가격("25,470원")을 줄바꿈시켰다. 이름은 최대 두 줄, 코드·시장·ETF 칩·뱃지는 아래 메타 한 줄(모자라면 줄바꿈),
가격 칸은 줄어들지도 줄바꿈되지도 않게 한다.
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


ITEMS = [
    {"code": "360750", "name": "TIGER 미국S&P500", "market": "KOSPI", "current_price": 25470, "change_rate": -0.49,
     "budget_status": "FIT_SPLIT", "logo_url": "", "security_type": "etf"},
    {"code": "381180", "name": "TIGER 미국필라델피아반도체나스닥", "market": "KOSPI", "current_price": 39550, "change_rate": 1.2,
     "budget_status": "FIT_SPLIT", "logo_url": "", "security_type": "etf"},
    {"code": "064400", "name": "LG씨엔에스", "market": "KOSPI", "current_price": 79500, "change_rate": 5.86,
     "budget_status": "FIT_SINGLE", "logo_url": "", "security_type": "stock"},
    {"code": "005930", "name": "삼성전자", "market": "KOSPI", "current_price": 245000, "change_rate": 0,
     "budget_status": "OVER_BUDGET", "logo_url": "", "security_type": "stock"},
]


@pytest.fixture
def render(tmp_path):
    """renderSearchResults 를 DOM 없이 실행해 만든 HTML 을 돌려준다(로고·종류 칩 함수는 실제 구간을 쓴다)."""
    base = "\n".join([_section("logo-logic"), _section("tag-logic"), _section("change-logic"), _func("renderSearchResults")])

    def _render(items):
        script = (
            "const dd = { innerHTML: '', classList: { add() {}, remove() {} } };\n"
            "const document = { getElementById: () => dd };\n"
            + base
            + f"\nrenderSearchResults({json.dumps(items, ensure_ascii=False)});\nconsole.log(JSON.stringify(dd.innerHTML));\n"
        )
        f = tmp_path / "t.js"
        f.write_text(script, encoding="utf-8")
        out = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    return _render


def _rows(html):
    """행(onclick 이 달린 최상위 div)별로 나눈다."""
    parts = re.split(r'(?=<div onclick="selectSearchResult)', html)
    return [p for p in parts if p.strip().startswith("<div onclick")]


# ── 소스 구조 ──


def test_name_is_alone_on_its_line_and_limited_to_two_lines():
    body = _func("renderSearchResults")
    h4 = re.search(r"<h4[^>]*>(.*?)</h4>", body, re.S)
    assert h4 and "${item.name}" in h4.group(1) and "market" not in h4.group(1) and "budgetBadge" not in h4.group(1)
    assert "line-clamp-2" in h4.group(0)
    # 이름 줄 바로 옆에 시장·뱃지가 오지 않는다(옛 구조)
    before_h4 = body[:body.index("<h4")]
    assert "${item.market}" not in before_h4.split("return `")[-1]


def test_meta_line_holds_code_market_kind_chip_and_budget_badge_in_that_order():
    body = _func("renderSearchResults")
    meta = body[body.index("</h4>"):]
    order = [meta.index(x) for x in ("${item.code}", "${item.market}", "securityTagHtml(item.security_type)", "${budgetBadge}")]
    assert order == sorted(order)
    assert "flex-wrap" in meta[:meta.index("${item.code}")]  # 모자라면 칩·뱃지가 다음 줄로


def test_every_budget_badge_keeps_its_text_in_one_piece():
    body = _func("renderSearchResults")
    badges = re.findall(r"budgetBadge = '(<span[^']*</span>)'", body)
    assert len(badges) == 3
    assert all("whitespace-nowrap" in b for b in badges)


def test_price_column_never_shrinks_or_wraps():
    body = _func("renderSearchResults")
    price = body[body.index('class="text-right'):]
    tag = price[:price.index(">")]
    assert "shrink-0" in tag and "whitespace-nowrap" in tag


def test_text_column_can_shrink_so_the_price_keeps_its_space():
    body = _func("renderSearchResults")
    assert re.search(r'class="[^"]*\bmin-w-0\b[^"]*\bflex-1\b|class="[^"]*\bflex-1\b[^"]*\bmin-w-0\b', body)


def test_row_still_selects_the_stock_and_keeps_the_logo_and_touch_feedback():
    body = _func("renderSearchResults")
    assert "selectSearchResult('${item.code}', '${String(item.market || '').replace(/[^A-Za-z]/g, '')}')" in body
    assert "cursor-pointer" in body and "tap-press" in body
    assert "logoHtml(item.code, item.name, 28, item.logo_url)" in body


def test_dropdown_is_taller_on_phones_and_unchanged_on_pc():
    s = _html()
    i = s.index('id="searchDropdown"')
    tag = s[s.rfind("<", 0, i):s.index(">", i) + 1]
    assert "max-h-[70vh]" in tag and "lg:max-h-80" in tag  # 모바일은 화면의 70%, PC 는 예전 320px
    assert "max-h-80 " not in tag.replace("lg:max-h-80", "")  # 모바일에 예전 320px 제한이 남아 있지 않다
    assert "lg:w-[400px]" in tag and "lg:left-auto" in tag  # 기존 PC 폭 규칙은 그대로


# ── 실제로 그린 HTML ──


@needs_node
def test_rendered_rows_follow_the_new_structure(render):
    rows = _rows(render(ITEMS))
    assert len(rows) == 4
    for row, item in zip(rows, ITEMS):
        assert row.count("<h4") == 1
        name_end = row.index("</h4>")
        assert item["name"] in row[:name_end]
        assert "10만원 적합" not in row[:name_end] and "1주 가능" not in row[:name_end] and "10만 초과" not in row[:name_end]
        meta = row[name_end:]
        assert item["code"] in meta and "KOSPI" in meta


@needs_node
def test_rendered_badges_and_price_text(render):
    rows = _rows(render(ITEMS))
    assert "10만원 적합" in rows[0] and "10만원 적합" in rows[1]
    assert "1주 가능" in rows[2] and "10만 초과" in rows[3]
    assert "25,470원" in rows[0] and "245,000원" in rows[3]
    # 가격과 등락률은 같은 칸(줄어들지 않는 칸) 안에 있다
    price_col = rows[0][rows[0].index("25,470원") - 200:]
    assert "shrink-0" in price_col and "whitespace-nowrap" in price_col and "-0.49%" in rows[0]


@needs_node
def test_rendered_etf_chip_only_for_etfs_and_it_is_on_the_meta_line(render):
    rows = _rows(render(ITEMS))
    assert ">ETF</span>" in rows[0] and ">ETF</span>" in rows[1]
    assert ">ETF</span>" not in rows[2] and ">ETF</span>" not in rows[3]
    assert rows[0].index(">ETF</span>") > rows[0].index("</h4>")  # 이름 줄을 밀지 않는다


@needs_node
def test_rendered_gain_loss_colours_and_signs(render):
    rows = _rows(render(ITEMS))
    assert "text-[#5aa9ff]" in rows[0] and "-0.49%" in rows[0]
    assert "text-[#ff6a60]" in rows[1] and "+1.2%" in rows[1]


@needs_node
def test_empty_results_message_is_unchanged(render):
    assert "검색 결과가 없습니다." in render([])
