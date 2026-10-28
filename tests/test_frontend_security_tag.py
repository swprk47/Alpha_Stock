"""ETF/ETN 태그 검증 (시안 '태그 C': 밝은 회색 채움).

서버가 주는 security_type(stock/etf/etn)만 믿고, 일반 주식이나 값이 없거나 이상한 값이면 태그를 그리지 않는다
(모르는 종목에 ETF 라고 틀리게 달지 않는다).
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
    m = re.search(r"// <tag-logic>\r?\n(.*?)// </tag-logic>", _html(), re.S)
    assert m, "index.html 에 tag-logic 구간이 없습니다"
    return m.group(1)


@pytest.fixture
def run(tmp_path):
    src = _logic()

    def _run(expr):
        f = tmp_path / "t.js"
        f.write_text(src + f"\nconsole.log(JSON.stringify({expr}));\n", encoding="utf-8")
        out = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    return _run


@needs_node
@pytest.mark.parametrize("kind,label", [("etf", "ETF"), ("etn", "ETN")])
def test_etf_and_etn_get_a_light_grey_tag(run, kind, label):
    html = run(f"securityTagHtml('{kind}')")
    assert f">{label}</span>" in html
    assert "bg-[#3a3a3c]" in html and "text-[#f5f5f7]" in html  # 시안 C: 색 의미 없는 밝은 회색 채움
    assert "whitespace-nowrap" in html  # 줄바꿈될 때 태그 글자가 쪼개지지 않는다
    assert "ring-1" in html and "ring-white/20" in html  # 선택된 행(밝은 배경)에서도 태그 모양이 보이게 안쪽 테두리


@needs_node
@pytest.mark.parametrize("value", ["'stock'", "''", "undefined", "null", "'ETF'", "'fund'", "123", "'<script>'", "['etf']"])
def test_everything_else_gets_no_tag(run, value):
    assert run(f"securityTagHtml({value})") == ""


@needs_node
def test_tag_keeps_the_same_shape_as_the_fractional_tag(run):
    html = run("securityTagHtml('etf')")
    for cls in ("px-1.5", "rounded", "font-semibold"):
        assert cls in html


# ── 붙인 곳 ──


@pytest.mark.parametrize("func,expr", [
    ("renderRecommendations", "item.security_type"),
    ("recDetailHtml", "item.security_type"),
    ("searchDetailHtml", "stock.security_type"),
    ("renderHoldings", "h.security_type"),
    ("holdingDetailHtml", "h.security_type"),
    ("renderSearchResults", "item.security_type"),
    ("openCustomBuyModal", "stockItem.security_type"),
])
def test_every_place_with_a_name_uses_the_shared_tag(func, expr):
    assert f"securityTagHtml({expr})" in _func(func), func


def test_kind_tag_comes_before_the_fractional_tag_in_the_detail_headers():
    for func in ("recDetailHtml", "searchDetailHtml"):
        body = _func(func)
        assert body.index("securityTagHtml(") < body.index("소수점 가능"), func


def test_recommendation_row_has_no_fractional_chip():
    # 추천은 정수 수량("N주 매수 추천")이 이미 나와 있고 소수점 여부는 오른쪽 패널·매수 창에 보인다.
    # 행 첫 줄을 덜 붐비게 하려고 뺐다(칩: 등급 + ETF/ETN)
    body = _func("renderRecommendations")
    assert "소수점 가능" not in body
    assert "securityTagHtml(item.security_type)" in body


def test_fractional_chip_stays_where_the_detail_is_shown():
    for func in ("recDetailHtml", "searchDetailHtml"):
        assert "소수점 가능" in _func(func), func
    assert 'id="buyFractionalTag"' in _html()


def test_mobile_buy_window_has_a_slot_for_the_tag():
    assert 'id="buyKindTag"' in _html()
    assert re.search(r"buyKindTag[^\n]*securityTagHtml\(stockItem\.security_type\)", _func("openCustomBuyModal"))
