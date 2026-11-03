import copy
import json

import pytest

from backtest.improve import lock
from backtest.improve.candidates import Combo, by_name, registry_fingerprint
from backtest.improve.lock import (StageError, build_selection_payload, check_test_allowed, check_train_allowed,
                                   code_hashes, data_snapshot, file_hash, finalists_from_json, finalists_to_json,
                                   git_state, read_selection, selection_hash, tree_hash, write_selection,
                                   write_test_result)
from backtest.improve.select import Selection

CONFIG = {"bucket": 200_000, "slippage_pct": 0.1, "entry_mode": "next_open", "k": 2, "block": 20, "draws": 20_000, "seed": 20261103}


def _cache(tmp_path, content="date,open,high,low,close,volume\n2021-01-04,1,1,1,1,1\n"):
    cache = tmp_path / "cache"
    cache.mkdir(exist_ok=True)
    for code in ("A", "B"):
        (cache / f"{code}.csv").write_text(content, encoding="utf-8")
    (cache / "listing.json").write_text("[]", encoding="utf-8")
    return cache


def _current(tmp_path, **override):
    cache = _cache(tmp_path)
    current = {"code": {"backtest/improve/slots.py": "h1", "backend/strategy.py": "h2"},
               "data": data_snapshot(cache, ["A", "B"], n_frames=2, first_date="2014-08-07", last_date="2026-11-02", test_end="2026-10-05"),
               "config": dict(CONFIG), "registry": registry_fingerprint()}
    current.update(override)
    return current


def _selection():
    return Selection(chosen={"filter": None, "exit": "E2", "signal": None}, folded={"filter": "no_data", "signal": "no_data"},
                     combo=None, finalists=[by_name("E2")], n=1)


def _write(tmp_path, current):
    payload = build_selection_payload(_selection(), {"E2": {"trade_mean": 0.5}}, current["config"], current["data"], current["code"],
                                      current["registry"], {"rows": []}, "2026-10-05")
    out = tmp_path / "out"
    write_selection(out, payload)
    return out


def test_hashes_change_with_content(tmp_path):
    path = tmp_path / "f.py"
    path.write_text("a = 1\n", encoding="utf-8")
    before, tree_before = file_hash(path), tree_hash([path])
    path.write_text("a = 2\n", encoding="utf-8")
    assert file_hash(path) != before and tree_hash([path]) != tree_before


def test_code_hashes_cover_the_pipeline_files():
    hashes = code_hashes(".")
    for name in ("backtest/improve/slots.py", "backtest/simulate.py", "backtest/analysis/bootstrap.py", "backend/strategy.py",
                 "backend/fees.py", "backend/orders.py", "backend/config.py"):
        assert name in hashes


def test_test_refused_without_selection(tmp_path):
    with pytest.raises(StageError, match="selection"):
        check_test_allowed(tmp_path / "out", _current(tmp_path), allow_rerun=False)


def test_second_test_refused_without_allow_rerun(tmp_path):
    current = _current(tmp_path)
    out = _write(tmp_path, current)
    assert check_test_allowed(out, current, allow_rerun=False) == []
    write_test_result(out, {"verdicts": []}, selection_hash=selection_hash(out), rerun=False, mismatches=[])
    with pytest.raises(StageError, match="test_result"):
        check_test_allowed(out, current, allow_rerun=False)
    assert check_test_allowed(out, current, allow_rerun=True) == []


def test_train_refused_after_test_result_exists(tmp_path):
    current = _current(tmp_path)
    out = _write(tmp_path, current)
    check_train_allowed(out, overwrite=True)                                   # 아직 test 결과가 없으면 통과
    write_test_result(out, {}, selection_hash=selection_hash(out), rerun=False, mismatches=[])
    with pytest.raises(StageError, match="train"):
        check_train_allowed(out, overwrite=True)


def test_retrain_refused_when_a_selection_exists_unless_overwrite_is_requested(tmp_path):
    out = _write(tmp_path, _current(tmp_path))
    with pytest.raises(StageError, match="selection"):
        check_train_allowed(out)                                               # 사전 등록한 selection.json 을 조용히 덮어쓰지 않는다
    check_train_allowed(out, overwrite=True)
    check_train_allowed(tmp_path / "empty")                                    # 선별 결과가 아직 없으면 그냥 통과


def test_test_refused_when_code_hash_differs(tmp_path):
    current = _current(tmp_path)
    out = _write(tmp_path, current)
    changed = copy.deepcopy(current)
    changed["code"]["backtest/improve/slots.py"] = "different"
    with pytest.raises(StageError, match="slots.py"):
        check_test_allowed(out, changed, allow_rerun=False)


def test_test_refused_when_candle_content_hash_differs(tmp_path):
    current = _current(tmp_path)
    out = _write(tmp_path, current)
    (tmp_path / "cache" / "A.csv").write_text("date,open,high,low,close,volume\n2021-01-04,1,1,1,2,1\n", encoding="utf-8")   # 값 하나만 바뀜
    changed = dict(current)                                                    # _current() 를 다시 부르면 CSV 를 원래대로 덮어쓰므로 쓰지 않는다
    changed["data"] = data_snapshot(tmp_path / "cache", ["A", "B"], n_frames=2, first_date="2014-08-07", last_date="2026-11-02", test_end="2026-10-05")
    with pytest.raises(StageError, match="candle_hash"):
        check_test_allowed(out, changed, allow_rerun=False)


def test_test_refused_when_config_or_registry_differs(tmp_path):
    current = _current(tmp_path)
    out = _write(tmp_path, current)
    with pytest.raises(StageError, match="config"):
        check_test_allowed(out, _current(tmp_path, config={**CONFIG, "k": 3}), allow_rerun=False)
    with pytest.raises(StageError, match="registry"):
        check_test_allowed(out, _current(tmp_path, registry="other"), allow_rerun=False)


def test_allow_rerun_passes_but_records_mismatches_and_rerun_flag(tmp_path):
    current = _current(tmp_path)
    out = _write(tmp_path, current)
    changed = _current(tmp_path, config={**CONFIG, "draws": 5000})
    mismatches = check_test_allowed(out, changed, allow_rerun=True)
    assert mismatches and any("config" in m for m in mismatches)
    write_test_result(out, {"verdicts": []}, selection_hash=selection_hash(out), rerun=True, mismatches=mismatches)
    saved = json.loads((out / "test_result.json").read_text(encoding="utf-8"))
    assert saved["rerun"] is True and saved["mismatches"] == mismatches


def test_test_result_records_selection_hash(tmp_path):
    out = _write(tmp_path, _current(tmp_path))
    write_test_result(out, {"verdicts": []}, selection_hash=selection_hash(out), rerun=False, mismatches=[])
    saved = json.loads((out / "test_result.json").read_text(encoding="utf-8"))
    assert saved["selection_hash"] == selection_hash(out) == file_hash(out / "selection.json")
    assert read_selection(out)["n"] == 1 and read_selection(out)["config"]["k"] == 2


def test_data_snapshot_is_order_independent(tmp_path):
    cache = _cache(tmp_path)
    a = data_snapshot(cache, ["A", "B"], n_frames=2, first_date="x", last_date="y", test_end="z")
    b = data_snapshot(cache, ["B", "A"], n_frames=2, first_date="x", last_date="y", test_end="z")
    assert a == b and a["listing_hash"] and a["candle_hash"]


def test_git_state_returns_none_values_outside_a_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))      # 상위 폴더(예: 홈 폴더)에 저장소가 있어도 찾지 않게 한다
    assert git_state() == {"commit": None, "dirty": None}


def test_finalists_round_trip_through_json():
    singles = [by_name("E2"), by_name("S1")]
    combo = Combo(signal=by_name("S1"), filter=None, exit=by_name("E2"))
    restored = finalists_from_json(json.loads(json.dumps(finalists_to_json(singles + [combo]))))
    assert [c.name for c in restored] == ["E2", "S1", "COMBO(S1+E2)"]
    assert isinstance(restored[2], Combo) and restored[2].exit.name == "E2"
