"""시세 조회에 실패한 보유 종목(price_stale === true)의 표시.

서버는 시세를 못 받으면 현재가를 평균 매입가로 대신하고 그 값으로 평가금액·손익·신호를 계산한다.
그 값이 실시간 시세·손익처럼 보이지 않게 하되, 같은 말이 한 화면에 여러 번 나오지 않도록 자리마다 한 번만 말한다.
- 보유 행: 가격 자리에 "—", 그 아래 주의 아이콘 + "시세 없음" (손익 알약 없음)
- 펼친 카드·PC 상세: 평가 금액·손익이 들어갈 자리에 칸 하나(설명 한 문장). 안내 띠·차트 제목·기준선 문구 없음
- 계좌 카드: 주식 평가 뒤 "*"와 "* 1종목은 매입가 기준" 한 줄
price_stale 이 없거나 false 면(옛 서버 포함) 지금과 같다.
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
    src = "\n".join([_section("stale-logic"), _section("summary-logic")])

    def _run(expr):
        f = tmp_path / "t.js"
        f.write_text(src + f"\nconsole.log(JSON.stringify({expr}));\n", encoding="utf-8")
        out = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    return _run


# ── 순수 함수 ──


@needs_node
@pytest.mark.parametrize("h,expected", [
    ("{price_stale: true}", True),
    ("{price_stale: false}", False),
    ("{}", False),                       # 옛 서버: 필드가 없으면 지금처럼 정상으로 본다
    ("{price_stale: 'true'}", False),    # 정확히 true 일 때만
    ("{price_stale: 1}", False),
    ("null", False),
    ("undefined", False),
])
def test_only_an_exact_true_means_the_price_was_not_received(run, h, expected):
    assert run(f"isPriceStale({h})") is expected


@needs_node
def test_stale_holdings_are_counted_and_filtered(run):
    hs = "[{code:'a', price_stale:true}, {code:'b', price_stale:false}, {code:'c'}, {code:'d', price_stale:true}]"
    assert run(f"staleHoldingCount({hs})") == 2
    assert [h["code"] for h in run(f"nonStaleHoldings({hs})")] == ["b", "c"]
    assert run("staleHoldingCount(null)") == 0 and run("staleHoldingCount(undefined)") == 0
    assert run("nonStaleHoldings('x')") == []


@needs_node
def test_row_price_is_a_dash_with_the_icon_and_short_label_and_no_number(run):
    html = run("staleRowPriceHtml()")
    assert "—" in html and "시세 없음" in html and "triangle-alert" in html and "text-[#ff9f0a]" in html
    assert not re.search(r"\d", re.sub(r"text-\[#ff9f0a\]|text-\[#a9aebf\]|text-\[\d+px\]|text-sm|gap-\S+|justify-\S+|w-\S+|h-\S+", "", html))
    # 손익 알약(이전 시안의 "—" 알약)과 이득·손실 색은 없다
    assert "min-w-[62px]" not in html and "bg-[#ff453a]" not in html and "bg-[#0a84ff]" not in html


@needs_node
def test_header_price_is_a_dash_with_the_icon_and_label(run):
    html = run("staleHeaderPriceHtml()")
    assert "—" in html and "시세 없음" in html and "triangle-alert" in html and "justify-end" in html
    assert not re.search(r"\d", re.sub(r"text-\[#ff9f0a\]|text-\[#a9aebf\]|text-\[\d+px\]|text-xl|text-\S+|font-\S+|gap-\S+", "", html))


@needs_node
def test_missing_cell_says_it_once_where_the_numbers_would_be(run):
    html = run("staleCellHtml()")
    assert "평가 금액 · 손익" in html
    assert "현재가를 못 가져와 계산할 수 없어요" in html and "익절·손절 경보도 이 종목은 멈춰 있어요" in html
    assert "col-span-2" in html  # 평가 금액·평가 손익 두 칸 자리를 합쳐 쓴다


@needs_node
def test_account_notice_text_uses_the_count_and_vanishes_at_zero(run):
    assert run("staleNoticeText(1)") == "1종목은 매입가 기준"
    assert run("staleNoticeText(3)") == "3종목은 매입가 기준"
    assert run("staleNoticeText(0)") == ""
    assert run("staleExcludedText(2)") == "시세를 못 받은 2종목은 뺐어요"
    assert run("staleExcludedText(0)") == ""


@needs_node
def test_chart_price_slot_is_blank_but_keeps_its_height_when_stale(run):
    # 차트 제목은 그대로 두고, 가격 자리는 비워 두되(호버하면 그 날짜의 가격이 채워진다) 높이는 유지한다
    assert run("holdingPriceText({current_price: 22150, price_stale: true})") == "&nbsp;"
    assert run("holdingPriceText({current_price: 22150, price_stale: false})") == "22,150원"
    assert run("holdingPriceText({current_price: 22150})") == "22,150원"


@needs_node
def test_pnl_ranking_leaves_out_stale_holdings_and_is_unchanged_otherwise(run):
    live = "[{name:'a', pnl_pct: 1.5}, {name:'b', pnl_pct: -2}, {name:'c', pnl_pct: 3}]"
    assert run(f"holdingsByPnl({live})") == [
        {"name": "c", "pnlPct": 3}, {"name": "a", "pnlPct": 1.5}, {"name": "b", "pnlPct": -2}]
    mixed = "[{name:'a', pnl_pct: 1.5}, {name:'x', pnl_pct: -0.21, price_stale: true}, {name:'c', pnl_pct: 3, price_stale: false}]"
    assert [r["name"] for r in run(f"holdingsByPnl({mixed})")] == ["c", "a"]
    assert run("holdingsByPnl([{name:'x', pnl_pct: -0.21, price_stale: true}])") == []


# ── 화면에 붙인 곳 ──


def test_old_wordy_pieces_are_gone():
    s = _html()
    for gone in ("stalePriceHtml", "stalePillHtml", "staleBannerHtml", "시세 확인 못 함", "현재가를 가져오지 못했어요"):
        assert gone not in s, f"{gone} 이 남아 있습니다"


def test_holding_row_swaps_price_and_pill_for_one_block_only_when_stale():
    body = _func("renderHoldings")
    assert "staleRowPriceHtml()" in body
    # 정상일 때의 표시는 그대로
    assert "${h.current_price.toLocaleString()}원" in body and "${pnlSign}${h.pnl_pct}%" in body


def test_mobile_card_has_no_banner_and_one_merged_cell():
    body = _func("renderHoldings")
    assert "staleCellHtml()" in body
    assert "holdingPriceText(h)" in body  # 차트 가격 자리
    assert "statCell('평가 금액'" in body and "statCell('평가 손익'" in body  # 정상일 때는 두 칸 그대로
    # 시세 실패일 때는 두 칸 대신 합친 칸 하나
    assert re.search(r"isPriceStale\(h\) \? staleCellHtml\(\) : `", body) or re.search(r"stale \? staleCellHtml\(\)", body)


def test_pc_detail_swaps_header_and_cells_and_drops_banner_chart_title_and_baseline_text():
    body = _func("holdingDetailHtml")
    assert "staleHeaderPriceHtml()" in body and "staleCellHtml()" in body
    assert "pcChartPanel(holdingPriceText(h))" in body
    assert "statCell('평가 금액'" in body and "statCell('평가 손익'" in body
    # 기준선 가운데의 현재 가격 글자는 시세 실패일 때 아예 그리지 않는다(문구를 늘리지 않는다)
    assert "현재 ${h.current_price.toLocaleString()}원" in body
    mid = body[body.index("손절 ${h.stop_loss_price"):body.index("익절 ${h.target_price")]
    assert "isPriceStale(h) ? ''" in mid
    marker = body[body.index("absolute -top-[5px]"):]
    assert "isPriceStale(h)" in body[:body.index("absolute -top-[5px]")][-400:] or "isPriceStale(h)" in marker[:200]


def test_account_card_marks_the_stock_value_and_adds_a_footnote_line():
    s = _html()
    assert 'id="staleNotice"' in s and 'id="staleMark"' in s
    # 표시 순서: 주식 평가 금액 바로 뒤에 "*", 그 아래 오른쪽 정렬 각주
    assert s.index('id="stockEval"') < s.index('id="staleMark"') < s.index('id="staleNotice"')
    body = _func("renderPortfolio")
    assert "staleHoldingCount(data.holdings)" in body and "staleNoticeText(" in body
    assert "staleMark" in body and "staleNotice" in body


def test_summary_panel_leaves_stale_holdings_out_with_a_note():
    body = _func("holdingsPanelHtml")
    assert "staleHoldingCount(p.holdings)" in body and "staleExcludedText(" in body
    # 보유 종목이 있는데 전부 시세를 못 받은 경우 "보유 중인 종목이 없어요" 라고 하지 않는다
    assert "손익을 계산하지 못했어요" in body


def test_live_server_without_the_field_keeps_every_old_expression():
    detail = _func("holdingDetailHtml")
    assert "signedWon(h.unrealized_pnl)" in detail and "${h.eval_amount.toLocaleString()}원" in detail
    row = _func("renderHoldings")
    assert "${h.eval_amount.toLocaleString()}원" in row and "${pnlSign}${h.unrealized_pnl.toLocaleString()}원" in row
