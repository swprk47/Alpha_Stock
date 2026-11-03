"""검증 분석 실행: python -m backtest.analysis.run

캐시된 일봉(다시 받지 않는다)과 상장 목록 스냅샷에서 후보-날짜 패널을 만들고, 요소 검정·선택 효과·계좌 곡선·
상관·위험 분포를 계산해 보고서를 쓴다.
"""
import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path

import numpy as np
import pandas as pd

import clock

from backtest.data import CandleCache, Listing, fetch_listing as default_fetch_listing, load_frames
from backtest.metrics import by_market_state
from backtest.pool import select_pool
from backtest.run import DEFAULT_BUCKETS, _executor, _generate_days
from backtest.signals import trading_dates
from backtest.simulate import ENTRY_MODES, simulate_picks

from .bootstrap import BLOCK, DEFAULT_SEED, DRAWS
from .correlation import all_stop_vs_independent, picks_vs_random, terciles_by_corr, unfiltered_pick_trades
from .equity import (TRADING_DAYS, benchmark_returns, cost_drag, excess_ci, information_ratio, matched_benchmark, perf,
                     portfolio_daily)
from .factors import FACTOR_COLUMNS, bin_table, holm, judge, mean_corr_test, rank_corr_test, train_edges, yearly_signs
from .features import compute_features
from .panel import TRAIN_END, build_panel, passes_from_days, pools_from_days
from .risk import PATHS, by_regime, calibration, risk_by_horizon, risk_summary, simulate_paths
from .selection import selection_effect

REGIME_HORIZON = 252


@dataclass
class AnalysisConfig:
    buckets: tuple = DEFAULT_BUCKETS
    workers: int = 1
    out_dir: "Path | None" = None
    cache_dir: Path = Path("backtest/cache")
    max_codes: "int | None" = None
    benchmark_code: str = "069500"           # KODEX 200
    seed: int = DEFAULT_SEED
    refresh_listing: bool = False
    full_pool: bool = True                   # 필터 통과 전체 풀(최대 300)로 확인용 요소 검정도 돌린다
    draws: int = DRAWS
    paths: int = PATHS
    slippage_pct: float = 0.1


def load_listing(cache_dir, fetch, *, refresh: bool = False) -> list:
    """상장 목록 스냅샷. 캐시에 없으면(또는 refresh) 한 번 받아 listing.json 에 저장하고 이후 재사용한다."""
    path = Path(cache_dir) / "listing.json"
    if path.exists() and not refresh:
        try:
            return [Listing(**item) for item in json.loads(path.read_text(encoding="utf-8"))]
        except Exception:
            pass
    items = fetch()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(item) for item in items], ensure_ascii=False), encoding="utf-8")
    return items


def _plain(obj):
    """JSON 으로 쓸 수 있는 기본 형태로 바꾼다(데이터클래스·numpy·Timestamp, NaN 은 None)."""
    if is_dataclass(obj) and not isinstance(obj, type):
        obj = asdict(obj)
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [_plain(v) for v in obj.tolist()]
    if isinstance(obj, np.generic):
        obj = obj.item()
    if isinstance(obj, pd.Timestamp):
        return obj.date().isoformat()
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def _factor_section(panel: pd.DataFrame, columns, *, seed: int, draws: int) -> dict:
    edges = train_edges(panel)
    train, test = panel[panel["period"] == "train"], panel[panel["period"] == "test"]
    res_train = {c: rank_corr_test(train, c, seed=seed, draws=draws) for c in columns}
    res_test = {c: rank_corr_test(test, c, seed=seed, draws=draws) for c in columns}
    mean_train = {c: mean_corr_test(train, c, seed=seed, draws=draws) for c in columns}
    mean_test = {c: mean_corr_test(test, c, seed=seed, draws=draws) for c in columns}
    adjusted = holm({c: res_train[c].p for c in columns})
    out = {}
    for c in columns:
        signs = yearly_signs(panel, c)
        out[c] = {"verdict": judge(res_train[c], res_test[c], signs, adjusted[c], mean_train[c], mean_test[c]),
                  "train": res_train[c], "test": res_test[c], "mean_train": mean_train[c], "mean_test": mean_test[c],
                  "holm_p": adjusted[c], "yearly_signs": signs, "table": bin_table(panel, c, edges[c]),
                  "n_train": int(train[c].notna().sum()), "n_test": int(test[c].notna().sum())}
    return out


def _annual(res) -> dict:
    scale = lambda v: None if v is None else v * TRADING_DAYS
    return {"point": scale(res.point), "lo": scale(res.lo), "hi": scale(res.hi), "p": res.p, "n_days": res.n_days}


def _equity_section(trades, frames, dates, bench, cfg) -> dict:
    daily = portfolio_daily(trades, frames, dates)
    ret, invested = daily["ret"], daily["invested"]
    zeros = pd.Series(0.0, index=ret.index)
    equity = {"strategy": perf(ret, invested), "cash": perf(zeros), "excess": {"vs_cash": _annual(excess_ci(ret, zeros, seed=cfg.seed, draws=cfg.draws))}}
    if bench is not None:
        hold = benchmark_returns(bench, dates)
        matched = matched_benchmark(hold, invested)
        equity["kodex_hold"] = perf(hold, pd.Series(True, index=hold.index))
        equity["kodex_matched"] = perf(matched, invested)
        equity["information_ratio"] = information_ratio(ret, hold)
        equity["excess"]["vs_kodex_hold"] = _annual(excess_ci(ret, hold, seed=cfg.seed, draws=cfg.draws))
        equity["excess"]["vs_kodex_matched"] = _annual(excess_ci(ret, matched, seed=cfg.seed, draws=cfg.draws))
    return equity, daily


def _risk_section(daily, bench, cfg) -> dict:
    ret = daily["ret"]
    horizons = {str(h): v for h, v in risk_by_horizon(ret.to_numpy(), paths=cfg.paths, seed=cfg.seed).items()}
    regime = {}
    if bench is not None:
        for state, values in by_regime(daily, bench).items():
            regime[state] = {"n_days": int(len(values)),
                             "risk": risk_summary(simulate_paths(values, REGIME_HORIZON, paths=cfg.paths, seed=cfg.seed))}
    train, test = ret[ret.index <= TRAIN_END], ret[ret.index > TRAIN_END]
    return {"horizons": horizons, "regime": regime,
            "calibration": calibration(train.to_numpy(), test.to_numpy(), horizon=21, paths=cfg.paths, seed=cfg.seed, draws=cfg.draws)}


def _scenario(bucket, mode, days, frames, features, bench, dates, full_pools, picks_stats, cfg) -> dict:
    panel = build_panel(pools_from_days(days), frames, features, mode, bucket=bucket, slippage_pct=cfg.slippage_pct,
                        passes=passes_from_days(days))
    factors = {"main": _factor_section(panel, FACTOR_COLUMNS, seed=cfg.seed, draws=cfg.draws), "full": None}
    panel_rows = {"main": len(panel), "full": None}
    if full_pools is not None:
        full = build_panel(full_pools, frames, features, mode, bucket=bucket, slippage_pct=cfg.slippage_pct)
        factors["full"] = _factor_section(full, [c for c in FACTOR_COLUMNS if c != "score"], seed=cfg.seed, draws=cfg.draws)
        panel_rows["full"] = len(full)
    trades = simulate_picks(days, frames, mode, bucket=bucket, top_n=3, slippage_pct=cfg.slippage_pct)
    scenario = {"bucket": bucket, "entry_mode": mode, "trades": len(trades), "panel_rows": panel_rows, "factors": factors,
                "selection": selection_effect(panel, seed=cfg.seed, draws=cfg.draws),
                "equity": None, "cost_drag": None, "states": None, "correlation": None, "risk": None}
    if not trades:
        return scenario
    equity, daily = _equity_section(trades, frames, dates, bench, cfg)
    scenario["equity"] = equity
    scenario["cost_drag"] = cost_drag(trades)
    if bench is not None:
        scenario["states"] = {state: {"n": s.n, "expectancy_pct": s.expectancy_pct} for state, s in by_market_state(trades, bench).items()}
    pick_trades = unfiltered_pick_trades(days, frames, mode, bucket=bucket, slippage_pct=cfg.slippage_pct)   # 보유 중 제외 없이 추천 3개 모두
    scenario["correlation"] = {"picks_vs_random": picks_stats,
                               "all_stop": all_stop_vs_independent(pick_trades, seed=cfg.seed, draws=cfg.draws),
                               "terciles": terciles_by_corr(frames, pick_trades)}
    scenario["risk"] = _risk_section(daily, bench, cfg)
    return scenario


def run_analysis(cfg: AnalysisConfig, *, fetch_listing=default_fetch_listing) -> dict:
    listings = load_listing(cfg.cache_dir, fetch_listing, refresh=cfg.refresh_listing)
    if cfg.max_codes:
        listings = listings[:cfg.max_codes]
    codes = [item.code for item in listings]
    wanted = codes + ([cfg.benchmark_code] if cfg.benchmark_code not in codes else [])
    frames, skipped = load_frames(wanted, CandleCache(cfg.cache_dir))          # 일봉은 캐시에서만 읽는다
    bench = frames.get(cfg.benchmark_code)
    dates = trading_dates(frames)
    features = {code: compute_features(frame) for code, frame in frames.items()}
    print(f"frames: {len(frames)}, trading dates after warmup: {len(dates)}")

    scenarios = []
    with _executor(cfg.workers, listings, frames) as pool:
        for bucket in cfg.buckets:
            days = _generate_days(pool, cfg.workers, listings, frames, bucket, dates)
            full_pools = ({d: select_pool(listings, frames, d, bucket, limit=len(listings)) for d in dates}
                          if cfg.full_pool else None)
            picks_stats = picks_vs_random(days, frames, seed=cfg.seed)       # 추천 목록은 진입 방식과 무관하므로 예산 구간마다 한 번만
            for mode in ENTRY_MODES:
                scenarios.append(_scenario(bucket, mode, days, frames, features, bench, dates, full_pools, picks_stats, cfg))
                print(f"scenario bucket={bucket} mode={mode}: {scenarios[-1]['trades']} trades")
    all_dates = sorted({d for f in frames.values() for d in f.index})
    data = {"generated_at": clock.now_str(), "n_listed": len(listings), "n_frames": len(frames), "skipped": skipped,
            "first_date": all_dates[0].date().isoformat() if all_dates else "",
            "last_date": all_dates[-1].date().isoformat() if all_dates else "", "n_dates": len(dates),
            "seed": cfg.seed, "draws": cfg.draws, "paths": cfg.paths, "block": BLOCK, "slippage_pct": cfg.slippage_pct,
            "full_pool": cfg.full_pool}
    return _plain({"data": data, "scenarios": scenarios})


def main(argv=None, *, fetch_listing=default_fetch_listing) -> int:
    from .report import write_analysis_report

    parser = argparse.ArgumentParser(prog="python -m backtest.analysis.run", description="스윙 추천 규칙 검증 분석(요소 검정·계좌 곡선·위험 분포)")
    parser.add_argument("--buckets", type=int, nargs="+", default=list(DEFAULT_BUCKETS), help="예산 구간(후보 가격 상한, 원)")
    parser.add_argument("--workers", type=int, default=1, help="신호 계산 프로세스 수")
    parser.add_argument("--out", type=Path, default=None, help="결과 폴더(기본 backtest/results/<실행일>)")
    parser.add_argument("--cache", type=Path, default=Path("backtest/cache"), help="일봉 캐시 폴더")
    parser.add_argument("--max-codes", type=int, default=None, help="앞 N개 종목만(시험용)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--refresh-listing", action="store_true", help="상장 목록 스냅샷을 다시 받는다")
    parser.add_argument("--no-full-pool", action="store_true", help="확인용 전체 풀 분석을 건너뛴다")
    parser.add_argument("--draws", type=int, default=DRAWS, help="부트스트랩 재추출 횟수")
    parser.add_argument("--paths", type=int, default=PATHS, help="위험 분포 가상 경로 수")
    args = parser.parse_args(argv)
    out_dir = args.out or Path("backtest/results") / clock.today_kst().isoformat()
    cfg = AnalysisConfig(buckets=tuple(args.buckets), workers=args.workers, out_dir=out_dir, cache_dir=args.cache,
                         max_codes=args.max_codes, seed=args.seed, refresh_listing=args.refresh_listing,
                         full_pool=not args.no_full_pool, draws=args.draws, paths=args.paths)
    results = run_analysis(cfg, fetch_listing=fetch_listing)
    write_analysis_report(out_dir, results)
    print(f"report: {out_dir / 'analysis_report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
