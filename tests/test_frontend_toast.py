"""상단 알림(토스트) 표시 시간 검증.

체결 알림("HMM 2.6842주 매수 완료! (체결가: 22,350원)")은 읽고 무엇인지 알아볼 시간이 필요하다.
시간은 종류(성공/정보/오류)와 글자 수로 정하고(순수 함수 toastDuration), 새 알림이 뜨면 이전 알림의 타이머를 지운다.
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
    m = re.search(r"// <toast-logic>\r?\n(.*?)// </toast-logic>", _html(), re.S)
    assert m, "index.html 에 toast-logic 구간이 없습니다"
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


TRADE = "HMM 2.6842주 매수 완료! (체결가: 22,350원)"


@needs_node
def test_trade_result_toast_stays_long_enough_to_read(run):
    # 예전에는 2.5초로 고정이라 체결 알림이 너무 빨리 사라졌다
    assert run(f"toastDuration('success', {json.dumps(TRADE, ensure_ascii=False)})") >= 5000


@needs_node
def test_errors_stay_longer_than_success_and_info(run):
    msg = json.dumps("실시간 시세를 조회할 수 없어 주문을 거부했습니다.", ensure_ascii=False)
    err = run(f"toastDuration('error', {msg})")
    assert err >= 7000
    assert err > run(f"toastDuration('success', {msg})") > run(f"toastDuration('info', {msg})") - 1
    assert run("toastDuration('info', '완료')") >= 4000


@needs_node
def test_longer_messages_stay_longer_but_never_forever(run):
    short = run("toastDuration('success', '완료')")
    long_ = run("toastDuration('success', '가'.repeat(80))")
    huge = run("toastDuration('success', '가'.repeat(5000))")
    assert long_ > short
    assert huge <= 12000


@needs_node
def test_unknown_type_and_empty_message_are_safe(run):
    assert run("toastDuration('weird', '')") >= 4000
    assert run("toastDuration('success', undefined)") >= 5000


def test_show_toast_uses_the_duration_and_cancels_the_previous_timer():
    body = _func("showToast")
    assert "toastDuration(type, message)" in body
    assert "clearTimeout(toastTimer)" in body  # 이전 알림의 타이머가 새 알림을 일찍 숨기지 않는다
    assert "2500" not in body


def test_every_trade_result_uses_the_shared_toast():
    # 체결 알림은 모두 showToast 를 거친다(성공 문구는 서버 응답 message)
    s = _html()
    for name in ("executeSell", "executeInlineBuy"):
        assert "showToast(data.message" in _func(name), name
