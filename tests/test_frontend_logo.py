"""종목 로고 표시 검증.

로고 주소는 종목코드로만 만든다(저장된 logo_url 은 보유 종목에서 비어 있을 수 있다).
이미지가 없거나(ETF 등) 불러오지 못하면 이름 첫 글자 원으로 대신하고, 한 번 실패한 코드는 기억해
목록을 다시 그릴 때마다 404 요청을 되풀이하지 않는다.
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
    m = re.search(r"// <logo-logic>\r?\n(.*?)// </logo-logic>", _html(), re.S)
    assert m, "index.html 에 logo-logic 구간이 없습니다"
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
def test_logo_url_is_built_from_the_code(run):
    base = "https://ssl.pstatic.net/imgstock/fn/real/logo/png/stock/Stock"
    assert run("logoUrl('035720')") == base + "035720.png"
    assert run("logoUrl('0183J0')") == base + "0183J0.png"  # 영숫자 종목코드


@needs_node
@pytest.mark.parametrize("code", ["'035720 '", "'12345'", "'1234567'", "'0183j0'", "''", "null", "undefined", "'../x'"])
def test_invalid_codes_get_no_url_and_show_the_initial(run, code):
    assert run(f"logoUrl({code})") == ""
    html = run(f"logoHtml({code}, '카카오', 36)")
    assert "<img" not in html
    assert ">카<" in html


@needs_node
def test_logo_html_has_image_size_and_fallback_hook(run):
    html = run("logoHtml('035720', '카카오', 52)")
    assert 'src="https://ssl.pstatic.net/imgstock/fn/real/logo/png/stock/Stock035720.png"' in html
    assert "width: 52px" in html and "height: 52px" in html
    assert "rounded-full" in html
    # 네이버 로고는 이미 원형·투명 이미지라 회색 원과 여백이 없어야 로고가 크게 보인다
    assert "background" not in html and "bg-[#2c2c2e]" not in html and "padding" not in html
    assert 'alt=""' in html  # 이름이 바로 옆에 있으니 스크린리더가 두 번 읽지 않게
    assert "logoImgFailed(this, '035720')" in html
    assert 'data-initial="카"' in html


@needs_node
def test_font_size_scales_with_the_circle_for_the_initial(run):
    small = run("logoHtml(null, 'KODEX 200', 28)")
    big = run("logoHtml(null, 'KODEX 200', 52)")
    size = lambda h: int(re.search(r"font-size: (\d+)px", h).group(1))
    assert size(big) > size(small)
    assert ">K<" in small and ">K<" in big
    # 로고가 없는 종목(ETF 등)은 글자만 떠 보이지 않게 회색 원을 둔다
    assert "bg-[#2c2c2e]" in small


@needs_node
def test_names_are_escaped_so_markup_in_a_name_cannot_inject(run):
    html = run("logoHtml('035720', '<img src=x onerror=alert(1)>', 36)")
    assert "<img src=x" not in html
    assert 'data-initial="&lt;"' in html
    quote = run("""logoHtml('035720', '"A\\'B', 36)""")
    assert 'data-initial="&quot;"' in quote


@needs_node
def test_empty_or_missing_name_shows_a_placeholder(run):
    assert ">?<" in run("logoHtml(null, '', 36)")
    assert ">?<" in run("logoHtml(null, undefined, 36)")
    assert ">?<" in run("logoHtml(null, '   ', 36)")


@needs_node
def test_initial_keeps_a_whole_character(run):
    assert ">😀<" in run("logoHtml(null, '😀주식', 36)")  # 이모지를 반으로 자르지 않는다
    assert ">삼<" in run("logoHtml(null, '삼성전자', 36)")


@needs_node
def test_failed_image_swaps_to_initial_and_is_remembered(run):
    out = run("""(() => {
      const parent = { textContent: '<img>', style: {} };
      const img = { dataset: { initial: '라' }, parentElement: parent };
      logoImgFailed(img, '360750');
      return {
        text: parent.textContent,
        bg: parent.style.background,
        remembered: logoFailed.has('360750'),
        next: logoHtml('360750', 'TIGER 미국S&P500', 36),
        other: logoHtml('035720', '카카오', 36),
      };
    })()""")
    assert out["text"] == "라"
    assert out["bg"] == "#2c2c2e"  # 실패한 순간부터 첫 글자 원 모양
    assert out["remembered"] is True
    assert "<img" not in out["next"]  # 다시 그려도 404 요청을 되풀이하지 않는다
    assert "<img" in out["other"]  # 다른 종목은 영향 없음


@needs_node
def test_failed_handler_is_safe_without_a_parent(run):
    assert run("(() => { logoImgFailed({ dataset: {}, parentElement: null }, '069500'); return logoFailed.has('069500'); })()") is True


# ── 화면에 붙인 곳 (시안: 제목줄 52px · 목록 행 36px · 검색 드롭다운 28px · 모바일 매수 창 40px) ──


def test_detail_headers_use_the_shared_52px_logo():
    for name in ("recDetailHtml", "holdingDetailHtml", "searchDetailHtml"):
        body = _func(name)
        assert re.search(r"logoHtml\([^)]*\b52\)", body), name


def test_search_detail_skeleton_reserves_the_logo_space():
    # 받는 중에 로고 자리가 비어 있다가 생기면 제목이 옆으로 밀린다
    body = _func("searchDetailHtml")
    loading = body[:body.index("const isGain")]
    assert "w-[52px] h-[52px]" in loading


def test_list_rows_use_the_36px_logo():
    assert re.search(r"logoHtml\([^)]*\b36\)", _func("renderRecommendations"))
    assert re.search(r"logoHtml\([^)]*\b36\)", _func("renderHoldings"))


def test_rec_row_keeps_the_rank_circle_before_the_logo():
    body = _func("renderRecommendations")
    assert body.index("${idx + 1}") < body.index("logoHtml(")  # 시안 A: 순번 원은 그대로, 오른쪽에 로고


def test_search_dropdown_uses_the_shared_logo_not_the_stored_url():
    body = _func("renderSearchResults")
    assert re.search(r"logoHtml\([^)]*\b28\)", body)
    assert "logo_url" not in body
    assert "charAt(0)" not in body  # 이름을 그대로 끼워 넣던 인라인 onerror 제거


def test_mobile_search_buy_modal_shows_a_40px_logo():
    s = _html()
    assert 'id="buyStockLogo"' in s
    body = _func("openCustomBuyModal")
    assert re.search(r"buyStockLogo[^\n]*logoHtml\([^)]*\b40\)", body)
