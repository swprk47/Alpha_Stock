"""'평가 손익' 칸 표시 개선 검증.

평가 손익(unrealized_pnl)과 손익률(pnl_pct)은 예상 매도 비용(수수료·세금)을 뺀 값이라,
현재가가 평단보다 조금 높아도 마이너스일 수 있다. 칸 이름만으로는 알 수 없어서 보조 글자로 밝힌다.
값과 계산은 그대로이고 화면 글자만 바뀐다.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "frontend" / "index.html"

NOTE = "(매도 비용 반영)"


def _html():
    return HTML.read_text(encoding="utf-8")


def _func(name):
    s = _html()
    m = re.search(rf"(async )?function {name}\(", s)
    assert m, f"function {name} 이 없습니다"
    return s[m.start():s.index("\n    }\n", m.start()) + len("\n    }")]


def _eval_pnl_cells(body):
    return re.findall(r"statCell\('평가 손익'[^\n]*", body)


def test_mobile_accordion_eval_pnl_cell_carries_the_note():
    cells = _eval_pnl_cells(_func("renderHoldings"))
    assert len(cells) == 1
    assert NOTE in cells[0]
    assert "unrealized_pnl" in cells[0]  # 값은 그대로 서버의 평가 손익


def test_pc_detail_eval_pnl_cell_carries_the_note():
    cells = _eval_pnl_cells(_func("holdingDetailHtml"))
    assert len(cells) == 1
    assert NOTE in cells[0]
    assert "unrealized_pnl" in cells[0]


def test_summary_holdings_panel_explains_that_pnl_includes_sell_costs():
    body = _func("holdingsPanelHtml")
    assert "예상 매도 수수료·세금을 뺀 값이에요" in body


def test_screen_still_does_not_calculate_fees():
    for name in ("renderHoldings", "holdingDetailHtml", "holdingsPanelHtml"):
        body = _func(name)
        for forbidden in ("0.00015", "0.0015", "0.002", "0.00215", "estimate_sell_cost", "calc_sell"):
            assert forbidden not in body, (name, forbidden)
