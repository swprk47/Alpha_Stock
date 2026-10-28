"""UI 개편 단계 5(요약 패널) 중 모바일 "요약" 탭 검증. 패널의 계산·구성은 test_frontend_summary.py 에서 다룬다.

모바일에만 3번째 탭이 생기고(PC 는 탭 2개 그대로), 같은 패널을 세로로 쌓되 추천 등급 분포는 뺀다(명세 2항).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "frontend" / "index.html"


def _html():
    return HTML.read_text(encoding="utf-8")


def _func(name):
    """index.html 안의 `function name(` 본문(다음 들여쓰기 4칸 닫는 중괄호까지)."""
    s = _html()
    m = re.search(rf"(async )?function {name}\(", s)
    assert m, f"function {name} 이 없습니다"
    return s[m.start():s.index("\n    }\n", m.start())]


def _tag(s, needle):
    i = s.index(needle)
    return s[s.rfind("<", 0, i):s.index(">", i) + 1]


def test_mobile_has_a_third_summary_tab_hidden_on_pc():
    s = _html()
    tag = _tag(s, 'id="tabSummary"')
    assert "switchTab('summary')" in tag and "lg:hidden" in tag and "aria-selected" in tag
    assert "요약" in s[s.index('id="tabSummary"'):][:300]


def test_summary_section_is_hidden_until_the_tab_is_chosen():
    classes = _tag(_html(), 'id="sectionSummary"').split('class="')[1].split('"')[0].split()
    assert "hidden" in classes


def test_tab_buttons_keep_the_touch_target_and_three_equal_columns():
    s = _html()
    for tab_id in ("tabRecs", "tabHoldings", "tabSummary"):
        assert "flex-1" in _tag(s, f'id="{tab_id}"'), tab_id
    assert "py-3" in _tag(s, 'id="tabSummary"')  # 기존 탭과 같은 높이(44px 이상)


def test_switch_tab_handles_summary():
    body = _func("switchTab")
    assert "tabSummary" in body and "sectionSummary" in body
    assert "'summary'" in body
    # 요약 탭 버튼은 PC 에서 숨겨져야 하므로 상태를 바꿔도 lg:hidden 이 유지된다
    assert "lg:hidden" in body


def test_pc_falls_back_when_the_summary_tab_is_active():
    s = _html()
    listener = s[s.index("pcMql.addEventListener('change'"):][:500]
    assert "activeTab === 'summary'" in listener and "switchTab('recs')" in listener
    # 요약을 보던 중이었으니 PC 에서도 요약이 보이게, 모바일 기본 펼침(첫 행) 선택은 풀어 준다
    assert "expandedCardIndex = expandedHoldingIndex = -1" in listener


def test_summary_section_renders_the_stacked_panels_only_on_mobile():
    body = _func("renderSummarySection")
    assert "summaryPanelsHtml(true)" in body
    assert "isPcLayout()" in body and "activeTab === 'summary'" in body


def test_summary_section_refreshes_with_the_pane_and_before_the_pc_early_return():
    body = _func("renderDetailPane")
    assert "renderSummarySection()" in body
    assert body.index("renderSummarySection()") < body.index("!isPcLayout()")  # PC 가 아닐 때도 그려져야 한다


def test_mobile_panels_stack_in_one_column_without_grade_distribution():
    body = _func("summaryPanelsHtml")
    mobile_line = next(ln for ln in body.splitlines() if "if (mobile) return" in ln)
    assert "gradePanelHtml" not in mobile_line and "${grade}" not in mobile_line
    for part in ("${account}", "${asset}", "${holdings}", "${rank}"):
        assert part in mobile_line, part


def test_bottom_bar_is_not_shown_on_the_summary_tab():
    # 하단 매수 바는 추천 탭에서만(bottomBarState 가 tab !== 'recs' 면 null)
    s = _html()
    assert "if (tab !== 'recs'" in s[s.index("function bottomBarState"):][:200]


def test_order_code_is_untouched_by_the_mobile_tab():
    for name in ("executeInlineBuy", "confirmReset"):
        assert "sectionSummary" not in _func(name) and "tabSummary" not in _func(name), name
