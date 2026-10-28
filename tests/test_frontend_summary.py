"""UI 개편 단계 5(요약 패널) 검증: 내 계좌(승률·거래별 손익 막대·거래 내역), 자산 구성, 추천 등급 분포,
보유 종목 손익, 추천 점수 순위. PC 는 종목 미선택일 때 오른쪽 패널, 모바일은 3번째 "요약" 탭.

계산은 index.html 의 `// <summary-logic>` 구간을 node 로 그대로 실행해 확인하고, 화면 구조는 문자열로 확인한다.
서버 변경은 없다: 승률·거래별 손익은 /api/portfolio 의 history(SELL 의 pnl·date), 나머지는 화면에 있는 데이터.
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
    return s[m.start():s.index("\n    }\n", m.start())]


def _logic_source():
    m = re.search(r"// <summary-logic>\r?\n(.*?)// </summary-logic>", _html(), re.S)
    assert m, "index.html 에 summary-logic 구간이 없습니다"
    return m.group(1)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    d = tmp_path_factory.mktemp("summaryjs")
    src = _logic_source()

    def _run(expr):
        f = d / "t.js"
        f.write_text(src + "\nconsole.log(JSON.stringify(" + expr + "));\n", encoding="utf-8")
        out = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    return _run


# 서버 history 와 같은 모양: BUY 는 pnl 이 없고 SELL 에만 있다
H = (
    "[{type:'BUY',name:'가',price:100,quantity:1,date:'2026-10-13 09:00:00'},"
    "{type:'SELL',name:'가',price:110,quantity:1,pnl:2000,date:'2026-10-14 10:00:00'},"
    "{type:'SELL',name:'나',price:90,quantity:1,pnl:-1000,date:'2026-10-16 10:00:00'},"
    "{type:'SELL',name:'다',price:95,quantity:1,pnl:500,date:'2026-10-20 10:00:00'}]"
)


# ---- 승률·거래별 손익 ----
@needs_node
def test_trade_stats_counts_sells_and_wins(run):
    st = run(f"tradeStats({H})")
    assert st["sells"] == 3 and st["wins"] == 2
    assert st["winRate"] == 67  # 2/3 = 66.7% → 반올림


@needs_node
def test_trade_stats_recent_are_oldest_first_with_month_day(run):
    st = run(f"tradeStats({H})")
    assert [r["date"] for r in st["recent"]] == ["10/14", "10/16", "10/20"]
    assert [r["pnl"] for r in st["recent"]] == [2000, -1000, 500]


@needs_node
def test_trade_stats_keeps_only_the_latest_six_sells(run):
    sells = ",".join(
        f"{{type:'SELL',name:'s{i}',pnl:{i},date:'2026-10-{10 + i:02d} 10:00:00'}}" for i in range(1, 9)
    )
    st = run(f"tradeStats([{sells}])")
    assert st["sells"] == 8
    assert [r["pnl"] for r in st["recent"]] == [3, 4, 5, 6, 7, 8]


@needs_node
def test_trade_stats_without_sells_has_no_win_rate(run):
    # 매도가 없으면 승률을 지어내지 않는다(0% 가 아니라 null → 화면은 "–")
    assert run("tradeStats([{type:'BUY',date:'2026-10-13 09:00:00'}])") == {
        "sells": 0, "wins": 0, "winRate": None, "recent": [],
    }
    assert run("tradeStats(undefined)")["winRate"] is None
    assert run("tradeStats([])")["sells"] == 0


@needs_node
def test_trade_stats_sell_without_pnl_is_not_a_win(run):
    st = run("tradeStats([{type:'SELL',date:'2026-10-14 10:00:00'},{type:'SELL',pnl:5,date:'2026-10-15 10:00:00'}])")
    assert st["sells"] == 2 and st["wins"] == 1 and st["winRate"] == 50


# ---- 거래 내역(최신순) ----
@needs_node
def test_recent_trades_are_newest_first_and_only_sells_have_pnl(run):
    rows = run(f"recentTrades({H}, 8)")
    assert [r["type"] for r in rows] == ["SELL", "SELL", "SELL", "BUY"]
    assert rows[0]["date"] == "10/20" and rows[0]["pnl"] == 500
    assert rows[-1]["pnl"] is None and rows[-1]["type"] == "BUY"


@needs_node
def test_recent_trades_respects_the_limit(run):
    assert len(run(f"recentTrades({H}, 2)")) == 2
    assert run("recentTrades(null, 5)") == []


# ---- 막대 높이: 가장 큰 값이 한쪽 절반 높이를 채운다 ----
@needs_node
def test_bar_specs_scale_to_the_largest_value(run):
    bars = run("barSpecs([2000, -1000, 500], 40)")
    assert [b["h"] for b in bars] == [40, 20, 10]
    assert [b["up"] for b in bars] == [True, False, True]


@needs_node
def test_bar_specs_tiny_values_stay_visible_and_zero_stays_flat(run):
    bars = run("barSpecs([100000, 1, 0], 40)")
    assert bars[1]["h"] == 3  # 너무 작아도 보이게 최소 높이
    assert bars[2]["h"] == 0
    assert run("barSpecs([0, 0], 40)") == [{"value": 0, "up": True, "h": 0}, {"value": 0, "up": True, "h": 0}]


@needs_node
def test_compact_won_shortens_large_amounts_for_narrow_bars(run):
    assert run("compactWon(950)") == "950"
    assert run("compactWon(1953)") == "1,953"
    assert run("compactWon(12345)") == "1.2만"
    assert run("compactWon(100000)") == "10만"
    assert run("compactWon(0)") == "0"
    assert run("compactWon(-12345)") == "1.2만"  # 부호는 부르는 쪽이 붙인다


# ---- 도넛 / 자산 구성 ----
@needs_node
def test_donut_segments_fill_the_circle_in_order(run):
    segs = run("donutSegments([69496, 30560], 40)")
    c = 2 * 3.141592653589793 * 40
    assert len(segs) == 2
    assert abs(sum(s["len"] for s in segs) - c) < 1e-6
    assert segs[0]["offset"] == 0 and abs(segs[1]["offset"] + segs[0]["len"]) < 1e-6
    assert run("donutSegments([0, 0], 40)") == []


@needs_node
def test_asset_split_percentages_add_up_to_100(run):
    sp = run("assetSplit({cash_balance:69496,total_evaluation:30560})")
    assert sp["total"] == 100056 and sp["cashPct"] == 69.5 and sp["stockPct"] == 30.5
    assert run("assetSplit({cash_balance:0,total_evaluation:0})")["cashPct"] == 100


# ---- 추천 등급 분포 / 보유 손익 / 점수 순위 ----
RECS = (
    "[{name:'가',grade:'S',score:84,grade_score:70},{name:'나',grade:'A',score:71,grade_score:80},"
    "{name:'다',grade:'A',score:65},{name:'라',grade:'B',score:40},{name:'마',grade:'A',score:90}]"
)


@needs_node
def test_grade_distribution_counts_each_grade(run):
    gd = run(f"gradeDistribution({RECS})")
    assert gd["total"] == 5
    assert gd["counts"]["S"] == 1 and gd["counts"]["A"] == 3 and gd["counts"]["B"] == 1 and gd["counts"]["C"] == 0
    assert run("gradeDistribution([])")["total"] == 0 and run("gradeDistribution(null)")["total"] == 0


@needs_node
def test_holdings_by_pnl_sorts_best_first(run):
    rows = run("holdingsByPnl([{name:'가',pnl_pct:-1.5},{name:'나',pnl_pct:3.2},{name:'다',pnl_pct:0}])")
    assert [r["name"] for r in rows] == ["나", "다", "가"]
    assert rows[0]["pnlPct"] == 3.2
    assert run("holdingsByPnl(undefined)") == []


@needs_node
def test_score_ranking_uses_score_not_grade_score(run):
    # 목록은 score 순으로 정렬되므로 순위도 score 기준(AI 진단의 grade_score 와 숫자가 다를 수 있다)
    rk = run(f"scoreRanking({RECS}, 3)")
    assert [r["name"] for r in rk] == ["마", "가", "나"]
    assert [r["score"] for r in rk] == [90, 84, 71]
    assert [r["rank"] for r in rk] == [1, 2, 3]
    assert rk[0]["grade"] == "A"


@needs_node
def test_score_ranking_handles_missing_scores_and_empty(run):
    rk = run("scoreRanking([{name:'가'},{name:'나',score:5}], 3)")
    assert [r["name"] for r in rk] == ["나", "가"] and rk[1]["score"] == 0
    assert run("scoreRanking(null, 3)") == []


def test_score_ranking_source_does_not_read_grade_score():
    body = re.search(r"function scoreRanking\(.*?\n    }\n", _logic_source(), re.S).group(0)
    assert "grade_score" not in body


# ---- 아이콘 ----
def test_summary_icons_exist_per_spec():
    s = _html()
    for name in ("chart-column", "chart-pie", "award", "list-ordered", "chart-line"):
        assert f"'{name}':" in s, name


# ---- 내 계좌 패널: 세그먼트는 거래별 손익·거래 내역 2개 ----
def test_account_panel_has_two_segments_and_four_stats():
    body = _func("accountPanelHtml")
    assert "segHtml(" in body
    seg = _func("segHtml")
    assert "btn('pnl'" in seg and "btn('trades'" in seg
    assert "거래별 손익" in seg and "거래 내역" in seg
    assert "assets" not in seg  # 자산 구성은 아래 별도 패널과 겹쳐서 세그먼트에 두지 않는다
    assert "setSummarySeg(" in seg and "aria-pressed" in seg
    for label in ("총 자산", "수익률", "실현 손익", "승률"):
        assert label in body, label


def test_account_panel_is_shorter_on_mobile():
    # 모바일은 위의 자산 카드에 총 자산·수익률이 있으므로 실현 손익·승률만
    body = _func("accountPanelHtml")
    assert "!mobile" in body  # 총 자산·수익률 칸은 PC 에서만


def test_segment_buttons_meet_touch_target_on_mobile():
    body = _func("segHtml")
    assert "min-h-[44px]" in body  # 모바일 44px
    assert "min-h-[36px]" in body  # PC


def test_bars_follow_korean_colors_and_label_values_not_only_colors():
    body = _func("pnlBarsHtml")
    assert "#ff453a" in body and "#0a84ff" in body  # 이익 빨강, 손실 파랑
    assert "compactWon(" in body  # 색에만 의존하지 않고 부호·금액을 적는다
    assert 'role="img"' in body and "aria-label" in body
    assert "매도 거래가 쌓이면 여기에 보여요" in _func("accountPanelHtml")


def test_trade_list_view_and_empty_state():
    body = _func("tradeListHtml")
    assert "매수" in body and "매도" in body
    assert "아직 거래가 없어요" in body
    assert "recentTrades(" in body


# ---- 자산 구성·등급 분포 도넛 ----
def test_donut_is_an_accessible_svg_with_dash_segments():
    body = _func("donutSvg")
    assert "stroke-dasharray" in body and "stroke-dashoffset" in body
    assert 'role="img"' in body and "aria-label" in body
    assert "donutSegments(" in body


def test_asset_panel_shows_cash_and_stock_with_percent_and_amount():
    body = _func("assetPanelHtml")
    assert "assetSplit(" in body
    assert "현금" in body and "주식 평가" in body
    assert "#30d158" in body and "#0a84ff" in body


def test_grade_panel_uses_the_same_grade_colors_as_the_list_badges():
    assert re.search(r"GRADE_FILL\s*=\s*\{[^}]*'S'[^}]*'A'[^}]*'B'", _html(), re.S)
    body = _func("gradePanelHtml")
    assert "gradeDistribution(" in body and "GRADE_FILL" in body
    assert "recsPanelBody(" in body  # 로딩·빈 상태는 공통 몸통이 처리


def test_holdings_and_rank_panels():
    assert "holdingsByPnl(" in _func("holdingsPanelHtml")
    assert "보유 종목이 늘어나면 손익 순으로 정렬돼요" in _func("holdingsPanelHtml")
    assert "보유 중인 종목이 없어요" in _func("holdingsPanelHtml")
    rank = _func("rankPanelHtml")
    assert "scoreRanking(" in rank and "GRADE_FILL" in rank
    assert "recsPanelBody(" in rank


def test_recs_panels_show_skeleton_while_loading_and_empty_text_when_none():
    body = _func("recsPanelBody")
    assert "recsViewState(" in body and "loading" in body and 'class="sk' in body
    assert "추천 종목이 없어요" in body


# ---- 구성: PC 는 5개, 모바일은 등급 분포 제외 ----
def test_panels_order_and_mobile_omits_grade_distribution():
    body = _func("summaryPanelsHtml")
    order = [body.index(n + "(") for n in ("accountPanelHtml", "assetPanelHtml", "gradePanelHtml", "holdingsPanelHtml", "rankPanelHtml")]
    assert order == sorted(order)
    assert "!mobile" in body  # 등급 분포는 길이 때문에 모바일에서 뺀다(명세 2항)


def test_summary_pane_composes_hint_state_and_panels():
    body = _func("summaryPaneHtml")
    assert "summaryPanelsHtml(false)" in body
    assert "종목을 선택하세요" in body  # 한 줄 안내로 남긴다
    assert "recsViewState(" in body and "매수·매도" in body  # 오류 경고 카드는 유지


def test_summary_state_and_segment_switch_rerender():
    s = _html()
    assert re.search(r"let summarySeg\s*=\s*'pnl'", s)
    body = _func("setSummarySeg")
    assert "summarySeg = " in body and "renderDetailPane()" in body


def test_order_code_is_untouched_by_this_feature():
    for name in ("executeSelectedBuy", "updateBuyModalCalcs", "calculateQtyFromAmount", "confirmReset"):
        for token in ("summarySeg", "tradeStats", "summaryPanelsHtml"):
            assert token not in _func(name), (name, token)


def test_bars_keep_a_slim_fixed_width_on_wide_screens():
    # 막대 폭이 칸 폭 100%라서 전체화면에서 거래가 두세 건이면 막대가 큰 블록처럼 퍼졌다.
    # 막대는 칸 가운데에 최대 56px, 제목과 차트는 한 블록(최대 600px)으로 묶어 오른쪽(최신 쪽)에 붙인다
    bars = _func("pnlBarsHtml")
    assert "max-w-[56px]" in bars and "left-1/2" in bars and "-translate-x-1/2" in bars
    assert not re.search(r"absolute inset-x-0 \$\{b\.up", bars)  # 칸 폭을 그대로 쓰던 막대
    assert "w-full" in bars.split("max-w-[56px]")[0].split("<div")[-1]  # 좁은 화면에서는 칸 폭을 따른다(상한 안에서)
    account = _func("accountPanelHtml")
    block = account[account.index("최근 매도 거래별 실현 손익") - 400:account.index("pnlBarsHtml(")]
    assert "max-w-[600px]" in block and "ml-auto" in block  # 제목도 같은 블록 안에 있어 차트와 떨어지지 않는다
