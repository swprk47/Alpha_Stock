"""오늘 등락률 옆에 전일 대비 금액을 붙인다: "+4.2% (5,000원)" (방향은 퍼센트 앞 부호가 말하므로 금액에는 부호 없음).

서버가 주는 change_amount 가 없으면(null·옛 응답·부호 검증 실패) 지금처럼 "+4.2%" 만 보인다.
붙이는 곳: 검색 드롭다운, 추천 상세 헤더, 검색 상세 헤더, 모바일 매수 시트. 추천 목록 행의 알약은 폭 때문에 %만 둔다.
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
    src = _section("change-logic")

    def _run(expr):
        f = tmp_path / "t.js"
        f.write_text(src + f"\nconsole.log(JSON.stringify({expr}));\n", encoding="utf-8")
        out = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    return _run


# ── 문구 함수 ──


@needs_node
@pytest.mark.parametrize("rate,amount,expected", [
    (4.2, 5000, "+4.2% (5,000원)"),       # 방향은 퍼센트 앞의 부호가 말하므로 금액에는 부호를 달지 않는다
    (-5.37, -13000, "-5.37% (13,000원)"),
    (0, 0, "+0% (0원)"),                  # 보합: 지금 코드가 0 도 "+0%" 로 쓴다
    (1.2, 1234567, "+1.2% (1,234,567원)"),
    (-0.08, -20, "-0.08% (20원)"),
])
def test_text_with_amount(run, rate, amount, expected):
    assert run(f"changeText({rate}, {amount})") == expected


@needs_node
@pytest.mark.parametrize("amount", ["null", "undefined", "'5000'", "NaN", "1.5", "Infinity"])
def test_text_without_a_usable_amount_is_the_old_percent_only_text(run, amount):
    assert run(f"changeText(4.2, {amount})") == "+4.2%"
    assert run(f"changeText(-4.2, {amount})") == "-4.2%"


@needs_node
def test_separator_can_be_a_line_break_for_narrow_columns(run):
    assert run("changeText(4.2, 5000, '\\n')") == "+4.2%\n(5,000원)"
    assert run("changeText(4.2, null, '\\n')") == "+4.2%"  # 금액이 없으면 구분자는 쓰이지 않는다


@needs_node
def test_percent_part_is_identical_to_the_old_expression(run):
    # 옛 식: `${isGain ? '+' : ''}${rate}%`
    for rate in (0, 1.5, -2, 29.99, -0.01, 12):
        old = ("+" if rate >= 0 else "") + (str(rate)) + "%"
        assert run(f"changeText({rate}, null)") == old


@needs_node
def test_amount_part_carries_no_sign_of_its_own(run):
    assert run("changeText(3, 100)").endswith("(100원)")
    assert run("changeText(-3, -100)").endswith("(100원)")
    # 퍼센트 앞 부호만 남는다: 문자열 안의 부호는 퍼센트 쪽 하나뿐
    assert len(re.findall(r"[+-]", run("changeText(-3, -100)"))) == 1
    assert len(re.findall(r"[+-]", run("changeText(3, 100)"))) == 1


# ── 화면에 붙인 곳 ──


def test_search_dropdown_shows_the_amount_next_to_the_rate():
    body = _func("renderSearchResults")
    assert "changeText(item.change_rate, item.change_amount)" in body
    assert "${changeSign}${item.change_rate}%" not in body


def test_recommendation_detail_header_shows_the_amount():
    body = _func("recDetailHtml")
    assert "changeText(item.change_rate, item.change_amount)" in body


def test_search_detail_header_shows_the_amount():
    body = _func("searchDetailHtml")
    assert "changeText(stock.change_rate, stock.change_amount)" in body


def test_mobile_buy_sheet_shows_the_amount_on_its_own_line():
    # 375px 시트의 종목 카드는 가격 칸이 넓어지면 이름이 세 줄로 꺾인다 → 퍼센트 아래 줄에 금액
    body = _func("openCustomBuyModal")
    assert "changeText(stockItem.change_rate, stockItem.change_amount, '\\n')" in body
    assert "whitespace-pre-line" in body[body.index("buyStockChange"):]


def test_recommendation_list_pill_keeps_the_percent_only_text():
    # 알약은 고정 폭의 색 박스라 금액을 넣지 않는다(상세 헤더에서 본다)
    body = _func("renderRecommendations")
    assert "${changeSign}${item.change_rate}%" in body
    assert "change_amount" not in body
