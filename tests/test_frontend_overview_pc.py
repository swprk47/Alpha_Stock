"""PC 오른쪽 패널(검색 종목·스윙 추천 상세)의 [시세·매수 | 개요] 탭.

- 탭은 헤더(이름·가격) 바로 아래, 차트·수치·AI 진단·매수 패널 위에 있고, 개요 탭이면 그 자리에 개요가 두 열로 놓인다.
- PC 보유 상세(holdingDetailHtml)에는 넣지 않는다(쓰다가 필요하면 추가).
- 60초 자동 갱신이 패널을 다시 그려도 선택한 탭이 유지되고, 패널이 보여 주는 종목이 바뀌면 시세·매수 탭으로 돌아간다.
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


@pytest.mark.parametrize("func,chart", [("searchDetailHtml", "pcChartPanel("), ("recDetailHtml", "pcChartPanel(")])
def test_detail_has_tabs_after_header_and_before_body(func, chart):
    body = _func(func)
    header = body.index("<h2")
    tabs = body.index("overviewPaneTabsHtml()")
    assert header < tabs < body.index(chart)


@pytest.mark.parametrize("func", ["searchDetailHtml", "recDetailHtml"])
def test_overview_replaces_body_only_when_selected(func):
    body = _func(func)
    assert "overviewTab === 'overview' ? overviewPaneBody(" in body
    # 기본(시세·매수)에서는 기존 본문 조각이 그대로 남아 있다
    for part in ("pcChartPanel(", "grid-cols-4", "recAiHtml(" if func == "recDetailHtml" else "ibBoxHtml("):
        assert part in body, part


def test_holding_detail_has_no_tabs():
    body = _func("holdingDetailHtml")
    assert "overviewPaneTabsHtml" not in body and "overviewTab" not in body and "ovTabsHtml" not in body


def test_pane_helpers_use_two_columns_and_state_variables():
    body = _func("overviewPaneBody")
    assert "layout: 'two-col'" in body and "aboutOpen: overviewAboutOpen" in body and "overviewViewFor(" in body and "ovBodyHtml(" in body
    tabs = _func("overviewPaneTabsHtml")
    assert "ovTabsHtml(overviewTab)" in tabs and "max-w-[" in tabs


def test_render_detail_pane_draws_chart_only_on_trade_tab_and_resets_by_code():
    body = _func("renderDetailPane")
    assert "ovPaneReset(overviewPaneCode" in body and "overviewPaneCode = " in body
    assert body.count("overviewTab === 'trade'") >= 2  # 검색·추천 모두 개요 탭에서는 없는 캔버스를 그리지 않는다
    # 같은 종목을 다시 그릴 때(60초 갱신) 탭을 무조건 되돌리지 않는다
    assert "overviewTab = 'trade'" not in body


@needs_node
def test_pane_reset_keeps_tab_for_the_same_code_only(tmp_path):
    f = tmp_path / "t.js"
    f.write_text(_section("overview-logic") + """
console.log(JSON.stringify([
  ovPaneReset('005930', '005930', 'overview'),
  ovPaneReset('005930', '000660', 'overview'),
  ovPaneReset('', '005930', 'overview'),
  ovPaneReset('005930', '', 'overview'),
  ovPaneReset('005930', '005930', 'trade'),
]));
""", encoding="utf-8")
    out = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == ["overview", "trade", "trade", "trade", "trade"]


def test_visible_code_reads_the_pc_pane_too():
    body = _func("overviewVisibleCode")
    assert "buySheetItem" in body and "isPcLayout()" in body and "overviewPaneItem()" in body
    pane = _func("overviewPaneItem")
    assert "detailPaneState(" in pane and "'search'" in pane and "'rec'" in pane  # 보유 상세에는 탭이 없다


def test_select_tab_scrolls_the_pc_pane_to_top():
    assert "detailPane" in _func("selectOverviewTab") and "scrollTop = 0" in _func("selectOverviewTab")
