"""프론트 수량 입력 로직(index.html 의 qty-logic 구간) 검증. node 가 없으면 건너뛴다.

구간 안의 함수는 DOM 을 쓰지 않는 순수 함수라서 node 로 그대로 실행해 값을 확인한다.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "frontend" / "index.html"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node 가 필요합니다")


def _logic_source():
    s = HTML.read_text(encoding="utf-8")
    m = re.search(r"// <qty-logic>\r?\n(.*?)// </qty-logic>", s, re.S)
    assert m, "index.html 에 qty-logic 구간이 없습니다"
    return m.group(1)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    src = _logic_source()
    d = tmp_path_factory.mktemp("qtyjs")

    def _run(expr):
        f = d / "t.js"
        f.write_text(src + "\nconsole.log(JSON.stringify(" + expr + "));\n", encoding="utf-8")
        out = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    return _run


# ---- buyQtyMax: 정수 단위 최대 ----
def test_max_is_integer_floor_with_fee(run):
    # 100,000 / (30,500 * 1.00015) = 3.278... -> 3
    assert run("buyQtyMax(100000, 30500)") == 3
    # 100,000 / (7,600 * 1.00015) = 13.15... -> 13
    assert run("buyQtyMax(100000, 7600)") == 13


def test_max_is_zero_when_unaffordable_or_invalid(run):
    assert run("buyQtyMax(100000, 150000)") == 0
    assert run("buyQtyMax(0, 7600)") == 0
    assert run("buyQtyMax(100000, 0)") == 0


def test_max_never_exceeds_cash(run):
    # 1주 가격에 수수료를 더해 현금과 같은 경우: 수수료 때문에 살 수 없다
    assert run("buyQtyMax(10000, 10000)") == 0


# ---- normalizeBuyQty ----
def test_integer_input_is_kept(run):
    assert run("normalizeBuyQty('2', false, 13)") == {"qty": 2, "kind": "", "message": ""}


def test_fractional_stock_keeps_decimal_input(run):
    r = run("normalizeBuyQty('1.5', true, 3)")
    assert r["qty"] == 1.5 and r["kind"] == ""


def test_fractional_input_floors_to_four_decimals(run):
    r = run("normalizeBuyQty('1.23456', true, 3)")
    assert r["qty"] == 1.2345


def test_four_decimal_float_noise_is_not_lost(run):
    # 0.0003 * 10000 은 부동소수 오차로 2.9999... 가 되므로 보정이 필요하다
    assert run("normalizeBuyQty('0.0003', true, 3)")["qty"] == 0.0003


def test_integer_only_stock_floors_decimal_with_notice(run):
    r = run("normalizeBuyQty('2.5', false, 13)")
    assert r["qty"] == 2 and r["kind"] == "notice" and "1주 단위" in r["message"]


def test_integer_only_stock_rejects_below_one(run):
    r = run("normalizeBuyQty('0.5', false, 13)")
    assert r["qty"] == 0 and r["kind"] == "error"


def test_over_max_is_clamped_to_integer_max(run):
    r = run("normalizeBuyQty('99', true, 3)")
    assert r["qty"] == 3 and r["kind"] == "notice" and "3주" in r["message"]


def test_decimal_above_integer_max_is_clamped(run):
    # 소수점 종목이어도 최대는 정수 최대다 (3.2 -> 3)
    assert run("normalizeBuyQty('3.2', true, 3)")["qty"] == 3


def test_empty_zero_negative_and_garbage_are_errors(run):
    for raw in ["''", "'0'", "'-1'", "'abc'", "null"]:
        r = run(f"normalizeBuyQty({raw}, true, 3)")
        assert r["qty"] == 0 and r["kind"] == "error", raw


def test_fractional_below_minimum_is_error(run):
    r = run("normalizeBuyQty('0.00001', true, 3)")
    assert r["qty"] == 0 and r["kind"] == "error"


def test_no_cash_is_error_even_with_valid_input(run):
    r = run("normalizeBuyQty('1', true, 0)")
    assert r["qty"] == 0 and r["kind"] == "error" and "현금" in r["message"]


# ---- 소수점 종목의 직접 입력 상한은 "소수로 살 수 있는 최대" (정수 최대보다 큼) ----
def test_fractional_max_is_four_decimal_floor(run):
    # 100,000 / (30,500 * 1.00015) = 3.27810... -> 3.2781
    assert run("buyQtyMaxFractional(100000, 30500)") == 3.2781
    assert run("buyQtyMaxFractional(0, 30500)") == 0
    assert run("buyQtyMaxFractional(100000, 0)") == 0


def test_fractional_input_above_integer_max_is_kept_up_to_fractional_max(run):
    # 정수 최대는 3 이지만 3.2 는 현금으로 살 수 있으므로 그대로 받는다
    r = run("normalizeBuyQty('3.2', true, 3, 3.2781)")
    assert r["qty"] == 3.2 and r["kind"] == ""


def test_fractional_input_is_clamped_to_fractional_max(run):
    r = run("normalizeBuyQty('3.5', true, 3, 3.2781)")
    assert r["qty"] == 3.2781 and r["kind"] == "notice" and "3.2781" in r["message"]


def test_integer_only_stock_ignores_fractional_max(run):
    r = run("normalizeBuyQty('3.5', false, 3, 3.2781)")
    assert r["qty"] == 3


def test_fractional_stock_can_be_bought_in_fraction_even_if_one_share_is_unaffordable(run):
    # 1주 가격이 현금보다 커서 정수 최대는 0 이지만, 소수로는 살 수 있다
    r = run("normalizeBuyQty('0.5', true, 0, 0.6665)")
    assert r["qty"] == 0.5 and r["kind"] == ""


# ---- 입력 도중에는 사용자가 친 글자를 덮어쓰지 않는다 (소수점이 막히던 문제 회귀) ----
def test_field_text_is_left_alone_while_typing(run):
    # null = 입력칸을 건드리지 않음. 2.5 를 치는 도중 "2" 로 덮어쓰면 소수점이 막힌다.
    assert run("buyQtyFieldText(2, true)") is None
    assert run("buyQtyFieldText(0, true)") is None


def test_field_text_is_rewritten_when_committed(run):
    assert run("buyQtyFieldText(2, false)") == "2"
    assert run("buyQtyFieldText(1.5, false)") == "1.5"
    assert run("buyQtyFieldText(0, false)") == ""


def test_typing_decimal_on_integer_only_stock_keeps_message_not_value(run):
    # 1주 단위 종목에 2.5: 적용 수량은 2, 안내는 하되 칸의 글자는 그대로 둔다
    r = run("(() => { const r = normalizeBuyQty('2.5', false, 13); return { r, field: buyQtyFieldText(r.qty, true) }; })()")
    assert r["r"]["qty"] == 2 and r["r"]["kind"] == "notice"
    assert r["field"] is None


# ---- 입력칸 너비: "주" 가 숫자 바로 옆에 붙도록 글자 수에 맞춘다 ----
def test_input_width_follows_text_length(run):
    one = run("buyQtyInputWidthCh('3')")
    six = run("buyQtyInputWidthCh('3.2781')")
    assert six > one
    assert abs((six - one) - 5) < 0.01  # 글자 5개 차이만큼


def test_input_width_has_a_minimum_when_empty(run):
    assert run("buyQtyInputWidthCh('')") >= 1


# ---- stepBuyQty: -/+ 는 항상 1주 단위 ----
def test_step_plus_and_minus_by_one(run):
    assert run("stepBuyQty(2, 1, 13)")["qty"] == 3
    assert run("stepBuyQty(2, -1, 13)")["qty"] == 1


def test_step_snaps_fractional_to_whole_numbers(run):
    assert run("stepBuyQty(2.2781, 1, 13)")["qty"] == 3
    assert run("stepBuyQty(2.2781, -1, 13)")["qty"] == 2


def test_step_minus_does_not_go_to_zero(run):
    assert run("stepBuyQty(1, -1, 13)")["qty"] == 1
    assert run("stepBuyQty(0.5, -1, 13)")["qty"] == 0.5


def test_step_plus_stops_at_max_with_notice(run):
    r = run("stepBuyQty(3, 1, 3)")
    assert r["qty"] == 3 and r["kind"] == "notice"


def test_step_from_zero_goes_to_one(run):
    assert run("stepBuyQty(0, 1, 13)")["qty"] == 1
