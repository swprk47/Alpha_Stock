"""PC 보유 종목 상세의 "거래 이력" 패널 검증.

서버가 주는 history(BUY·SELL, 종목코드 포함)에서 그 종목의 "현재 보유 구간" 거래만 골라 보여 준다:
추가 매수·부분 매도는 포함하고, 전량 청산 뒤 다시 산 경우 이전 거래는 뺀다. 서버 변경은 없고 주문 코드도 그대로다.
모바일 보유 아코디언에는 없다(시안 LayoutM3Holdings 에 거래 이력이 없다).

계산은 index.html 의 `// <summary-logic>` 구간을 node 로 그대로 실행해 확인하고, 실제 서버 매니저로 만든 history 와
교차 확인한다(고른 구간의 수량·평균 매입가가 서버의 보유 종목 값과 같아야 한다).
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
    d = tmp_path_factory.mktemp("tradesjs")
    src = _logic_source()

    def _run(expr):
        f = d / "t.js"
        f.write_text(src + "\nconsole.log(JSON.stringify(" + expr + "));\n", encoding="utf-8")
        out = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    return _run


def e(type_, code, qty, price, day, pnl=None):
    """JS 리터럴로 쓸 history 항목."""
    extra = f",pnl:{pnl}" if pnl is not None else ""
    return f"{{type:'{type_}',code:'{code}',name:'{code}',quantity:{qty},price:{price},date:'2026-10-{day:02d} 10:00:00'{extra}}}"


def H(*items):
    return "[" + ",".join(items) + "]"


# ---- 현재 보유 구간의 거래만 ----
@needs_node
def test_single_buy_is_one_trade(run):
    rows = run(f"positionTrades({H(e('BUY', 'A', 2, 15250, 24))}, 'A')")
    assert len(rows) == 1 and rows[0]["type"] == "BUY"


@needs_node
def test_additional_buys_are_all_part_of_the_position(run):
    h = H(e("BUY", "A", 1, 15000, 20), e("BUY", "A", 1, 15500, 21))
    rows = run(f"positionTrades({h}, 'A')")
    assert [r["price"] for r in rows] == [15000, 15500]  # 시간순(평균 매입가 15,250원이 어떻게 나왔는지 보인다)


@needs_node
def test_rebuy_after_full_sell_starts_a_new_position(run):
    h = H(e("BUY", "A", 2, 15000, 12), e("SELL", "A", 2, 16000, 14, pnl=1900), e("BUY", "A", 1, 15500, 20))
    rows = run(f"positionTrades({h}, 'A')")
    assert [r["type"] for r in rows] == ["BUY"] and rows[0]["price"] == 15500  # 청산된 한 바퀴는 현재 보유가 아니다


@needs_node
def test_partial_sell_stays_in_the_position(run):
    h = H(e("BUY", "A", 3, 15000, 12), e("SELL", "A", 1, 16000, 14, pnl=900))
    rows = run(f"positionTrades({h}, 'A')")
    assert [r["type"] for r in rows] == ["BUY", "SELL"]


@needs_node
def test_other_codes_are_ignored(run):
    h = H(e("BUY", "A", 1, 100, 10), e("BUY", "B", 5, 200, 11), e("BUY", "A", 1, 110, 12))
    assert [r["code"] for r in run(f"positionTrades({h}, 'A')")] == ["A", "A"]
    assert [r["code"] for r in run(f"positionTrades({h}, 'B')")] == ["B"]


@needs_node
def test_fully_sold_or_unknown_code_has_no_position(run):
    h = H(e("BUY", "A", 2, 15000, 12), e("SELL", "A", 2, 16000, 14, pnl=1900))
    assert run(f"positionTrades({h}, 'A')") == []
    assert run(f"positionTrades({h}, 'Z')") == []


@needs_node
def test_missing_or_broken_history_gives_nothing(run):
    for bad in ("undefined", "null", "[]", "'x'", "[null, 5]"):
        assert run(f"positionTrades({bad}, 'A')") == [], bad


@needs_node
def test_sell_without_a_buy_does_not_invent_a_position(run):
    # 일관되지 않은 기록(매수 없이 매도)은 보여 줄 구간이 없다
    assert run(f"positionTrades({H(e('SELL', 'A', 1, 100, 10, pnl=1))}, 'A')") == []


@needs_node
def test_fractional_quantities_use_the_servers_rounding(run):
    # 0.1 + 0.2 = 0.30000000000000004 → 소수 4자리로 맞춰 0.3 을 파는 순간 청산
    h = H(e("BUY", "A", 0.1, 1000, 10), e("BUY", "A", 0.2, 1000, 11), e("SELL", "A", 0.3, 1100, 12, pnl=10))
    assert run(f"positionTrades({h}, 'A')") == []
    h2 = H(e("BUY", "A", 0.1, 1000, 10), e("BUY", "A", 0.2, 1000, 11), e("SELL", "A", 0.1, 1100, 12, pnl=10))
    assert len(run(f"positionTrades({h2}, 'A')")) == 3


# ---- 화면용 행: 최신이 위, 최대 N건, 손익은 매도에만 ----
@needs_node
def test_rows_are_newest_first_with_month_day_and_sell_pnl_only(run):
    h = H(e("BUY", "A", 3, 15000, 12), e("SELL", "A", 1, 16000, 14, pnl=900))
    res = run(f"holdingTradeRows({h}, 'A', 8)")
    assert res["more"] == 0
    assert [r["type"] for r in res["rows"]] == ["SELL", "BUY"]
    assert res["rows"][0]["date"] == "10/14" and res["rows"][0]["pnl"] == 900
    assert res["rows"][1]["pnl"] is None and res["rows"][1]["qty"] == 3 and res["rows"][1]["price"] == 15000


@needs_node
def test_rows_are_capped_and_report_the_rest(run):
    buys = [e("BUY", "A", 1, 1000 + i, 10 + i) for i in range(10)]
    res = run(f"holdingTradeRows({H(*buys)}, 'A', 8)")
    assert len(res["rows"]) == 8 and res["more"] == 2
    assert res["rows"][0]["price"] == 1009  # 최신부터


@needs_node
def test_rows_for_no_position_are_empty(run):
    assert run("holdingTradeRows([], 'A', 8)") == {"rows": [], "more": 0}


# ---- 실제 서버로 만든 history 와의 교차 확인 ----
@needs_node
def test_picked_position_matches_the_servers_quantity_and_average_price(run, tmp_path):
    """서버(MultiUserPortfolioManager)로 추가 매수·전량 청산 뒤 재매수·소수점 부분 매도를 한 history 를 만들고,
    화면 함수가 고른 구간의 수량·평균 매입가가 서버의 보유 종목 값과 같은지 본다."""
    from portfolio import MultiUserPortfolioManager
    from storage import UserStore

    mgr = MultiUserPortfolioManager(initial_balance=1_000_000, store=UserStore(str(tmp_path)))
    u = "dev:cross"

    def buy(code, price, qty):
        mgr.buy(u, code, code, price, qty, int(price * 1.065), int(price * 0.97))

    buy("A", 15000, 1)
    buy("A", 15500, 1)            # 추가 매수: 평균 매입가 15,250원
    buy("B", 10000, 2)
    mgr.sell(u, "B", 10100)       # B 전량 청산
    buy("B", 10200, 1)            # 청산 뒤 재매수: 현재 보유 구간은 이 한 건
    buy("C", 5000, 0.5)
    mgr.sell(u, "C", 5100, 0.2)   # C 부분 매도(소수점)
    buy("D", 7000, 1)
    mgr.sell(u, "D", 7100)        # D 전량 청산: 현재 보유 아님

    summary = mgr.get_summary(u, current_prices={"A": 15000, "B": 10200, "C": 5000, "D": 7000})
    holdings = {h["code"]: h for h in summary["holdings"]}
    assert set(holdings) == {"A", "B", "C"}
    hist = json.dumps(summary["history"])

    for code, h in holdings.items():
        trades = run(f"positionTrades({hist}, {json.dumps(code)})")
        qty, avg = 0.0, 0
        for t in trades:
            if t["type"] == "BUY":
                gross = int(t["price"] * t["quantity"])
                total = round(qty + t["quantity"], 4)
                avg = t["price"] if qty <= 1e-6 else int((avg * qty + gross) / total)
                qty = total
            else:
                qty = round(qty - t["quantity"], 4)  # 부분 매도는 평균 매입가를 바꾸지 않는다
        assert qty == pytest.approx(h["quantity"]), code
        assert avg == h["avg_price"], code
    assert run(f"positionTrades({hist}, 'D')") == []  # 청산한 종목은 보여 줄 구간이 없다
    assert len(run(f"positionTrades({hist}, 'B')")) == 1


# ---- 화면 구조 ----
def test_holding_detail_has_a_trade_history_panel_next_to_the_sell_panel():
    body = _func("holdingDetailHtml")
    assert "holdingTradesHtml(" in body
    assert "grid-cols-[minmax(0,1fr)_360px]" in body  # 시안: 거래 이력(1fr) | 매도 패널(360px)
    assert "sellBoxHtml(h, false)" in body  # 매도 패널(버튼 포함)은 sellBoxHtml


def test_trade_history_panel_content_and_states():
    body = _func("holdingTradesHtml")
    assert "거래 이력" in body
    assert "holdingTradeRows(" in body and "currentPortfolio" in body
    assert "거래 기록이 없어요" in body
    assert "외 " in body  # 8건을 넘으면 나머지 건수
    assert "매수" in body and "매도" in body
    assert "pnlTextClass(" in body  # 손익은 부호와 함께 색(이익 빨강·손실 파랑)


def test_buy_sell_labels_are_not_colored_as_up_down():
    body = _func("holdingTradesHtml")
    # 매수/매도 글자는 상승·하락 색이 아니라 중립(명세 5항: 그 색은 상승·하락·손익에만)
    assert "bg-white/10" in body
    assert "#ff6a60" not in body and "#5aa9ff" not in body


def test_stale_comment_about_missing_trade_history_is_corrected():
    assert "거래 이력은 서버가 주지 않아" not in _html()


def test_mobile_holdings_accordion_has_no_trade_history():
    # 시안 M3(모바일 보유)에는 거래 이력이 없다
    assert "holdingTradesHtml(" not in _func("renderHoldings")


def test_order_code_is_untouched_by_this_feature():
    for name in ("executeSell", "executeInlineBuy"):
        body = _func(name)
        assert "positionTrades" not in body and "holdingTrade" not in body, name
