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
    r = calc_sell_proceeds(10_000, 10)
    assert r["gross"] == 100_000
    assert r["fee"] == 15
    assert r["tax"] == 180
    assert r["net"] == 100_000 - 15 - 180


def test_small_amount_truncates_to_zero_fee():
    assert calc_buy_cost(1_000, 1)["fee"] == 0
    assert calc_sell_proceeds(1_000, 1)["tax"] == 1


def test_estimate_sell_cost():
    assert estimate_sell_cost(100_000) == 195
