"""UI 개편 단계 1(docs/superpowers/specs/2026-10-26-ui-redesign-design.md)의 공통 규칙 검증.

화면 구조는 그대로 두고 토큰·글자 크기·아이콘·접근성 규칙만 지켰는지 index.html 문자열로 확인한다.
아이콘 함수는 node 가 있으면 그대로 실행해 본다.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "frontend" / "index.html"
MANIFEST = ROOT / "frontend" / "manifest.json"

# 명세 8항에서 확정한 아이콘 이름(+ 상태 표시용). index.html 의 ICONS 에 모두 있어야 한다.
SPEC_ICONS = {
    "search", "refresh-cw", "bell", "bell-off", "circle-user-round", "chevron-down", "x", "circle-x",
    "minus", "plus", "zap", "sliders-horizontal", "wallet", "triangle-alert", "brain",
    "lightbulb", "info", "circle-check", "circle-alert", "loader-circle", "target", "hourglass", "timer",
}


def _html():
    return HTML.read_text(encoding="utf-8")


def _strip_comments(s):
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s = re.sub(r"(?m)^\s*//.*$", "", s)          # 줄 전체 주석
    s = re.sub(r"(?<=\s)//\s.*$", "", s, flags=re.M)  # 줄 끝 주석 (URL 의 // 는 앞에 공백이 없다)
    return s


def _icons_source():
    m = re.search(r"// <icons>\r?\n(.*?)// </icons>", _html(), re.S)
    assert m, "index.html 에 icons 구간(// <icons> ... // </icons>)이 없습니다"
    return m.group(1)


# ---- 접근성 / 뷰포트 ----
def test_viewport_allows_zoom():
    m = re.search(r'<meta name="viewport" content="([^"]*)"', _html())
    assert m
    content = m.group(1)
    assert "user-scalable=no" not in content
    assert "maximum-scale" not in content


def test_icon_only_buttons_have_aria_label():
    s = _html()
    body = s.split("<body", 1)[1].split("<script>", 1)[0]
    bad = []
    for m in re.finditer(r"<button\b([^>]*)>(.*?)</button>", body, re.S):
        attrs, inner = m.group(1), m.group(2)
        text = re.sub(r"<[^>]+>", "", inner).strip()
        if not text and "aria-label" not in attrs:
            bad.append(attrs.strip()[:80])
    assert not bad, f"글자 없는 버튼에 aria-label 이 없습니다: {bad}"


# ---- 글자 크기 / 색 ----
def test_no_text_smaller_than_13px():
    s = _html()
    found = re.findall(r"text-\[(?:8|9|10|10\.5|11|12)px\]|(?<![\w-])text-xs(?![\w-])", s)
    assert not found, f"13px 보다 작은 글자 클래스가 남아 있습니다: {sorted(set(found))}"


def test_no_dim_text_colors():
    # 명세 3항: 흐린 글자는 #a9aebf 보다 어두운 회색을 쓰지 않는다
    s = _html()
    found = re.findall(r"text-\[#(?:636366|86868b|48484a)\]", s)
    assert not found, f"너무 어두운 글자색이 남아 있습니다: {sorted(set(found))}"


# ---- 아이콘 ----
def test_font_awesome_removed():
    s = _html()
    assert "font-awesome" not in s.lower()
    assert not re.search(r"\bfa-(?:solid|regular|brands)\b", s)


def test_no_emoji_in_ui():
    s = _strip_comments(_html())
    emoji = re.findall("[\U0001F300-\U0001FAFF☀-➿⬀-⯿⏩-⏿️]", s)
    assert not emoji, f"화면 문구에 이모지가 남아 있습니다: {sorted(set(emoji))}"


def test_used_icons_are_defined():
    s = _html()
    src = _icons_source()
    defined = set(re.findall(r"^\s*['\"]?([a-z0-9-]+)['\"]?\s*:\s*['`\"]<", src, re.M))
    used = set(re.findall(r'data-icon="([a-z0-9-]+)"', s)) | set(re.findall(r"icon\('([a-z0-9-]+)'", s))
    missing = used - defined
    assert not missing, f"정의되지 않은 아이콘: {sorted(missing)}"
    assert SPEC_ICONS <= defined, f"명세 아이콘 누락: {sorted(SPEC_ICONS - defined)}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node 가 필요합니다")
def test_icon_function_renders_inline_svg(tmp_path):
    f = tmp_path / "t.js"
    f.write_text(_icons_source() + "\nconsole.log(JSON.stringify(icon('search','x y')));\n", encoding="utf-8")
    out = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert out.returncode == 0, out.stderr
    svg = json.loads(out.stdout)
    assert svg.startswith("<svg")
    assert 'stroke-width="1.75"' in svg
    assert 'aria-hidden="true"' in svg
    assert 'class="ic x y"' in svg
    assert 'viewBox="0 0 24 24"' in svg


# ---- 토큰 / 글라스 ----
def test_glass_tokens_defined():
    s = _html()
    assert ".glass-bar" in s and "rgba(21, 24, 34, 0.72)" in s.replace("rgba(21,24,34,0.72)", "rgba(21, 24, 34, 0.72)")
    assert ".glass-card" in s
    assert ".glass-modal" in s
    assert "prefers-reduced-motion" in s
    assert "prefers-reduced-transparency" in s


# ---- PWA ----
def test_manifest_colors_match_black_theme():
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert m["background_color"].lower() == "#000000"
    assert m["theme_color"].lower() == "#000000"
