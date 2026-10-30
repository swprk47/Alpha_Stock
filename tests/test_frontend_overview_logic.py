"""종목 개요 탭의 순수 로직(`// <overview-logic>` 구간): 탭, 카드 표시, 이스케이프, 상태 판단.

서버가 정제한 글자라도 화면은 반드시 이스케이프해서 넣는다. 구간은 DOM 없이 node 로 평가한다.
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


def _section(tag):
    m = re.search(rf"// <{tag}>\r?\n(.*?)// </{tag}>", _html(), re.S)
    assert m, f"{tag} 구간이 없습니다"
    return m.group(1)


@pytest.fixture
def run(tmp_path):
    src = _section("overview-logic")

    def _run(expr, **data):
        consts = "".join(f"const {k} = {json.dumps(v, ensure_ascii=False)};\n" for k, v in data.items())
        f = tmp_path / "t.js"
        f.write_text(src + "\n" + consts + f"console.log(JSON.stringify({expr}));\n", encoding="utf-8")
        out = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    return _run


# ── 응답 예시(서버 backend/overview.py 의 응답 모양) ──

ONE = {"aboutOpen": False, "layout": "one-col"}
TWO = {"aboutOpen": False, "layout": "two-col"}


def stock_data(**over):
    data = {
        "success": True, "code": "005930", "kind": "stock", "fetched_at": "2026-10-30 21:40:12",
        "source_url": "https://m.stock.naver.com/domestic/stock/005930/total",
        "about": {"status": "ok", "title": "회사 소개", "paragraphs": ["문단 하나.", "문단 둘.", "문단 셋."]},
        "facts": {"status": "ok", "items": [
            {"label": "업종", "value": "반도체와반도체장비", "note": ""},
            {"label": "시가총액", "value": "1,289조 1,044억", "note": "현재 시세 기준"},
            {"label": "PER", "value": "9.89배", "note": "2026.06. 실적 기준"},
        ]},
        "holdings": {"status": "empty", "items": []},
        "weights": {"status": "empty", "cards": []},
        "news": {"status": "ok", "items": [
            {"title": "삼성 공장 인허가", "office": "KBS", "time": "10.30 21:59", "url": "https://n.news.naver.com/mnews/article/052/1", "more": 0},
            {"title": "코스피 급락", "office": "연합뉴스TV", "time": "10.30 21:06", "url": "https://n.news.naver.com/mnews/article/422/2", "more": 3},
        ]},
    }
    data.update(over)
    return data


def etf_data(**over):
    data = {
        "success": True, "code": "069500", "kind": "etf", "fetched_at": "2026-10-30 21:40:12", "source_url": "",
        "about": {"status": "ok", "title": "이 ETF는", "paragraphs": ["설명 하나입니다."]},
        "facts": {"status": "ok", "items": [{"label": "기초지수", "value": "코스피 200", "note": ""}, {"label": "총보수", "value": "0.15%", "note": ""}]},
        "holdings": {"status": "ok", "items": [
            {"name": "삼성전자", "count": "6,969", "weight": 34.19}, {"name": "SK하이닉스", "count": "849", "weight": 27.4},
        ]},
        "weights": {"status": "ok", "cards": [
            {"key": "sector", "title": "업종별 비중", "total": 99.05, "items": [{"label": "IT", "weight": 66.12}, {"label": "산업재", "weight": 12.54}]},
        ]},
        "news": {"status": "empty", "items": []},
    }
    data.update(over)
    return data


def ready(data, kind=None):
    return {"status": "ready", "data": data}


FAILED_TEXT = "종목 정보를 불러오지 못했어요."


# ── 이스케이프 ──


@needs_node
def test_esc_escapes_markup(run):
    out = run("ovEsc(S)", S="<script>alert(1)</script>&\"'")
    assert "<" not in out and ">" not in out and "&lt;script&gt;" in out and "&amp;" in out
    assert run("ovEsc(null)") == "" and run("ovEsc(5)") == ""


@needs_node
def test_body_never_emits_raw_server_markup(run):
    evil = "<img src=x onerror=alert(1)>"
    data = etf_data()
    data["about"]["paragraphs"] = [evil]
    data["facts"]["items"][0]["value"] = evil
    data["holdings"]["items"][0]["name"] = evil
    data["weights"]["cards"][0]["items"][0]["label"] = evil
    data["news"] = {"status": "ok", "items": [{"title": evil, "office": evil, "time": evil, "more": 0,
                                               "url": 'https://n.news.naver.com/x"onmouseover="alert(1)'}]}
    html = run("ovBodyHtml(V, 'etf', O)", V=ready(data), O=ONE)
    assert "<img" not in html and "&lt;img" in html  # 글자로만 보인다
    assert '"onmouseover' not in html  # 속성 밖으로 빠져나가지 못한다


# ── 상태: 불러오는 중·실패·카드별 ──


@needs_node
def test_loading_shows_skeletons_and_failed_shows_retry(run):
    loading = run("ovBodyHtml(V, '', O)", V={"status": "loading"}, O=ONE)
    assert "sk" in loading and "aria-busy" in loading
    failed = run("ovBodyHtml(V, '', O)", V={"status": "failed"}, O=ONE)
    assert FAILED_TEXT in failed and "시세·매수 탭은 그대로 쓸 수 있어요." in failed
    assert "retryOverview()" in failed and "다시 시도" in failed and "min-h-[44px]" in failed


@needs_node
def test_card_states(run):
    data = stock_data(news={"status": "error", "title": ""})
    html = run("ovBodyHtml(V, 'stock', O)", V=ready(data), O=ONE)
    assert "뉴스를 불러오지 못했어요." in html and "다른 칸은 그대로 보여요." in html and "retryOverview()" in html
    assert "문단 둘." in html and "반도체와반도체장비" in html  # 다른 카드는 그대로
    # 소개 없음(우선주 등)
    empty_about = stock_data(about={"status": "empty", "title": "회사 소개", "paragraphs": []})
    html = run("ovBodyHtml(V, 'stock', O)", V=ready(empty_about), O=ONE)
    assert "이 종목은 네이버 증권에 회사 소개가 없어요. 우선주, 신규 상장, 스팩 종목에서 그럴 수 있어요." in html
    # ETN·종류 불명
    etn = stock_data(kind="etn", about={"status": "empty", "title": "", "paragraphs": []}, facts={"status": "empty", "items": []})
    html = run("ovBodyHtml(V, 'etn', O)", V=ready(etn), O=ONE)
    assert "이 종목의 개요 정보는 아직 제공하지 않아요. 시세·매수 탭은 그대로 쓸 수 있어요." in html
    assert "기본 정보" not in html  # 비어 있는 카드는 제목만 남기지 않는다


@needs_node
def test_error_cards_use_their_own_messages(run):
    msgs = {
        "about": "소개를 불러오지 못했어요.", "facts": "기본 정보를 불러오지 못했어요.",
        "holdings": "보유 자산 정보를 불러오지 못했어요.", "weights": "비중 정보를 불러오지 못했어요.",
    }
    for key, msg in msgs.items():
        data = etf_data(**{key: {"status": "error", "title": ""}})
        html = run("ovBodyHtml(V, 'etf', O)", V=ready(data), O=ONE)
        assert msg in html, key


@needs_node
def test_all_failed_collapses_to_one_message(run):
    err = {"status": "error", "title": ""}
    data = stock_data(about=err, facts=err, holdings=err, weights=err, news=err)
    assert run("ovAllFailed(D)", D=data) is True
    html = run("ovBodyHtml(V, '', O)", V=ready(data), O=ONE)
    assert html.count(FAILED_TEXT) == 1 and "회사 소개" not in html and "retryOverview()" in html
    assert run("ovAllFailed(D)", D=stock_data()) is False
    assert run("ovAllFailed(D)", D=stock_data(news=err)) is False
    assert run("ovAllFailed(null)") is True and run("ovAllFailed(undefined)") is True


# ── 비중·보유 자산 ──


@needs_node
def test_bar_width_and_weight_text(run):
    assert run("[ovBarWidth(null), ovBarWidth('-'), ovBarWidth(NaN), ovBarWidth(-5), ovBarWidth(250), ovBarWidth(34.19), ovBarWidth('34')]") == [0, 0, 0, 0, 100, 34.19, 0]
    assert run("[ovWeightText(34.19), ovWeightText(2.3), ovWeightText(null), ovWeightText('x'), ovWeightText(NaN)]") == ["34.19%", "2.30%", "", "", ""]


@needs_node
def test_holdings_with_weights_show_bars(run):
    html = run("ovBodyHtml(V, 'etf', O)", V=ready(etf_data()), O=ONE)
    assert "보유 자산 상위 10" in html and "34.19%" in html and "27.40%" in html
    assert 'width:34.19%' in html and "6,969" not in html  # 비중이 있으면 막대와 비중만(수량은 이름만 있는 경우에)


@needs_node
def test_holdings_without_any_weight_show_names_and_counts_only(run):
    data = etf_data(holdings={"status": "ok", "items": [
        {"name": "NVIDIA CORP", "count": "348", "weight": None}, {"name": "APPLE INC", "count": "210", "weight": None}]})
    html = run("ovBodyHtml(V, 'etf', O)", V=ready(data), O=ONE)
    assert "NVIDIA CORP" in html and "348" in html and "이 ETF는 비중을 제공하지 않아서 이름과 보유 수량만 보여요." in html
    assert 'width:' not in html.split("보유 자산 상위 10")[1].split("업종별 비중")[0]  # 막대 없음
    # 이름도 못 받은(목록이 빈) 경우
    empty = etf_data(holdings={"status": "empty", "items": []})
    assert "이 ETF는 보유 자산 정보를 제공하지 않아요." in run("ovBodyHtml(V, 'etf', O)", V=ready(empty), O=ONE)


@needs_node
def test_weights_cards_use_titles_network_total_and_never_sum(run):
    data = etf_data(weights={"status": "ok", "cards": [
        {"key": "sector", "title": "업종별 비중", "total": 99.05, "items": [{"label": "IT", "weight": 60.0}, {"label": "금융", "weight": 30.0}]},
        {"key": "country", "title": "국가별 비중", "total": None, "items": [{"label": "미국", "weight": 94.73}]},
    ]})
    html = run("ovBodyHtml(V, 'etf', O)", V=ready(data), O=ONE)
    assert "업종별 비중" in html and "국가별 비중" in html and html.index("업종별 비중") < html.index("국가별 비중")
    assert "네이버 합계 99.05%" in html and "60.00%" in html
    assert "90.00" not in html and "90%" not in html  # 앱이 합계를 계산해 보이지 않는다
    assert "#0a84ff" in html and "#ffb340" in html  # 항목마다 다른 색, 범례 점과 같은 색


# ── 뉴스·푸터 ──


@needs_node
def test_news_more_link_and_attrs(run):
    html = run("ovBodyHtml(V, 'stock', O)", V=ready(stock_data()), O=ONE)
    assert "외 3건" in html and "삼성 공장 인허가" in html and "KBS" in html and "10.30 21:59" in html
    assert 'target="_blank"' in html and 'rel="noopener noreferrer"' in html
    assert "min-h-[44px]" in html
    assert "네이버가 주는 헤드라인을 그대로 보여요. 종목과 크게 관련 없는 기사가 섞일 수 있어요." in html
    assert run("ovBodyHtml(V, 'etf', O)", V=ready(etf_data()), O=ONE).count("표시할 뉴스가 없어요.") == 1


@needs_node
def test_footer_text(run):
    stock = run("ovBodyHtml(V, 'stock', O)", V=ready(stock_data()), O=ONE)
    assert "출처: " in stock and "네이버 증권" in stock and "21:40에 가져왔어요" in stock
    assert 'href="https://m.stock.naver.com/domestic/stock/005930/total"' in stock
    assert "정보 제공용이며 투자 권유가 아니에요." in stock
    assert "구성 비중의 기준일은 제공되지 않아요." not in stock
    etf = run("ovBodyHtml(V, 'etf', O)", V=ready(etf_data()), O=ONE)
    assert "구성 비중의 기준일은 제공되지 않아요." in etf
    assert "<a " not in etf.split("출처:")[1].split("정보 제공용")[0]  # 주소가 없으면 링크 없이 글자만
    no_time = run("ovBodyHtml(V, 'etf', O)", V=ready(etf_data(fetched_at="")), O=ONE)
    assert "에 가져왔어요" not in no_time


# ── 본문 배치 ──


@needs_node
def test_one_col_order_and_two_col_layout(run):
    data = etf_data(news={"status": "ok", "items": [{"title": "T", "office": "O", "time": "", "url": "https://n.news.naver.com/a", "more": 0}]})
    one = run("ovBodyHtml(V, 'etf', O)", V=ready(data), O=ONE)
    order = ["이 ETF는", "기본 정보", "보유 자산 상위 10", "업종별 비중", "최근 뉴스"]
    assert [one.index(t) for t in order] == sorted(one.index(t) for t in order)
    assert "grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]" not in one
    two = run("ovBodyHtml(V, 'etf', O)", V=ready(data), O=TWO)
    assert "grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]" in two
    assert two.index("이 ETF는") < two.index("보유 자산 상위 10") < two.index("최근 뉴스")


# ── 탭 ──


@needs_node
def test_tabs_html_reuses_existing_tab_look(run):
    html = run("ovTabsHtml('overview')")
    assert 'role="tablist"' in html and html.count('role="tab"') == 2
    assert "시세·매수" in html and "개요" in html
    assert re.search(r'aria-selected="true"[^>]*onclick="selectOverviewTab\(\'overview\'\)"', html) or "selectOverviewTab('overview')" in html
    assert "bg-[#f5f5f7]" in html and "min-h-[40px]" in html and "rounded-[9px]" in html
    trade = run("ovTabsHtml('trade')")
    assert trade.index("시세·매수") < trade.index("개요")
    assert 'aria-selected="true"' in trade.split("개요")[0] and 'aria-selected="false"' in trade.split("시세·매수")[1]


@needs_node
def test_next_tab_and_should_fetch(run):
    assert run("[ovNextTab('trade', 'overview'), ovNextTab('overview', 'trade'), ovNextTab('trade', 'x'), ovNextTab('overview', undefined)]") == \
        ["overview", "trade", "trade", "trade"]
    assert run("ovShouldFetch(undefined, 0, false)") is True
    entry = {"data": {}, "fetchedAt": 1000, "hasError": False}
    assert run("ovShouldFetch(E, 1000 + 299999, false)", E=entry) is False
    assert run("ovShouldFetch(E, 1000 + 300000, false)", E=entry) is True
    assert run("ovShouldFetch(E, 1000 + 10, true)", E=entry) is False  # 실패가 없으면 force 여도 다시 받지 않는다
    assert run("ovShouldFetch(E, 1000 + 10, true)", E=dict(entry, hasError=True)) is True
    assert run("ovShouldFetch(E, 1000 + 10, false)", E=dict(entry, hasError=True)) is False


# ── ETF 긴 설명 접기 ──


@needs_node
def test_long_etf_about_is_clamped_with_more_button(run):
    long_text = "가" * 550
    card = {"status": "ok", "title": "이 ETF는", "paragraphs": [long_text]}
    closed = run("ovAboutHtml(C, false)", C=card)
    assert "-webkit-line-clamp:4" in closed and "더보기" in closed and "toggleOverviewAbout()" in closed
    assert long_text in closed  # 원문을 자르지 않는다. 줄 수만 제한한다
    assert "min-h-[44px]" in closed
    opened = run("ovAboutHtml(C, true)", C=card)
    assert "-webkit-line-clamp" not in opened and "접기" in opened
    short = run("ovAboutHtml(C, false)", C={"status": "ok", "title": "이 ETF는", "paragraphs": ["가" * 100]})
    assert "더보기" not in short and "-webkit-line-clamp" not in short
    stock = run("ovAboutHtml(C, false)", C={"status": "ok", "title": "회사 소개", "paragraphs": [long_text]})
    assert "더보기" not in stock  # 주식 소개는 접지 않는다


# ── 크기 규칙 ──


def test_no_font_below_13px_or_touch_below_44px_in_section():
    src = _section("overview-logic")
    assert not re.search(r"text-xs|text-\[(?:9|10|11|12)(?:\.\d+)?px\]", src)
    for m in re.finditer(r"<button[^>]*>", src):
        assert "min-h-[44px]" in m.group(0) or "min-h-[40px]" in m.group(0), m.group(0)  # 탭은 기존 탭과 같은 40px
