"""차트 끝점의 실시간 닷과 모바일 차트 블록 검증.

- PC 차트에도 모바일처럼 마지막 점에 깜빡이는 닷이 보여야 한다(예전에는 #pcPulse 가 비어 있어 안 보였다).
- 닷 위치는 화면에 보이는 캔버스 크기에 맞춰 계산한다(그림 크기와 보이는 크기가 다를 수 있다).
- 모바일 보유 탭 차트는 추천 탭 차트와 같은 블록(제목·현재가·터치 탐색·높이 208px·닷)을 쓴다. 예전에는 144px로 납작했다.
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
    m = re.search(r"// <chart-logic>\r?\n(.*?)// </chart-logic>", _html(), re.S)
    assert m, "index.html 에 chart-logic 구간이 없습니다"
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


# ---- 닷 ----
@needs_node
def test_pulse_dot_is_red_for_gain_and_blue_for_loss_and_pings(run):
    gain = run("pulseDotHtml(true)")
    loss = run("pulseDotHtml(false)")
    assert "#ff453a" in gain and "#0a84ff" not in gain
    assert "#0a84ff" in loss and "#ff453a" not in loss
    for html in (gain, loss):
        assert "animate-ping" in html           # 깜빡이는 바깥 고리
        assert "motion-reduce:animate-none" in html  # 움직임을 줄이는 설정이면 깜빡임을 끈다
        assert "border-white" in html           # 중심 점의 흰 테두리(모바일의 기존 모양)


@needs_node
def test_pulse_position_follows_the_visible_canvas_not_the_drawing_size(run):
    # 그림은 340x208 로 그렸지만 화면에는 여백(8px)을 뺀 324x192 로 보인다
    box = "{offsetLeft: 8, offsetTop: 8, clientWidth: 324, clientHeight: 192}"
    pos = run(f"pulsePosition({box}, 340, 208, {{x: 326, y: 52}})")
    assert pos["left"] == pytest.approx(8 + 326 * 324 / 340)
    assert pos["top"] == pytest.approx(8 + 52 * 192 / 208)
    # 그림 크기와 보이는 크기가 같으면 여백만 더한다
    same = run("pulsePosition({offsetLeft: 8, offsetTop: 8, clientWidth: 100, clientHeight: 50}, 100, 50, {x: 30, y: 10})")
    assert same == {"left": 38, "top": 18}


@needs_node
def test_pulse_position_is_safe_with_a_zero_sized_drawing(run):
    pos = run("pulsePosition({offsetLeft: 8, offsetTop: 8, clientWidth: 0, clientHeight: 0}, 0, 0, {x: 5, y: 5})")
    assert all(v == v for v in pos.values())  # NaN 이 아니다(JSON 으로는 null 이 되므로 값이 있어야 한다)
    assert pos["left"] is not None and pos["top"] is not None


# ---- 모바일 차트 블록 ----
@needs_node
def test_mobile_chart_block_has_header_hint_ids_and_full_height(run):
    html = run("mobileChartBlockHtml({canvasId: 'c1', priceId: 'p1', dateId: 'd1', pulseId: 'u1', priceText: '29,700원'})")
    for needed in ('id="c1"', 'id="p1"', 'id="d1"', 'id="u1"', "29,700원", "최근 30일 시세 흐름", "터치하여 탐색", "h-52", "touch-none"):
        assert needed in html, needed
    assert "h-36" not in html


# ---- 구조 ----
def test_draw_function_renders_the_dot_itself_at_the_scaled_position():
    body = _func("drawInteractiveChart")
    assert "pulseDotHtml(" in body and "pulsePosition(" in body
    assert "innerHTML" in body  # 닷 모양은 호출하는 쪽의 빈 요소를 채운다(PC 의 빈 #pcPulse 가 보이지 않던 문제)


def test_pc_chart_panel_still_provides_the_pulse_container():
    assert 'id="pcPulse"' in _func("pcChartPanel")
    assert "'pcPulse'" in _func("drawPcChart")


def test_recommendation_and_holding_accordions_share_the_chart_block():
    recs = _func("renderRecommendations")
    holds = _func("renderHoldings")
    assert "mobileChartBlockHtml(" in recs and "mobileChartBlockHtml(" in holds
    assert "h-36" not in holds  # 납작하던 144px 차트
    assert "h-52" not in recs and "h-52" not in holds  # 높이는 공통 블록 한 곳에서만 정한다


def test_holding_chart_gets_tooltip_and_pulse_ids():
    holds = _func("renderHoldings")
    draw = _func("drawExpandedHoldingChart")
    # 같은 id 를 공통 블록(마크업, renderHoldings)과 그리기 호출(drawExpandedHoldingChart) 양쪽에서 쓴다
    for needed in ("holdingTipPrice_", "holdingTipDate_", "holdingPulse_"):
        assert needed in holds and needed in draw, needed


# ---- 숨겨진 탭에서 그린 차트 ----
def test_chart_is_not_drawn_while_it_has_no_layout_and_is_redrawn_when_the_tab_is_shown():
    # 모바일은 처음에 숨겨진 탭 안의 차트를 먼저 그려서 캔버스 크기가 0 이었다(임시 크기로 그리고 닷은 0,0). 보일 때 다시 그린다
    draw = _func("drawInteractiveChart")
    assert re.search(r"if \(!canvas\.clientWidth[^)]*\)\s*(\{[^}]*)?return", draw)
    switch = _func("switchTab")
    assert "drawExpandedHoldingChart()" in switch and "drawExpandedRecChart()" in switch
    assert "drawExpandedHoldingChart()" in _func("renderHoldings")
    assert "drawExpandedRecChart()" in _func("renderRecommendations")
    # 모바일 아코디언에서만 그린다(PC 는 오른쪽 패널의 차트가 따로 그려진다)
    assert "isPcLayout()" in _func("drawExpandedHoldingChart") and "isPcLayout()" in _func("drawExpandedRecChart")


@needs_node
def test_pulse_position_falls_back_to_the_drawing_scale_when_the_canvas_has_no_size(run):
    pos = run("pulsePosition({offsetLeft: 0, offsetTop: 0, clientWidth: 0, clientHeight: 0}, 320, 208, {x: 100, y: 50})")
    assert pos == {"left": 100, "top": 50}  # 비율 0 으로 닷이 (0,0)에 가지 않는다


# ---- 평단선(보유 종목 차트) ----
@needs_node
def test_chart_range_covers_the_prices_and_the_average_price(run):
    assert run("chartRange([100, 120, 110], [])") == {"min": 100, "max": 120}
    assert run("chartRange([100, 120, 110], [105])") == {"min": 100, "max": 120}   # 범위 안이면 그대로
    assert run("chartRange([100, 120, 110], [130])") == {"min": 100, "max": 130}   # 위로 벗어나면 넓힌다
    assert run("chartRange([100, 120, 110], [90])") == {"min": 90, "max": 120}     # 아래로 벗어나면 넓힌다


@needs_node
def test_chart_range_ignores_missing_or_invalid_extra_values(run):
    for extra in ("[0]", "[-5]", "[null]", "[undefined]", "[NaN]", "['abc']"):
        assert run(f"chartRange([100, 120], {extra})") == {"min": 100, "max": 120}, extra


@needs_node
def test_avg_label_text(run):
    assert run("avgLabelText(22350)") == "평단 22,350원"
    assert run("avgLabelText(1234567)") == "평단 1,234,567원"


def test_only_holding_charts_draw_the_average_line():
    draw = _func("drawInteractiveChart")
    assert "opts" in draw and "avgPrice" in draw and "chartRange(" in draw
    assert "avgLabelText(" in draw and "avgLabelPlacement(" in draw
    assert "#ff9f0a" not in draw  # 주황은 쓰지 않는다(시안 A: 최고/최저와 같은 흰색 점선)
    assert "rgba(245, 245, 247, 0.65)" in draw and "setLineDash([2, 4])" in draw
    # 모바일 보유 차트와 PC 보유 상세만 평단을 넘긴다. 추천·검색·모달 차트는 넘기지 않는다
    assert "avgPrice" in _func("drawExpandedHoldingChart") and "avg_price" in _func("drawExpandedHoldingChart")
    assert "avgPrice" not in _func("drawExpandedRecChart")
    detail = _func("renderDetailPane")
    assert detail.count("avg_price") == 1 and detail.count("drawPcChart(") == 3
    assert "avgPrice" in _func("drawPcChart")


def test_pc_chart_is_taller_than_before():
    body = _func("pcChartPanel")
    assert "h-96" in body and "h-72" not in body and "h-48" not in body  # 192px → 288px → 384px. 가로로 길고 납작해서 변동폭이 안 보였다


# ---- 최고/최저를 점에 붙이고 평단선은 흰색 점선(시안 A) ----
@needs_node
def test_extreme_labels_read_like_the_old_ones(run):
    assert run("extremeText('high', 23900)") == "최고 23,900원"
    assert run("extremeText('low', 20500)") == "최저 20,500원"


@needs_node
def test_extreme_label_stays_centered_unless_it_would_leave_the_chart(run):
    # (점 x, 글자 폭, 왼쪽 한계, 오른쪽 한계)
    assert run("extremeLabelAlign(150, 80, 4, 300)") == {"anchor": "middle", "tx": 150}
    assert run("extremeLabelAlign(20, 80, 4, 300)") == {"anchor": "start", "tx": 16}    # 왼쪽 끝이면 점 오른쪽으로 펼친다
    assert run("extremeLabelAlign(290, 80, 4, 300)") == {"anchor": "end", "tx": 294}    # 오른쪽 끝이면 점 왼쪽으로 펼친다


@needs_node
def test_label_rect_follows_the_alignment(run):
    mid = run("labelRect('middle', 100, 60, 50)")
    assert mid == {"x1": 70, "x2": 130, "y1": 37, "y2": 54}
    assert run("labelRect('start', 100, 60, 50)")["x1"] == 100 and run("labelRect('start', 100, 60, 50)")["x2"] == 160
    assert run("labelRect('end', 100, 60, 50)")["x1"] == 40 and run("labelRect('end', 100, 60, 50)")["x2"] == 100


@needs_node
def test_avg_label_goes_left_above_the_line_unless_it_collides(run):
    # (평단선 y, 글자 폭, 피할 영역들, 왼쪽 한계, 오른쪽 한계)
    free = run("avgLabelPlacement(120, 90, [], 8, 313)")
    assert free == {"x": 10, "y": 116, "anchor": "start"}                                   # 기본: 왼쪽, 선 위
    block_above = "[{x1: 8, x2: 120, y1: 100, y2: 118}]"
    assert run(f"avgLabelPlacement(120, 90, {block_above}, 8, 313)") == {"x": 10, "y": 134, "anchor": "start"}  # 선 아래로
    block_both = "[{x1: 8, x2: 120, y1: 100, y2: 118}, {x1: 8, x2: 120, y1: 122, y2: 140}]"
    assert run(f"avgLabelPlacement(120, 90, {block_both}, 8, 313)") == {"x": 311, "y": 116, "anchor": "end"}  # 오른쪽으로
    block_all = "[{x1: 0, x2: 400, y1: 0, y2: 400}]"
    assert run(f"avgLabelPlacement(120, 90, {block_all}, 8, 313)") == free                  # 갈 곳이 없으면 기본 자리


def test_chart_draws_point_labels_instead_of_dotted_extreme_lines():
    draw = _func("drawInteractiveChart")
    assert "extremeLabelAlign(" in draw and "labelRect(" in draw and "extremeText(" in draw
    assert "measureText(" in draw  # 실제 글자 폭으로 정렬한다
    # 예전의 최고/최저 점선과 왼쪽 고정 라벨은 없어졌다
    assert "최고 ${" not in draw and "최저 ${" not in draw
    assert "#2c2c2e" not in draw
    # 마지막 점이 최고/최저이면 실시간 닷이 그 자리를 대신하므로 작은 점은 찍지 않는다
    assert "points.length - 1" in draw


def test_canvas_text_align_uses_valid_values_only():
    # 시안(SVG)의 text-anchor 'middle' 은 캔버스 textAlign 에서는 'center' 다. 'middle' 을 그대로 넘기면 무시되어 왼쪽 정렬로 그려진다
    draw = _func("drawInteractiveChart")
    assert re.search(r"textAlign = e\.anchor === 'middle' \? 'center' : e\.anchor", draw)
    assert "textAlign = e.anchor;" not in draw


# ---- 창 크기가 바뀌면 다시 그린다 ----
@needs_node
def test_chart_needs_a_redraw_only_when_the_visible_size_really_changed(run):
    drawn = "{w: 736, h: 366}"
    assert run(f"chartNeedsRedraw({drawn}, 736, 366)") is False      # 같으면 건너뛴다(무한 반복 방지)
    assert run(f"chartNeedsRedraw({drawn}, 556, 366)") is True       # 폭이 줄면
    assert run(f"chartNeedsRedraw({drawn}, 1156, 366)") is True      # 폭이 늘면
    assert run(f"chartNeedsRedraw({drawn}, 736, 270)") is True       # 높이만 바뀌어도
    assert run(f"chartNeedsRedraw({drawn}, 736.4, 366)") is False    # 1px 미만 흔들림은 무시
    assert run("chartNeedsRedraw({w: 0, h: 0}, 736, 366)") is True   # 숨겨져서 못 그렸던 차트가 보이게 되면
    assert run(f"chartNeedsRedraw({drawn}, 0, 0)") is False          # 숨겨진 동안은 그리지 않는다


@needs_node
def test_resize_action_forgets_charts_that_left_the_page(run):
    reg = "{el: 'A', w: 736, h: 366}"
    assert run(f"chartResizeAction({reg}, 'A', true, 556, 366)") == "redraw"
    assert run(f"chartResizeAction({reg}, 'A', true, 736, 366)") == "skip"
    assert run(f"chartResizeAction({reg}, 'A', false, 556, 366)") == "forget"        # 화면에서 사라진 캔버스
    assert run(f"chartResizeAction({reg}, 'B', true, 556, 366)") == "forget"         # 같은 id 의 새 캔버스가 이미 등록됨(옛 캔버스의 알림)
    assert run("chartResizeAction(undefined, 'A', true, 556, 366)") == "forget"      # 등록이 없음


def test_chart_function_registers_and_watches_before_it_may_skip_a_hidden_canvas():
    draw = _func("drawInteractiveChart")
    assert "chartRegistry[canvasId]" in draw and "watchChartSize(" in draw
    # 숨겨진 캔버스도 등록해 둬야 보이게 될 때 감시자가 그린다(숨김 검사보다 앞)
    assert draw.index("watchChartSize(") < draw.index("if (!canvas.clientWidth")
    reg = draw[draw.index("chartRegistry[canvasId]"):]
    assert "opts" in reg.split("\n")[0] or "opts" in reg[:200]  # 평단·닷 인자도 함께 기억한다


def test_watcher_uses_resize_observer_batches_frames_and_cleans_up():
    watch = _func("watchChartSize")
    assert "new ResizeObserver(" in watch and "requestAnimationFrame(" in watch
    assert "chartResizeAction(" in watch and "unobserve(" in watch
    assert "isConnected" in watch or "document.body.contains" in watch
    assert "drawInteractiveChart(" in watch  # 같은 인자로 다시 그린다
    assert "chartRegistry" in watch
