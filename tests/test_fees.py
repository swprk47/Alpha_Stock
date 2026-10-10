import importlib

import config
from fees import calc_buy_cost, calc_sell_proceeds, estimate_sell_cost


def test_buy_cost_matches_legacy_formula():
    # 기존: total=int(price*qty), fee=int(total*0.00015)
    r = calc_buy_cost(10_000, 5)
    assert r == {"gross": 50_000, "fee": 7, "total": 50_007}


def test_buy_cost_fractional():
    r = calc_buy_cost(71_300, 0.3)
    assert r["gross"] == 21_390
    assert r["fee"] == 3
    assert r["total"] == 21_393


def test_sell_proceeds():
    # 2026년 매도 세율 0.20% (코스피: 거래세 0.05% + 농특세 0.15%, 코스닥: 거래세 0.20%)
    r = calc_sell_proceeds(10_000, 10)
    assert r["gross"] == 100_000
    assert r["fee"] == 15
    assert r["tax"] == 200
    assert r["net"] == 100_000 - 15 - 200


def test_small_amount_tax_is_truncated_to_won():
    assert calc_buy_cost(1_000, 1)["fee"] == 0
    assert calc_sell_proceeds(1_000, 1)["tax"] == 2


def test_estimate_sell_cost():
    # 수수료 0.015% + 세금 0.20% = 0.215%
    assert estimate_sell_cost(100_000) == 215


def test_default_sell_tax_rate_is_the_2026_rate(monkeypatch):
    """환경변수가 없을 때의 기본 세율이 2026년 값(0.20%)인지 확인한다.
    (증권거래세법 시행령 제5조: 코스피 1만분의 5 + 농특세 0.15%, 코스닥 1만분의 20 → 둘 다 합계 0.20%)"""
    monkeypatch.delenv("SELL_TAX_RATE", raising=False)
    try:
        importlib.reload(config)
        assert config.SELL_TAX_RATE == 0.0020
    finally:
        monkeypatch.undo()
        importlib.reload(config)
