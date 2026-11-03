import pytest

from bt_helpers import make_raw, trending_rows
from backtest.data import CandleCache, Listing
from backtest.run import RunConfig, main, run


def candle_rows(n=130):
    return [(o, h, l, c, 300_000) for o, h, l, c, _ in trending_rows(n)]      # 거래대금 30억 → 후보 풀 조건 통과


def fake_listing():
    return [Listing(c, c, "KOSPI", i) for i, c in enumerate(["A", "B", "C", "D", "BAD"])]


def fake_candles(code, count):
    return None if code == "BAD" else make_raw(candle_rows())


def cfg(tmp_path, **kw):
    base = dict(buckets=(100_000,), out_dir=tmp_path / "out", cache_dir=tmp_path / "cache", delay_s=0)
    base.update(kw)
    return RunConfig(**base)


def test_end_to_end_with_fake_data_writes_all_files(tmp_path):
    res = run(cfg(tmp_path), fetch_listing=fake_listing, fetch_candles=fake_candles)
    assert {(s.bucket, s.entry_mode) for s in res.scenarios} == {(100_000, "close"), (100_000, "next_open")}
    assert all(s.summary.n > 0 and len(s.sensitivity) == 29 for s in res.scenarios)
    code = main(["--out", str(tmp_path / "out2"), "--cache", str(tmp_path / "cache"), "--buckets", "100000"],
                fetch_listing=fake_listing, fetch_candles=fake_candles)
    assert code == 0
    for name in ("report.md", "trades.csv", "metrics.json"):
        assert (tmp_path / "out2" / name).exists()


def test_parallel_and_sequential_runs_give_identical_trades(tmp_path):
    seq = run(cfg(tmp_path, workers=1), fetch_listing=fake_listing, fetch_candles=fake_candles)
    par = run(cfg(tmp_path, workers=2), fetch_listing=fake_listing, fetch_candles=fake_candles)
    assert [t for s in seq.scenarios for t in s.trades] == [t for s in par.scenarios for t in s.trades]
    assert [s.summary for s in seq.scenarios] == [s.summary for s in par.scenarios]


def test_failed_download_is_reported_not_fatal(tmp_path):
    res = run(cfg(tmp_path), fetch_listing=fake_listing, fetch_candles=fake_candles)
    assert res.data_quality.failed == ["BAD"] and res.data_quality.n_listed == 5 and res.data_quality.n_with_data == 4
    main(["--out", str(tmp_path / "out"), "--cache", str(tmp_path / "cache"), "--buckets", "100000"],
         fetch_listing=fake_listing, fetch_candles=fake_candles)
    assert "BAD" in (tmp_path / "out" / "report.md").read_text(encoding="utf-8")


def test_second_run_uses_the_cache_and_does_not_fetch_again(tmp_path):
    calls = []

    def counting(code, count):
        calls.append(code)
        return fake_candles(code, count)

    run(cfg(tmp_path), fetch_listing=fake_listing, fetch_candles=counting)
    assert sorted(calls) == ["069500", "A", "B", "BAD", "C", "D"]
    calls.clear()
    (tmp_path / "cache" / "A.csv").write_text("garbage")                  # 손상된 캐시 한 개
    run(cfg(tmp_path), fetch_listing=fake_listing, fetch_candles=counting)
    assert sorted(calls) == ["A", "BAD"]                                   # 손상 파일과 이전에 실패한 종목만 다시 받는다


def test_scenarios_cover_every_bucket_and_mode(tmp_path):
    res = run(cfg(tmp_path, buckets=(100_000, 200_000)), fetch_listing=fake_listing, fetch_candles=fake_candles)
    assert {(s.bucket, s.entry_mode) for s in res.scenarios} == {
        (100_000, "close"), (100_000, "next_open"), (200_000, "close"), (200_000, "next_open")}


def test_help_exits_cleanly():
    with pytest.raises(SystemExit) as e:
        main(["--help"])
    assert e.value.code == 0
