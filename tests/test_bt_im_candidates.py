import pytest

from backtest.improve import candidates
from backtest.improve.candidates import (BASELINE, DIRECTIONS, REGISTRY, Combo, by_name, exit_kwargs,
                                         registry_fingerprint)


def test_registry_matches_the_design_document():
    assert [c.name for c in REGISTRY] == ["F1", "E1", "E2", "E3", "S1", "S2", "S3", "S4"]
    assert [c.direction for c in REGISTRY] == ["filter", "exit", "exit", "exit", "signal", "signal", "signal", "signal"]
    assert {c.name for c in REGISTRY if c.pre_exposed} == {"F1", "E1", "E2", "E3", "S4"}
    assert DIRECTIONS == ("filter", "exit", "signal")
    assert BASELINE.name == "BASE" and BASELINE.direction == "baseline" and not BASELINE.pre_exposed


def test_exit_kwargs_values():
    assert exit_kwargs(by_name("E1")) == {"stop_ratio": 0.95}
    assert exit_kwargs(by_name("E2")) == {"stop_ratio": 0.95, "target_ratio": 1.10, "hold_days": 10}
    assert exit_kwargs(by_name("E3")) == {"stop_ratio": 0.93, "target_ratio": 1.15, "hold_days": 20}
    for name in ("F1", "S1", "S2", "S3", "S4"):
        assert exit_kwargs(by_name(name)) == {}
    assert exit_kwargs(BASELINE) == {}


def test_by_name_unknown_raises():
    with pytest.raises(KeyError):
        by_name("E9")


def test_combo_name_and_exposure():
    combo = Combo(signal=by_name("S1"), filter=by_name("F1"), exit=by_name("E2"))
    assert combo.name == "COMBO(S1+F1+E2)"
    assert combo.pre_exposed is True
    assert combo.exit_kwargs() == {"stop_ratio": 0.95, "target_ratio": 1.10, "hold_days": 10}
    only_s1 = Combo(signal=by_name("S1"), filter=None, exit=None)
    assert only_s1.name == "COMBO(S1)" and only_s1.pre_exposed is False and only_s1.exit_kwargs() == {}


def test_fingerprint_changes_when_a_parameter_changes(monkeypatch):
    before = registry_fingerprint()
    assert before == registry_fingerprint()
    changed = {name: dict(values) for name, values in candidates._EXIT_TABLE.items()}
    changed["E1"]["stop_ratio"] = 0.94
    monkeypatch.setattr(candidates, "_EXIT_TABLE", changed)
    assert registry_fingerprint() != before
    assert exit_kwargs(by_name("E1")) == {"stop_ratio": 0.94}          # 같은 표를 읽는다
