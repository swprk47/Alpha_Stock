"""매수 결제 계산(`// <buy-calc>` 구간)이 서버(fees.calc_buy_cost)와 정확히 같은지 검증한다.

화면의 총 결제·남는 현금이 서버가 실제로 받는 금액과 1원이라도 다르면 안 된다.
(기존 모달은 floor(총액×0.00015)라서 100,000원 매수의 수수료를 14원으로 보였고 서버는 15원을 받았다.)
node 가 없으면 건너뛴다.
"""
import json
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "frontend" / "index.html"
sys.path.insert(0, str(ROOT / "backend"))

import fees  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node 가 필요합니다")


def _calc_source():
    s = HTML.read_text(encoding="utf-8")
    m = re.search(r"// <buy-calc>\r?\n(.*?)// </buy-calc>", s, re.S)
    assert m, "index.html 에 buy-calc 구간이 없습니다"
    return m.group(1)


@pytest.fixture(scope="module")
def batch(tmp_path_factory):
    """(함수 이름, 인자 목록 배열)을 한 번의 node 실행으로 계산한다."""
    src = _calc_source()
    d = tmp_path_factory.mktemp("buycalc")

    def _batch(fn, args_list):
        (d / "in.json").write_text(json.dumps(args_list), encoding="utf-8")
        (d / "t.js").write_text(
            src + f"\nconst args = JSON.parse(require('fs').readFileSync({json.dumps(str(d / 'in.json'))}, 'utf8'));\n"
            f"console.log(JSON.stringify(args.map(a => {fn}(...a))));\n", encoding="utf-8")
        out = subprocess.run(["node", str(d / "t.js")], capture_output=True, text=True, encoding="utf-8", timeout=120)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    return _batch


def _cases():
    rnd = random.Random(20261027)
    prices = [1, 99, 1000, 20000, 28333, 29700, 40000, 50000, 88905, 100000, 1234567]
    qtys = [1, 2, 3, 5, 7, 10, 0.5, 0.1234, 2.5, 33.3333, 0.0001]
    cases = [(p, q) for p in prices for q in qtys]
    for _ in range(3000):
        p = rnd.randint(1, 500_000)
        q = rnd.randint(1, 50) if rnd.random() < 0.6 else round(rnd.uniform(0.0001, 20), 4)
        cases.append((p, q))
    return cases


# ---- 총 결제 ----
def test_totals_match_the_server_exactly(batch):
    cases = _cases()
    got = batch("buyTotals", [[p, q, 10**12] for p, q in cases])
    for (p, q), g in zip(cases, got):
        s = fees.calc_buy_cost(p, q)
        assert (g["gross"], g["fee"], g["total"]) == (s["gross"], s["fee"], s["total"]), (p, q, g, s)


def test_the_known_mismatches_of_the_old_formula_are_fixed(batch):
    # 기존 화면식 floor(총액×0.00015)가 서버보다 1원 적게 보이던 값들
    got = batch("buyTotals", [[20000, 1, 10**9], [40000, 1, 10**9], [100000, 1, 10**9]])
    assert [g["fee"] for g in got] == [3, 6, 15]


def test_remaining_cash_and_shortage(batch):
    r = batch("buyTotals", [[10000, 3, 50000], [10000, 3, 30003], [10000, 3, 30004], [10000, 0, 5000]])
    assert (r[0]["total"], r[0]["remaining"], r[0]["short"]) == (30004, 19996, False)  # 수수료 4.5원은 내림 4원
    assert (r[1]["remaining"], r[1]["short"]) == (0, True)    # 총 30,004원 > 현금 30,003원
    assert (r[2]["remaining"], r[2]["short"]) == (0, False)   # 총 30,004원 = 현금 30,004원(정확히 맞음)
    assert (r[3]["total"], r[3]["remaining"], r[3]["short"]) == (0, 5000, False)


# ---- 금액 → 수량, 최대 수량 ----
def _server_total(price, qty):
    return fees.calc_buy_cost(price, qty)["total"]


def _amounts_and_prices():
    rnd = random.Random(7)
    base = [(100000, 100000), (100000, 20000), (100000, 29700), (100000, 88905), (50000, 28333), (40000, 40000),
            (30003, 10000), (30005, 10000), (10000, 1), (1, 99999), (1000, 1)]
    for _ in range(1500):
        base.append((rnd.randint(1000, 3_000_000), rnd.randint(500, 400_000)))
    return base


def test_qty_for_amount_never_exceeds_the_amount_and_is_the_largest(batch):
    pairs = _amounts_and_prices()
    for fractional in (False, True):
        got = batch("qtyForAmount", [[price, amount, fractional] for amount, price in pairs])
        unit = 0.0001 if fractional else 1
        for (amount, price), q in zip(pairs, got):
            assert q >= 0
            if q > 0:
                assert _server_total(price, q) <= amount, (amount, price, fractional, q)
            nxt = round(q + unit, 4)
            assert _server_total(price, nxt) > amount, (amount, price, fractional, q)  # 한 단위 더는 못 산다


def test_max_buy_quantity_is_affordable_for_the_server(batch):
    pairs = _amounts_and_prices()
    for fn, unit in (("buyQtyMax", 1), ("buyQtyMaxFractional", 0.0001)):
        got = batch(fn, [[cash, price] for cash, price in pairs])
        for (cash, price), q in zip(pairs, got):
            if q > 0:
                assert _server_total(price, q) <= cash, (fn, cash, price, q)
            assert _server_total(price, round(q + unit, 4)) > cash, (fn, cash, price, q)
