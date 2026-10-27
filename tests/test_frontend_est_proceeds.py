"""보유 종목의 예상 수령액·예상 실현 손익 표시 검증.

값은 서버가 실제 매도와 같은 계산(calc_sell_proceeds)으로 내려준 est_proceeds·est_realized_pnl 을 그대로 보인다.
화면은 수수료·세금을 계산하지 않는다. PC 는 전량 매도 패널에 2줄(시안 S2), 모바일은 매도 버튼 위 1줄(시안 M3).
시세를 못 받은 종목은 서버가 null 을 주고, 화면은 숫자 대신 안내 한 줄을 보인다.
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
    """index.html 안의 `function name(` 본문(다음 들여쓰기 4칸 닫는 중괄호까지)."""
    s = _html()
    m = re.search(rf"(async )?function {name}\(", s)
    assert m, f"function {name} 이 없습니다"
    return s[m.start():s.index("\n    }\n", m.start()) + len("\n    }")]


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    d = tmp_path_factory.mktemp("estjs")
    src = "\n".join(_func(n) for n in ("signedWon", "pnlTextClass", "estimateRowsHtml"))

    def _run(expr):
        f = d / "t.js"
        f.write_text(src + "\nconsole.log(JSON.stringify(" + expr + "));\n", encoding="utf-8")
        out = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    return _run


def squash(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


# ---- 표시 ----
@needs_node
def test_pc_shows_estimated_proceeds_and_estimated_realized_pnl(run):
    html = run("estimateRowsHtml({est_proceeds: 30505, est_realized_pnl: 5}, false)")
    text = squash(html)
    assert "예상 수령액 (세금·수수료 반영) 30,505원" in text
    assert "예상 실현 손익 +5원" in text
    assert "text-[#ff6a60]" in html  # 이익은 빨강(부호 +와 함께)


@needs_node
def test_mobile_shows_only_estimated_proceeds(run):
    # 시안 M3: 예상 수령액 한 줄
    text = squash(run("estimateRowsHtml({est_proceeds: 30505, est_realized_pnl: 5}, true)"))
    assert "예상 수령액 (세금·수수료 반영) 30,505원" in text
    assert "예상 실현 손익" not in text


@needs_node
def test_negative_estimated_pnl_is_blue_with_a_minus_sign(run):
    html = run("estimateRowsHtml({est_proceeds: 9979, est_realized_pnl: -21}, false)")
    assert "예상 실현 손익 -21원" in squash(html)
    assert "text-[#5aa9ff]" in html


@needs_node
def test_zero_estimated_pnl_has_no_sign_and_neutral_color(run):
    html = run("estimateRowsHtml({est_proceeds: 10000, est_realized_pnl: 0}, false)")
    assert "예상 실현 손익 0원" in squash(html)
    assert "text-[#ff6a60]" not in html and "text-[#5aa9ff]" not in html


@needs_node
def test_null_estimate_shows_a_notice_instead_of_numbers(run):
    # 서버가 시세를 못 받아 null 을 준 종목: 틀린 금액을 그럴듯하게 보이지 않는다
    for mobile in ("true", "false"):
        text = squash(run(f"estimateRowsHtml({{est_proceeds: null, est_realized_pnl: null}}, {mobile})"))
        assert "시세를 가져오지 못해 예상 금액을 표시하지 못해요" in text
        assert "원" not in text.replace("표시하지 못해요", "")


@needs_node
def test_missing_fields_from_an_older_server_show_nothing(run):
    assert run("estimateRowsHtml({}, false)") == ""
    assert run("estimateRowsHtml({}, true)") == ""


# ---- 배치 ----
def test_pc_sell_panel_shows_the_estimate_above_the_button():
    body = _func("holdingDetailHtml")
    assert "estimateRowsHtml(h, false)" in body
    assert body.index("estimateRowsHtml(") < body.index("executeSell('${h.code}')")
    assert "전량 모의 매도" in body  # 매도 버튼은 그대로


def test_mobile_accordion_shows_the_estimate_above_the_sell_button():
    body = _func("renderHoldings")
    assert "estimateRowsHtml(h, true)" in body
    assert body.index("estimateRowsHtml(") < body.index("executeSell(")


# ---- 화면은 계산하지 않는다 ----
def test_screen_does_not_calculate_fees_or_taxes():
    for name in ("estimateRowsHtml", "holdingDetailHtml", "renderHoldings"):
        body = _func(name)
        for forbidden in ("0.00015", "0.0015", "0.002", "0.00215", "SELL_TAX", "SELL_FEE", "estimate_sell_cost", "calc_sell"):
            assert forbidden not in body, (name, forbidden)
    body = _func("estimateRowsHtml")
    assert "est_proceeds" in body and "est_realized_pnl" in body
    assert "unrealized_pnl" not in body  # 기존 평가 손익(합산 절사)을 예상 실현 손익으로 대신 쓰지 않는다


def test_order_code_is_untouched_by_this_feature():
    for name in ("executeSell", "executeSelectedBuy", "updateBuyModalCalcs", "calculateQtyFromAmount", "confirmReset"):
        body = _func(name)
        assert "est_proceeds" not in body and "estimateRowsHtml" not in body, name
