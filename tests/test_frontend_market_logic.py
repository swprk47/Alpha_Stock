"""장 상태 순수 함수(// <market-logic>): 태그 라벨, 탭 대상, 시간표 막대 계산, 한국 시각.

장 상태 판단은 서버(market_data.market_session)가 하고 화면은 그 결과(state)만 쓴다. 시계는 팝업의 현재 시각(V) 표시에만 쓰며
판단에 쓰지 않는다(공휴일을 모르므로). 시간표 값은 공식 확인된 것만 넣는다: NXT 세 구간, KRX 정규장.
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
    src = _section("market-logic")

    def _run(expr):
        f = tmp_path / "t.js"
        f.write_text(src + f"\nconsole.log(JSON.stringify({expr}));\n", encoding="utf-8")
        out = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    return _run


def _ms(state, nxt=True):
    return json.dumps({"state": state, "nxt_listed": nxt})


def _clock(minutes, weekend=False):
    return json.dumps({"min": minutes, "label": f"{minutes // 60:02d}:{minutes % 60:02d}", "weekend": weekend})


# ── 태그 ──


@needs_node
@pytest.mark.parametrize("state,label", [("regular", "정규장"), ("pre", "프리마켓"), ("after", "애프터마켓"), ("closed", "장 마감")])
def test_session_tag_labels(run, state, label):
    tag = run(f"sessionTag({_ms(state)})")
    assert tag == {"label": label, "tone": state}


@needs_node
@pytest.mark.parametrize("ms", ["null", "undefined", "{}", "'after'", _ms("unknown"), _ms("weird"), '{"state": 3}'])
def test_session_tag_is_null_for_unknown_or_garbage(run, ms):
    assert run(f"sessionTag({ms})") is None


@needs_node
def test_colors_follow_the_spec(run):
    assert run("MARKET_COLORS") == {"pre": "#64d2ff", "regular": "#30d158", "after": "#bf5af2", "closed": "#8e8e93"}


# ── 탭 ──


@needs_node
@pytest.mark.parametrize("ms,tabs", [
    (_ms("after", True), ["nxt", "krx"]), (_ms("after", False), ["krx"]),
    ("null", ["krx"]), ("{}", ["krx"]), ('{"nxt_listed": "true"}', ["krx"]),  # 정확히 true 일 때만
])
def test_available_tabs(run, ms, tabs):
    assert run(f"availableTabs({ms})") == tabs


# ── 시간표 막대 ──


@needs_node
def test_nxt_values_and_bar_geometry(run):
    m = run(f"hoursModel('nxt', {_ms('after')}, {_clock(1010)})")
    segs = {s["key"]: s for s in m["segments"]}
    assert [s["key"] for s in m["segments"]] == ["pre", "regular", "after"]
    assert [s["text"] for s in m["segments"]] == ["08:00 – 08:50", "09:00:30 – 15:20", "15:40 – 20:00"]
    assert segs["regular"]["name"] == "정규장 (메인마켓)"
    # 축 08:00~20:00 = 720분
    assert segs["pre"]["left"] == pytest.approx(0) and segs["pre"]["width"] == pytest.approx(50 / 720 * 100)
    assert segs["regular"]["left"] == pytest.approx(60 / 720 * 100) and segs["regular"]["width"] == pytest.approx(380 / 720 * 100)
    assert segs["after"]["left"] == pytest.approx(460 / 720 * 100) and segs["after"]["width"] == pytest.approx(260 / 720 * 100)
    assert segs["after"]["color"] == "#bf5af2"
    assert m["breaks"] == "08:50–09:00 · 15:20–15:40" and m["note"] == ""


@needs_node
def test_krx_has_only_the_regular_session_and_a_pending_note(run):
    m = run(f"hoursModel('krx', {_ms('regular')}, {_clock(600)})")
    assert [s["key"] for s in m["segments"]] == ["regular"]
    s = m["segments"][0]
    assert s["text"] == "09:00 – 15:30" and s["name"] == "정규장"
    assert s["left"] == pytest.approx(60 / 720 * 100) and s["width"] == pytest.approx(390 / 720 * 100)
    assert m["note"] == "그 밖의 시간(장전·장후 시간외, 프리·애프터마켓)은 확인 중이에요" and m["breaks"] == ""


@needs_node
def test_as_of_text_uses_the_check_date_not_an_official_date(run):
    assert run("marketAsOfText()") == "2026.10.29 확인 · 시간은 바뀔 수 있어요."


# ── 현재 시각 V ──


@needs_node
def test_marker_position_label_and_state_line(run):
    m = run(f"hoursModel('nxt', {_ms('after')}, {_clock(1010)})")  # 16:50
    assert m["outside"] is False
    assert m["marker"]["left"] == pytest.approx((1010 - 480) / 720 * 100)
    assert m["marker"]["label"] == "지금 16:50" and m["marker"]["align"] == "center"
    assert m["stateLine"] == "지금은 애프터마켓이에요"


@needs_node
@pytest.mark.parametrize("minutes,align", [(485, "start"), (1195, "end"), (480, "start"), (1200, "end"), (840, "center")])
def test_marker_label_alignment_at_the_edges(run, minutes, align):
    assert run(f"hoursModel('krx', {_ms('regular')}, {_clock(minutes)})")["marker"]["align"] == align


@needs_node
@pytest.mark.parametrize("clock,ms", [
    (_clock(479), _ms("pre")),             # 08:00 전
    (_clock(1201), _ms("after")),          # 20:00 후
    (_clock(600, weekend=True), _ms("regular")),   # 주말
    (_clock(600), _ms("closed")),          # 공휴일처럼 시계는 정규장인데 응답이 닫힘 → V 를 그리지 않는다(태그와 모순 방지)
])
def test_marker_hidden_outside_hours_weekend_and_when_closed(run, clock, ms):
    m = run(f"hoursModel('krx', {ms}, {clock})")
    assert m["marker"] is None and m["outside"] is True
    assert m["stateLine"] == "지금은 시간표 밖이에요"


@needs_node
def test_unknown_state_inside_hours_still_shows_the_marker_without_a_state_sentence(run):
    m = run(f"hoursModel('krx', {_ms('unknown')}, {_clock(600)})")
    assert m["marker"] is not None and m["stateLine"] == ""
    assert run(f"hoursModel('krx', null, {_clock(600)})")["marker"] is not None  # ms 자체가 없어도 죽지 않는다


@needs_node
def test_clock_may_be_missing(run):
    m = run(f"hoursModel('krx', {_ms('regular')}, null)")
    assert m["marker"] is None and m["outside"] is True


# ── 한국 시각 ──


@needs_node
def test_kst_clock_converts_from_utc(run):
    c = run("kstClock(new Date('2026-10-29T07:50:00Z'))")  # 목요일 16:50 KST
    assert c == {"min": 1010, "label": "16:50", "weekend": False}
    assert run("kstClock(new Date('2026-10-28T15:05:00Z'))") == {"min": 5, "label": "00:05", "weekend": False}  # KST 로는 다음 날 00:05(목)


@needs_node
def test_kst_clock_weekend_follows_korea_not_utc(run):
    assert run("kstClock(new Date('2026-10-31T03:00:00Z'))")["weekend"] is True        # 토요일 12:00 KST
    assert run("kstClock(new Date('2026-10-30T15:30:00Z'))")["weekend"] is True        # UTC 로는 금요일이지만 KST 토요일 00:30
    assert run("kstClock(new Date('2026-11-01T15:30:00Z'))")["weekend"] is False       # UTC 일요일이지만 KST 월요일 00:30
