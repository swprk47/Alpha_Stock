from types import SimpleNamespace

import pytest

from backtest.improve.candidates import by_name
from backtest.improve.select import decide_combo, select_train, train_mde
from backtest.improve.stats import Stat, mde


def _stat(point, se=0.1):
    return Stat(point, None if point is None else point - 1, None if point is None else point + 1, 0.5, se, 100, 100)


def _ev(vk, tm, *, se_tm=0.1, se_vk=0.05, kodex_excess=0.0):
    """선별·MDE 가 읽는 값만 가진 가짜 평가."""
    return SimpleNamespace(vs_kodex=_stat(vk, se_vk), trade_mean=_stat(tm, se_tm), trade_kodex_excess_mean=kodex_excess)


BASE = _ev(0.0, -0.30)


def _good(vk, tm=-0.10):
    return _ev(vk, tm)


def test_picks_best_per_direction_by_vs_kodex():
    evals = {"E1": _good(0.1), "E2": _good(0.3), "E3": _good(0.2)}
    sel = select_train(evals, BASE)
    assert sel.chosen["exit"] == "E2"
    assert sel.chosen["filter"] is None and sel.chosen["signal"] is None


def test_folds_direction_when_not_better_than_baseline():
    evals = {"S1": _good(-0.1), "S2": _good(0.0), "S3": _good(-0.5), "S4": _good(-0.2)}
    sel = select_train(evals, BASE)
    assert sel.chosen["signal"] is None and "signal" in sel.folded       # 기준선과 같거나 낮으면 접는다(같아도 접힘)


def test_folds_when_absolute_trade_mean_does_not_improve():
    evals = {"S1": _ev(0.5, -0.40), "S4": _ev(0.4, -0.30)}               # 지표는 좋지만 절대 기대값은 기준선 이하
    sel = select_train(evals, BASE)
    assert sel.chosen["signal"] is None
    assert "absolute" in sel.folded["signal"]


def test_market_timing_candidate_is_selected_not_erased():
    f1 = _ev(0.4, -0.10, kodex_excess=BASE.trade_kodex_excess_mean)      # 거래당 KODEX 대비 초과는 기준선과 같지만 계좌 지표는 크게 좋다
    sel = select_train({"F1": f1}, BASE)
    assert sel.chosen["filter"] == "F1"


def test_ties_follow_registry_order():
    sel = select_train({"E2": _good(0.3), "E1": _good(0.3)}, BASE)
    assert sel.chosen["exit"] == "E1"


def test_combo_only_when_two_or_more_directions():
    one = select_train({"E2": _good(0.3)}, BASE)
    assert one.combo is None
    two = select_train({"E2": _good(0.3), "S1": _good(0.2)}, BASE)
    assert two.combo is not None and two.combo.name == "COMBO(S1+E2)"


def test_combo_included_only_if_it_beats_every_single():
    evals = {"E2": _good(0.3, -0.10), "S1": _good(0.2, -0.15)}
    sel = select_train(evals, BASE)
    better = decide_combo(sel, _good(0.5, -0.05), evals)
    assert [getattr(c, "name") for c in better.finalists] == ["E2", "S1", "COMBO(S1+E2)"] or \
        {c.name for c in better.finalists} == {"E2", "S1", "COMBO(S1+E2)"}
    assert better.n == 3
    worse_metric = decide_combo(sel, _good(0.25, -0.05), evals)           # 지표가 단일 최댓값(0.3)보다 낮다
    worse_absolute = decide_combo(sel, _good(0.5, -0.20), evals)          # 절대 평균이 단일 최댓값(-0.10)보다 낮다
    assert worse_metric.n == 2 and worse_absolute.n == 2
    assert all(c.name != "COMBO(S1+E2)" for c in worse_metric.finalists + worse_absolute.finalists)


def test_n_counts_finalists_without_duplicates():
    evals = {"F1": _good(0.2), "E2": _good(0.3), "S1": _good(0.25)}
    sel = decide_combo(select_train(evals, BASE), _good(0.6, -0.02), evals)
    assert sel.n == 4 and len({c.name for c in sel.finalists}) == 4
    single = select_train({"E2": _good(0.3)}, BASE)
    assert single.n == 1 and [c.name for c in single.finalists] == ["E2"]
    assert decide_combo(single, None, {"E2": _good(0.3)}).n == 1          # 방향이 하나뿐이면 조합을 따로 만들지 않는다


def test_no_survivors_gives_empty_finalists_and_n_zero():
    sel = select_train({"F1": _good(-1.0), "E1": _good(-1.0), "S1": _good(-1.0)}, BASE)
    assert sel.finalists == [] and sel.n == 0 and all(v is None for v in sel.chosen.values())
    assert decide_combo(sel, None, {}).n == 0
    empty = select_train({}, _ev(None, None))
    assert empty.n == 0                                                    # 평가가 하나도 없어도 예외 없이 끝난다


def test_mde_uses_each_candidates_own_se():
    evals = {"E1": _ev(0.3, -0.1, se_tm=0.1), "E2": _ev(0.3, -0.1, se_tm=0.3)}
    sel = select_train(evals, BASE)
    out = train_mde(evals, BASE, [by_name("E1"), by_name("E2")], train_days=100, test_days=100)
    assert out["E2"]["trade_mean"] == pytest.approx(3 * out["E1"]["trade_mean"])
    assert sel.chosen["exit"] == "E1"


def test_mde_reports_zero_basis_and_baseline_relative_need():
    evals = {"E1": _ev(0.3, -0.1, se_tm=0.2, se_vk=0.5)}
    out = train_mde(evals, BASE, [by_name("E1")], train_days=200, test_days=100)["E1"]
    expected = mde(0.2, 200, 100, 1)
    assert out["trade_mean"] == pytest.approx(expected)
    assert out["trade_vs_baseline_needed"] == pytest.approx(expected - (-0.30))    # 0 기준 MDE 에서 기준선(-0.30)을 뺀 만큼 개선돼야 한다
    assert out["vs_kodex"] == pytest.approx(mde(0.5, 200, 100, 1))
