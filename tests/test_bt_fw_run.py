"""단계 명령(run) 테스트: 합성 종목 12개 + KODEX 200, 가짜 fetch 주입(네트워크 없음)."""
import json
import shutil

import numpy as np
import pandas as pd
import pytest

from backtest.data import CandleCache
from backtest.forward import registry
from backtest.forward.run import main
from tests.bt_fw_helpers import (
    build_candle_cache, fake_listing, no_fetch, stock_codes, synthetic_raw,
)

CODES = stock_codes(12)
FAST = ["--draws", "300", "--delay", "0"]


@pytest.fixture(scope="module")
def base_cache(tmp_path_factory):
    root = tmp_path_factory.mktemp("fw_base") / "cache"
    build_candle_cache(root, CODES)
    return root


@pytest.fixture
def cache(base_cache, tmp_path):
    dest = tmp_path / "cache"
    shutil.copytree(base_cache, dest)
    return dest


def _run(stage, cache, out, *extra, listing=None):
    return main(["--stage", stage, "--cache", str(cache), "--out", str(out), *FAST, *extra],
                fetch_listing=listing or fake_listing(CODES), fetch_candles=no_fetch)


def _load(out, name):
    return json.loads((out / name).read_text(encoding="utf-8"))


def _alter_after(cache_root, cutoff="2022-01-01"):
    """cutoff 이후 행의 가격만 고정 시드 난수로 바꾼다. 이전 행은 글자 그대로 둔다(CSV 왕복 오차 방지)."""
    rng = np.random.default_rng(7)
    for code in CODES + [registry.BENCHMARK]:
        path = cache_root / f"{code}.csv"
        lines = path.read_text(encoding="utf-8").splitlines()
        out = [lines[0]]
        for line in lines[1:]:
            parts = line.split(",")
            if parts[0] >= cutoff:
                factor = rng.uniform(0.3, 3.0)
                parts[1:5] = [repr(float(v) * factor) for v in parts[1:5]]
            out.append(",".join(parts))
        path.write_text("\n".join(out) + "\n", encoding="utf-8")


def test_train_writes_selection_and_never_reads_after_train_end(cache, tmp_path):
    out1 = tmp_path / "o1"
    assert _run("train", cache, out1) == 0
    t1 = _load(out1, "train.json")
    assert t1["stage"] == "train"
    assert t1["chosen_reentry_pct"] in (0.2, 0.3)
    assert t1["window"]["end"] == "2021-12-31"
    assert t1["last_date"] <= "2021-12-31"
    assert set(t1["lottery"]) == {"0.2", "0.3"}
    assert t1["registry"] == registry.fingerprint()
    assert t1["lottery"]["0.2"]["diff"]["1.0"]["n"] > 0
    chosen = str(t1["chosen_reentry_pct"])
    other = "0.2" if chosen == "0.3" else "0.3"
    p_c = t1["lottery"][chosen]["diff"]["1.0"]["point"]
    p_o = t1["lottery"][other]["diff"]["1.0"]["point"]
    assert p_c >= p_o

    _alter_after(cache)
    out2 = tmp_path / "o2"
    assert _run("train", cache, out2) == 0
    assert _load(out2, "train.json") == t1


def test_rehearsal_and_power_require_train(cache, tmp_path, capsys):
    for stage in ("rehearsal", "power"):
        assert _run(stage, cache, tmp_path / "o") == 2
        assert "먼저 --stage train" in capsys.readouterr().err
    assert not (tmp_path / "o" / "report.md").exists()


def test_rehearsal_uses_trained_buffer_and_sets_drop_flags(cache, tmp_path):
    out = tmp_path / "o"
    _run("train", cache, out)
    train = _load(out, "train.json")
    assert _run("rehearsal", cache, out) == 0
    r = _load(out, "rehearsal.json")
    assert r["stage"] == "rehearsal"
    assert r["reentry_pct"] == train["chosen_reentry_pct"]
    assert r["window"]["start"] == "2022-01-01"
    assert r["window"]["end"] > "2024-11-01"
    lot_point, gate_point = r["lottery"]["diff"]["1.0"]["point"], r["gate"]["mdd_diff"]["point"]
    assert r["drop"]["lottery_avoid"] == (lot_point is None or lot_point <= 0)
    assert r["drop"]["ma_gate"] == (gate_point is None or gate_point <= 0)
    assert set(r["lottery"]["diff"]) == {"1.0", "1.5", "2.0"}
    assert isinstance(r["drop"]["lottery_avoid"], bool)


def test_power_writes_required_months_table(cache, tmp_path):
    out = tmp_path / "o"
    _run("train", cache, out)
    assert _run("power", cache, out) == 0
    p = _load(out, "power.json")
    assert p["stage"] == "power"
    table = p["lottery_avoid"]["required_months"]
    assert set(table) == {"0.01", "0.02", "0.03", "0.05"}
    assert table["0.01"] >= table["0.02"] >= table["0.03"] >= table["0.05"] > 0
    assert p["lottery_avoid"]["sd_monthly"] > 0 and p["lottery_avoid"]["n_months"] > 100
    gate = p["ma_gate"]
    assert gate["big_drop_episodes"] >= 0 and gate["episodes_per_year"] >= 0
    assert gate["n_days"] > 2000 and gate["switches"] >= 0
    assert p["window"]["end"] > "2024-11-01"


def test_missing_or_short_candles_are_skipped_and_counted(tmp_path):
    root = tmp_path / "cache"
    build_candle_cache(root, CODES[:10])
    out = tmp_path / "o"
    assert main(["--stage", "train", "--cache", str(root), "--out", str(out), *FAST],
                fetch_listing=fake_listing(CODES), fetch_candles=no_fetch) == 0
    t = _load(out, "train.json")
    assert t["skipped"] == CODES[10:]
    assert t["n_listed"] == 12 and t["n_frames"] == 10


def test_max_codes_limits_listing(cache, tmp_path):
    out = tmp_path / "o"
    assert _run("train", cache, out, "--max-codes", "8") == 0
    t = _load(out, "train.json")
    assert t["n_listed"] == 8 and t["n_frames"] == 8


def test_missing_benchmark_fails_clearly(tmp_path, capsys):
    root = tmp_path / "cache"
    build_candle_cache(root, CODES, with_bench=False)
    rc = main(["--stage", "train", "--cache", str(root), "--out", str(tmp_path / "o"), *FAST],
              fetch_listing=fake_listing(CODES), fetch_candles=no_fetch)
    assert rc == 2
    assert "KODEX 200" in capsys.readouterr().err


def test_no_month_boundary_fails_clearly(cache, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("backtest.forward.run.periods", lambda calendar: [])
    assert _run("train", cache, tmp_path / "o") == 2
    assert "월말이 두 번 이상 있어야 한다" in capsys.readouterr().err


def test_train_without_candles_before_train_end_fails_clearly(tmp_path, capsys):
    root = tmp_path / "cache"
    cc = CandleCache(root)
    for code in CODES[:3] + [registry.BENCHMARK]:
        cc.save(code, synthetic_raw(5, start="2023-01-02", end="2023-12-29"))
    rc = main(["--stage", "train", "--cache", str(root), "--out", str(tmp_path / "o"), *FAST],
              fetch_listing=fake_listing(CODES[:3]), fetch_candles=no_fetch)
    assert rc == 2
    assert "KODEX 200" in capsys.readouterr().err


def test_downloads_missing_candles_with_injected_fetch(tmp_path):
    root = tmp_path / "cache"
    build_candle_cache(root, CODES[:11])
    spare = synthetic_raw(77)
    calls = []

    def fetch(code, count):
        calls.append(code)
        return spare

    out = tmp_path / "o"
    assert main(["--stage", "train", "--cache", str(root), "--out", str(out), *FAST],
                fetch_listing=fake_listing(CODES), fetch_candles=fetch) == 0
    assert calls == [CODES[11]]
    assert _load(out, "train.json")["skipped"] == []


def test_full_sequence_writes_report(cache, tmp_path, capsys):
    out = tmp_path / "o"
    for stage in ("train", "rehearsal", "power"):
        assert _run(stage, cache, out) == 0
    text = (out / "report.md").read_text(encoding="utf-8")
    assert text.index("## 한계") < text.index("## 학습") < text.index("## 예행연습") < text.index("## 필요 기간")
    assert str(out / "report.md") in capsys.readouterr().out
    json.loads((out / "power.json").read_text(encoding="utf-8"))
