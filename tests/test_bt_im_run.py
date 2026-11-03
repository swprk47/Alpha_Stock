import json
import shutil

import pandas as pd
import pytest

import market_data
from backtest.analysis.panel import TRAIN_END
from backtest.data import CandleCache, prepare_frame
from backtest.improve import lock
from backtest.improve.lock import StageError
from backtest.improve.report import write_improve_report
from backtest.improve.run import (ImproveConfig, load_frames_cut, main, run_test, run_train, training_window,
                                  validation_window)
from bt_helpers import listing, make_frame, make_raw, trending_rows

BENCH = "069500"
CODES = ["A", "B", "C", "D"]
DRAWS = 200


def _rows(k, n):
    return [(o * k, h * k, l * k, c * k, 400_000) for o, h, l, c, _ in trending_rows(n)]


def _seed_cache(root, codes=CODES, n=1000, start="2019-01-02"):
    cache = CandleCache(root)
    for i, code in enumerate(codes, 1):
        cache.save(code, make_raw(_rows(i, n), start=start))
    cache.save(BENCH, make_raw(_rows(1, n), start=start))
    return cache


def _cfg(tmp_path, stage, **kw):
    base = dict(stage=stage, out_dir=tmp_path / "out", cache_dir=tmp_path / "cache", draws=DRAWS, confirm_buckets=())
    base.update(kw)
    return ImproveConfig(**base)


def _boom(*a, **k):
    raise AssertionError("검증 도구는 일봉을 받으면 안 된다")


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory):
    """합성 종목으로 train -> test 를 한 번만 돌린다(일봉 다운로드가 일어나면 여기서 실패한다)."""
    root = tmp_path_factory.mktemp("improve")
    _seed_cache(root / "cache")
    fetch = lambda: listing(CODES)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(market_data, "get_stock_daily_candles", _boom)
        cfg = _cfg(root, "train", confirm_buckets=(100_000,))
        train = run_train(cfg, fetch_listing=fetch)
        test = run_test(_cfg(root, "test", confirm_buckets=(100_000,)), fetch_listing=fetch)
    return {"root": root, "train": train, "test": test, "fetch": fetch}


def test_load_frames_cut_truncates_raw_before_preparing(tmp_path):
    cache = _seed_cache(tmp_path / "cache", codes=["A"], n=900)
    frames, skipped = load_frames_cut(["A", BENCH], cache, end=TRAIN_END)
    assert not skipped and frames["A"].index.max() <= TRAIN_END
    raw = cache.load("A")
    expected = prepare_frame(raw[raw["date"] <= TRAIN_END].reset_index(drop=True))
    pd.testing.assert_frame_equal(frames["A"], expected)                     # 자른 원시 일봉에 prepare_frame 을 다시 적용한 것과 같다
    changed = raw.copy()
    changed.loc[changed["date"] > TRAIN_END, ["open", "high", "low", "close"]] *= 3
    CandleCache(tmp_path / "cache2").save("A", changed)
    again, _ = load_frames_cut(["A"], CandleCache(tmp_path / "cache2"), end=TRAIN_END)
    pd.testing.assert_frame_equal(frames["A"], again["A"])                   # 학습 프레임은 TRAIN_END 이후 데이터에 영향받지 않는다


def test_training_and_validation_windows():
    frames = {"A": make_frame(trending_rows(200)), "B": make_frame(trending_rows(200))}
    train = training_window(frames)
    all_dates = list(frames["A"].index)
    assert train.dates == all_dates[60:] and train.signal_start == all_dates[60] and train.signal_end == all_dates[-1]
    dates = list(pd.bdate_range("2021-06-01", periods=400))
    window, test_end = validation_window(dates)
    assert test_end == dates[-21]                                           # 마지막 거래일에서 20거래일 앞
    assert window.signal_start == pd.Timestamp("2022-01-01") and window.signal_end == test_end
    assert window.dates[0] >= pd.Timestamp("2022-01-01") and window.dates[-1] == dates[-1]
    assert all(d >= pd.Timestamp("2022-01-01") for d in window.dates)


def test_train_does_not_depend_on_data_after_train_end(tmp_path):
    codes = ["A", "B", "C"]
    for name in ("one", "two"):
        _seed_cache(tmp_path / name / "cache", codes=codes, n=900)
    raw = CandleCache(tmp_path / "two" / "cache")
    for code in codes + [BENCH]:
        df = raw.load(code)
        df.loc[df["date"] > TRAIN_END, ["open", "high", "low", "close"]] *= 3     # TRAIN_END 이후 가격만 바꾼다(날짜·거래량은 그대로)
        raw.save(code, df)
    fetch = lambda: listing(codes)
    first = run_train(_cfg(tmp_path / "one", "train", out_dir=tmp_path / "one" / "out", cache_dir=tmp_path / "one" / "cache"), fetch_listing=fetch)
    second = run_train(_cfg(tmp_path / "two", "train", out_dir=tmp_path / "two" / "out", cache_dir=tmp_path / "two" / "cache"), fetch_listing=fetch)
    for key in ("chosen", "folded", "n", "finalists", "mde", "train", "test_end"):
        assert first["payload"][key] == second["payload"][key], key          # Review Focus 2: 선별 결과가 동일하다


def test_train_then_test_end_to_end_on_synthetic_data(pipeline):
    out = pipeline["root"] / "out"
    for name in ("selection.json", "test_result.json", "improve_report.md"):
        assert (out / name).exists()
    selection = json.loads((out / "selection.json").read_text(encoding="utf-8"))
    result = json.loads((out / "test_result.json").read_text(encoding="utf-8"))
    assert selection["n"] == len(selection["finalists"])
    assert result["selection_hash"] == lock.selection_hash(out) and result["rerun"] is False
    assert "baseline" in result and "candidates" in result
    assert {c["verdict"]["label"] for c in result["candidates"]} <= {"합격", "유망", "불합격"}


def test_pipeline_never_downloaded_candles(pipeline):
    assert pipeline["train"] and pipeline["test"]                           # 픽스처가 다운로드 차단 아래에서 끝까지 돌았다


def test_test_refuses_without_selection(tmp_path):
    _seed_cache(tmp_path / "cache", n=900)
    with pytest.raises(StageError, match="selection"):
        run_test(_cfg(tmp_path, "test"), fetch_listing=lambda: listing(CODES))


def test_second_test_refused_and_allow_rerun_adds_banner(pipeline, tmp_path):
    copy = tmp_path / "copy"
    shutil.copytree(pipeline["root"], copy)
    cfg = _cfg(copy, "test", out_dir=copy / "out", cache_dir=copy / "cache")
    with pytest.raises(StageError, match="test_result"):
        run_test(cfg, fetch_listing=pipeline["fetch"])
    rerun_cfg = _cfg(copy, "test", out_dir=copy / "out", cache_dir=copy / "cache", allow_rerun=True)
    result = run_test(rerun_cfg, fetch_listing=pipeline["fetch"])
    assert result["rerun"] is True
    assert "검증 기간 재사용" in (copy / "out" / "improve_report.md").read_text(encoding="utf-8")


def test_test_refuses_after_candle_change(pipeline, tmp_path):
    copy = tmp_path / "copy"
    shutil.copytree(pipeline["root"], copy)
    (copy / "out" / "test_result.json").unlink()                            # 두 번째 실행 거부와 따로 보려고 결과 파일을 지운다
    df = CandleCache(copy / "cache").load("A")
    df.loc[df.index[-1], "close"] += 1
    CandleCache(copy / "cache").save("A", df)
    with pytest.raises(StageError, match="candle_hash"):
        run_test(_cfg(copy, "test", out_dir=copy / "out", cache_dir=copy / "cache"), fetch_listing=pipeline["fetch"])


def test_report_first_line_and_limits_come_first(pipeline):
    text = (pipeline["root"] / "out" / "improve_report.md").read_text(encoding="utf-8")
    assert text.splitlines()[0].startswith("이 보고서는 투자 권유가 아니며")
    assert text.index("## 한계") < text.index("## 학습 단계") < text.index("## 검증 단계")


def test_report_never_says_no_effect(pipeline):
    text = (pipeline["root"] / "out" / "improve_report.md").read_text(encoding="utf-8")
    assert "효과 없음" not in text


def _stat(point, p=0.001):
    return {"point": point, "lo": point - 1, "hi": point + 1, "p_one": p, "se": 0.1, "n_days": 100, "draws": 100}


def _train_payload(n):
    row = {"name": "BASE", "direction": "baseline", "pre_exposed": False, "n_trades": 10, "vs_kodex": _stat(0.0), "trade_mean": _stat(-0.3),
           "kodex_excess": 0.0, "avg_hold_days": 4.0, "exposure": 0.5, "avg_slots": 0.3, "selected": False, "fold_reason": None}
    return {"chosen": {"filter": None, "exit": None, "signal": None}, "folded": {"filter": "no_data", "exit": "metric_not_better", "signal": "no_data"},
            "n": n, "finalists": [], "mde": {}, "train": [row], "test_end": "2026-10-05", "config": {}, "data": {}}


def test_report_marks_pre_exposed_candidates(tmp_path):
    verdict = {"label": "유망", "flags": {"alpha_adj": 0.0125, "p_trade_mean": 0.2, "p_vs_kodex": 0.2, "p_vs_baseline": 0.001,
                                          "near_threshold": {"trade_mean": False, "vs_kodex": False, "vs_baseline": False},
                                          "pre_exposed": True, "dividend_sensitive": False}}
    candidate = {"name": "E2", "kind": "candidate", "pre_exposed": True, "summary": {"n_trades": 5, "trade_mean": _stat(0.1, 0.2), "vs_kodex": _stat(0.1, 0.2),
                 "vs_cash": _stat(0.1), "avg_hold_days": 8.0, "exposure": 0.6, "avg_slots": 0.4}, "vs_baseline": _stat(0.2), "verdict": verdict,
                 "yearly": {}, "confirm": {}}
    test = {"baseline": {"n_trades": 5, "trade_mean": _stat(-0.3), "vs_kodex": _stat(-0.1), "vs_cash": _stat(-0.1), "avg_hold_days": 4.0, "exposure": 0.5,
                         "avg_slots": 0.3}, "candidates": [candidate], "n": 1, "alpha_adj": 0.05, "no_candidates": False, "test_end": "2026-10-05"}
    write_improve_report(tmp_path, _train_payload(1), test)
    text = (tmp_path / "improve_report.md").read_text(encoding="utf-8")
    assert "(검증 기간 사전 노출)" in text and "유망" in text


def test_report_handles_no_candidates(tmp_path):
    test = {"baseline": {"n_trades": 5, "trade_mean": _stat(-0.3), "vs_kodex": _stat(-0.1), "vs_cash": _stat(-0.1), "avg_hold_days": 4.0, "exposure": 0.5,
                         "avg_slots": 0.3}, "candidates": [], "n": 0, "alpha_adj": None, "no_candidates": True, "test_end": "2026-10-05"}
    write_improve_report(tmp_path, _train_payload(0), test)
    text = (tmp_path / "improve_report.md").read_text(encoding="utf-8")
    assert "개선 후보 없음" in text and "효과 없음" not in text
    write_improve_report(tmp_path, _train_payload(0), None)                  # 학습 단계만 끝난 보고서도 만들어진다
    assert "검증 단계는 아직 실행하지 않았다" in (tmp_path / "improve_report.md").read_text(encoding="utf-8")


def test_cli_requires_stage_and_passes_options(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr("backtest.improve.run.run_train", lambda cfg, **kw: seen.setdefault("train", cfg))
    monkeypatch.setattr("backtest.improve.run.run_test", lambda cfg, **kw: seen.setdefault("test", cfg))
    with pytest.raises(SystemExit):
        main([])
    assert main(["--stage", "train", "--workers", "3", "--out", str(tmp_path), "--draws", "50"]) == 0
    assert seen["train"].stage == "train" and seen["train"].workers == 3 and seen["train"].draws == 50 and seen["train"].out_dir == tmp_path
    assert main(["--stage", "test", "--allow-rerun"]) == 0
    assert seen["test"].allow_rerun is True
