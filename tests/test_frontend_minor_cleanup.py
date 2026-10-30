"""미뤄 둔 사소한 항목 정리(리뷰 지적): 로그아웃 시 설정 초기화, 설정 토글 응답 확인, 한국 시각을 Intl 없이 계산.

- 로그아웃하거나 로그인이 만료돼도 이전 사용자의 "장 마감 중 거래 · 차단" 표시가 메뉴에 남지 않게 기본값(허용)으로 되돌린다.
- /api/settings 응답이 올바른 모양일 때만 화면 설정에 반영한다(없거나 이상하면 반영하지 않고 안내).
- 한국은 서머타임이 없으므로 UTC+9 산술로 계산한다: 오래된 WebView 에서 Intl.formatToParts·timeZone·hourCycle 이 없거나 다르게 동작해도 팝업이 열린다.
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


def _node(script, tmp_path):
    f = tmp_path / "t.js"
    f.write_text(script, encoding="utf-8")
    out = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.fixture
def run(tmp_path):
    src = _section("market-logic")
    return lambda expr, pre="": _node(pre + src + f"\nconsole.log(JSON.stringify({expr}));\n", tmp_path)


# ── 설정 응답 확인 ──


@needs_node
@pytest.mark.parametrize("data,expected", [
    ("{settings: {allow_closed_trading: false}}", {"allow_closed_trading": False}),
    ("{settings: {allow_closed_trading: true}}", {"allow_closed_trading": True}),
    ("{success: true, settings: {allow_closed_trading: true, extra: 1}}", {"allow_closed_trading": True, "extra": 1}),
])
def test_accepts_a_well_formed_settings_response(run, data, expected):
    assert run(f"acceptSettings({data})") == expected


@needs_node
@pytest.mark.parametrize("data", [
    "null", "undefined", "{}", "{settings: null}", "{settings: 'x'}", "{settings: []}", "{settings: {}}",
    "{settings: {allow_closed_trading: 'false'}}", "{settings: {allow_closed_trading: 0}}", "{settings: {allow_closed_trading: null}}", "'x'", "[]",
])
def test_rejects_a_missing_or_odd_settings_response(run, data):
    assert run(f"acceptSettings({data})") is None


def test_toggle_only_applies_an_accepted_response_and_tells_the_user_otherwise():
    body = _func("toggleClosedTrading")
    assert "const accepted = acceptSettings(data);" in body
    assert re.search(r"if \(!accepted\) \{[^}]*showToast\([^)]*'error'\)[^}]*return;", body, re.S)
    assert "userSettings = accepted;" in body and "userSettings = data.settings" not in body


def test_session_load_uses_the_same_check():
    body = _func("loadSession")
    assert "acceptSettings(data) ||" in body and "allow_closed_trading: true" in body


# ── 로그아웃·만료 때 초기화 ──


@needs_node
def test_reset_user_settings_goes_back_to_allowed_and_redraws_the_menu(tmp_path):
    script = (
        "let userSettings = {allow_closed_trading: false}; const calls = [];\n"
        "function updateClosedTradingMenu() { calls.push(userSettings.allow_closed_trading); }\n"
        + _func("resetUserSettings")
        + "\nresetUserSettings();\nconsole.log(JSON.stringify({userSettings, calls}));\n"
    )
    assert _node(script, tmp_path) == {"userSettings": {"allow_closed_trading": True}, "calls": [True]}


def test_logout_and_session_expiry_reset_the_settings():
    assert "resetUserSettings();" in _func("logout")
    assert "resetUserSettings();" in _func("handleUnauthorized")


# ── 한국 시각: Intl 없이 ──


@needs_node
@pytest.mark.parametrize("iso,expected", [
    ("2026-10-29T07:50:00Z", {"min": 1010, "label": "16:50", "weekend": False}),   # 목 16:50
    ("2026-10-28T15:05:00Z", {"min": 5, "label": "00:05", "weekend": False}),      # 한국은 다음 날 00:05
    ("2026-10-31T03:00:00Z", {"min": 720, "label": "12:00", "weekend": True}),     # 토 12:00
    ("2026-10-30T15:30:00Z", {"min": 30, "label": "00:30", "weekend": True}),      # UTC 금 → 한국 토
    ("2026-11-01T15:30:00Z", {"min": 30, "label": "00:30", "weekend": False}),     # UTC 일 → 한국 월
    ("2026-10-29T14:59:00Z", {"min": 1439, "label": "23:59", "weekend": False}),   # 자정 직전
])
def test_kst_clock_without_intl(run, iso, expected):
    # Intl 을 지운 환경(오래된 WebView 를 흉내)에서도 같은 값이어야 한다
    assert run(f"kstClock(new Date('{iso}'))", pre="delete globalThis.Intl;\n") == expected


def test_kst_clock_does_not_use_intl_at_all():
    body = _func("kstClock")
    assert "Intl" not in body and "formatToParts" not in body and "hourCycle" not in body
