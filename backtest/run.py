"""파이프라인 연결과 CLI: python -m backtest.run"""
import argparse
import sys
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import clock
import market_data

from .data import CandleCache, download_candles, fetch_listing as default_fetch_listing, load_frames
from .metrics import (benchmark_excess, by_market_state, by_score_band, by_year, control_runs, evaluate_checklist,
                      sensitivity, summarize, summarize_control)
from .report import DataQuality, RunResults, ScenarioResult, write_report
from .signals import generate_signals, trading_dates
from .simulate import ENTRY_MODES, simulate_picks

DEFAULT_BUCKETS = (100_000, 200_000, 500_000)


def default_fetch_candles(code, count):
    return market_data.get_stock_daily_candles(code, count=count)


@dataclass
class RunConfig:
    buckets: tuple = DEFAULT_BUCKETS
    workers: int = 1
    out_dir: "Path | None" = None            # None 이면 backtest/results/<실행일>
    cache_dir: Path = Path("backtest/cache")
    refresh: bool = False
    max_codes: "int | None" = None
    benchmark_code: str = "069500"           # KODEX 200
    candle_count: int = 3000
    delay_s: float = 0.2                     # 종목 사이 대기(네이버 비공식 API에 부담을 주지 않으려는 것)


# ── 병렬 신호 생성 ──

_WORKER_STATE = {}


def _init_worker(listings, frames):
    _WORKER_STATE["listings"], _WORKER_STATE["frames"] = listings, frames


def _generate_chunk(args):
    bucket, dates = args
    return generate_signals(_WORKER_STATE["listings"], _WORKER_STATE["frames"], bucket, dates)


@contextmanager
def _executor(workers, listings, frames):
    if workers <= 1:
        yield None
        return
    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker, initargs=(listings, frames)) as pool:
        yield pool


def _chunks(items, n):
    size = -(-len(items) // n)                       # 올림 나눗셈
    return [items[i:i + size] for i in range(0, len(items), size)]


def _generate_days(pool, workers, listings, frames, bucket, dates):
    if pool is None or len(dates) < 2 * workers:
        return generate_signals(listings, frames, bucket, dates)
    parts = list(pool.map(_generate_chunk, [(bucket, chunk) for chunk in _chunks(dates, workers)]))
    return [day for part in parts for day in part]               # map 은 순서를 지킨다


# ── 시나리오 ──


def _scenario(bucket, mode, days, frames, bench) -> ScenarioResult:
    top3 = simulate_picks(days, frames, mode, bucket=bucket, top_n=3)
    every = simulate_picks(days, frames, mode, bucket=bucket, top_n=None)
    summary = summarize(top3)
    yearly = by_year(top3)
    control = summarize_control(control_runs(days, frames, mode, bucket=bucket))
    sens = sensitivity(days, frames, mode, bucket=bucket)
    slip03 = next((r.expectancy_pct for r in sens if (r.target_pct, r.stop_pct, r.hold_days, r.slippage_pct) == (6.5, 3.0, 5, 0.3)), None)
    empty = summarize([])
    return ScenarioResult(
        bucket=bucket, entry_mode=mode, summary=summary, all_passes_summary=summarize(every), yearly=yearly,
        bands=by_score_band(top3), states=by_market_state(top3, bench) if bench is not None else {"up": empty, "down": empty},
        excess_pct=benchmark_excess(top3, bench) if bench is not None else None, control=control, sensitivity=sens,
        checklist=evaluate_checklist(summary=summary, control_expectancy=control.mean_expectancy_pct, yearly=yearly,
                                     slip03_expectancy=slip03),
        trades=top3)


def run(cfg: RunConfig, *, fetch_listing=default_fetch_listing, fetch_candles=default_fetch_candles) -> RunResults:
    listings = fetch_listing()
    if cfg.max_codes:
        listings = listings[:cfg.max_codes]
    codes = [item.code for item in listings]
    wanted = codes + ([cfg.benchmark_code] if cfg.benchmark_code not in codes else [])

    cache = CandleCache(cfg.cache_dir)
    failed = download_candles(wanted, cache, fetch_candles, count=cfg.candle_count, delay_s=cfg.delay_s, refresh=cfg.refresh)
    frames, skipped = load_frames(wanted, cache)
    bench = frames.get(cfg.benchmark_code)
    dates = trading_dates(frames)
    print(f"frames: {len(frames)}, trading dates after warmup: {len(dates)}")

    scenarios = []
    with _executor(cfg.workers, listings, frames) as pool:
        for bucket in cfg.buckets:
            days = _generate_days(pool, cfg.workers, listings, frames, bucket, dates)
            print(f"bucket {bucket}: signals generated for {len(days)} days")
            scenarios += [_scenario(bucket, mode, days, frames, bench) for mode in ENTRY_MODES]

    all_dates = sorted({d for f in frames.values() for d in f.index})
    quality = DataQuality(
        n_listed=len(listings), n_with_data=sum(1 for c in codes if c in frames), failed=failed, skipped_short=skipped,
        excluded_days={c: int(f["vol_break"].sum()) for c, f in frames.items() if f["vol_break"].any()},
        first_date=all_dates[0].date().isoformat() if all_dates else "", last_date=all_dates[-1].date().isoformat() if all_dates else "")
    return RunResults(clock.now_str(), scenarios, quality)


def main(argv=None, *, fetch_listing=default_fetch_listing, fetch_candles=default_fetch_candles) -> int:
    parser = argparse.ArgumentParser(prog="python -m backtest.run", description="스윙 추천 규칙 백테스트(앱의 analyze_stock_for_swing 을 그대로 호출)")
    parser.add_argument("--buckets", type=int, nargs="+", default=list(DEFAULT_BUCKETS), help="예산 구간(후보 가격 상한, 원)")
    parser.add_argument("--workers", type=int, default=1, help="신호 계산 프로세스 수")
    parser.add_argument("--out", type=Path, default=None, help="결과 폴더(기본 backtest/results/<실행일>)")
    parser.add_argument("--cache", type=Path, default=Path("backtest/cache"), help="일봉 캐시 폴더")
    parser.add_argument("--refresh", action="store_true", help="캐시를 무시하고 일봉을 다시 받는다")
    parser.add_argument("--max-codes", type=int, default=None, help="앞 N개 종목만(시험용)")
    args = parser.parse_args(argv)
    out_dir = args.out or Path("backtest/results") / clock.today_kst().isoformat()
    cfg = RunConfig(buckets=tuple(args.buckets), workers=args.workers, out_dir=out_dir, cache_dir=args.cache,
                    refresh=args.refresh, max_codes=args.max_codes)
    results = run(cfg, fetch_listing=fetch_listing, fetch_candles=fetch_candles)
    write_report(out_dir, results)
    print(f"report: {out_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
