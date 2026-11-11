from backtest.forward import registry as r

def test_registry_matches_design_doc():
    assert (r.LOTTERY.name, r.LOTTERY.exclude_pct, r.LOTTERY.reentry_choices, r.LOTTERY.min_days) == ("lottery_avoid", 0.20, (0.20, 0.30), 15)
    assert (r.GATE.name, r.GATE.months) == ("ma_gate", 10)
    assert (r.BENCHMARK, r.BAD_RETURN, r.SLIPPAGE, r.COST_MULTIPLIERS) == ("069500", 0.31, 0.001, (1.0, 1.5, 2.0))
    assert (r.DRAWS, r.SEED, r.BLOCK_MONTHS, r.BLOCK_DAYS) == (20_000, 20261110, 3, 63)
    assert (r.N_CANDIDATES, r.ALPHA, r.MIN_EFFECT_ANNUAL, r.BIG_DROP) == (2, 0.05, 0.01, 0.15)
    assert (r.TRAIN_END, r.REHEARSAL_START) == ("2021-12-31", "2022-01-01")

def test_fingerprint_is_stable_and_changes_with_values(monkeypatch):
    first = r.fingerprint()
    assert first == r.fingerprint() and len(first) == 64
    monkeypatch.setattr(r, "BIG_DROP", 0.20)
    assert r.fingerprint() != first
