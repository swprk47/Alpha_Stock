"""단계 명령: python -m backtest.forward.run --stage {train,rehearsal,power}

train 은 TRAIN_END 이후 일봉을 자른 뒤에만 계산한다. 결과는 --out 아래 JSON과 report.md 로 쓴다.
"""
import argparse
import json
import math
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.analysis.run import load_listing
from backtest.data import CandleCache, download_candles, fetch_listing as default_fetch_listing
from backtest.forward import registry
from backtest.forward.evaluate import evaluate_gate, evaluate_lottery
from backtest.forward.frames import load_all, truncate
from backtest.forward.months import periods
from backtest.forward.power import effective_sd, episodes_per_year, required_table
from backtest.forward.registry import BENCHMARK
from backtest.forward.report import write_report
from backtest.run import default_fetch_candles

STAGES = ("train", "rehearsal", "power")


def _plain(obj):
    """JSON 으로 쓸 수 있는 형태로 바꾼다(데이터클래스·numpy·Timestamp, NaN 은 None)."""
    if is_dataclass(obj) and not isinstance(obj, type):
        obj = asdict(obj)
    if isinstance(obj, pd.Series):
        return {_plain(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, dict):
        return {str(_plain(k)): _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    if isinstance(obj, pd.Timestamp):
        return obj.date().isoformat()
    if isinstance(obj, np.generic):
        obj = obj.item()
    if isinstance(obj, float) and math.isnan(obj):
        return None
    return obj


def _write_json(out, name, payload):
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text(json.dumps(_plain(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _point(stat):
    return stat.point if stat.point is not None else -math.inf


def _day(ts):
    return pd.Timestamp(ts).date().isoformat()


def _load_data(args, fetch_listing, fetch_candles):
    """(listings, frames, skipped) 또는 KODEX 200 일봉이 없으면 None."""
    cache = CandleCache(args.cache)
    listings = load_listing(args.cache, fetch_listing, refresh=args.refresh)
    if args.max_codes:
        listings = listings[:args.max_codes]
    codes = [item.code for item in listings]
    wanted = codes + ([BENCHMARK] if BENCHMARK not in codes else [])
    download_candles(wanted, cache, fetch_candles, count=3000, delay_s=args.delay, refresh=args.refresh)
    frames, skipped = load_all(wanted, cache)
    if BENCHMARK not in frames:
        return None
    return listings, frames, [c for c in skipped if c != BENCHMARK]


def _common(stage, listings, stock_frames, skipped, bench, start, end):
    return {"stage": stage, "registry": registry.fingerprint(),
            "window": {"start": _day(start), "end": _day(end)},
            "n_listed": len(listings), "n_frames": len(stock_frames), "skipped": skipped,
            "first_date": _day(bench.index[0]), "last_date": _day(bench.index[-1])}


def _train(frames, bench, calendar, order, start, end, draws):
    evals = {pct: evaluate_lottery(frames, bench, calendar, order, start=start, end=end,
                                   reentry_pct=pct, draws=draws)
             for pct in registry.LOTTERY.reentry_choices}
    low, high = registry.LOTTERY.reentry_choices
    chosen = low if _point(evals[low].diff[1.0]) > _point(evals[high].diff[1.0]) else 0.30
    return {"chosen_reentry_pct": chosen, "lottery": evals,
            "gate": evaluate_gate(bench, calendar, start=start, end=end, draws=draws)}


def _rehearsal(frames, bench, calendar, order, start, end, draws, reentry):
    lot = evaluate_lottery(frames, bench, calendar, order, start=start, end=end,
                           reentry_pct=reentry, draws=draws)
    gate = evaluate_gate(bench, calendar, start=start, end=end, draws=draws)
    lp, gp = lot.diff[1.0].point, gate.mdd_diff.point
    return {"reentry_pct": reentry, "lottery": lot, "gate": gate,
            "drop": {"lottery_avoid": lp is None or lp <= 0, "ma_gate": gp is None or gp <= 0}}


def _power(frames, bench, calendar, order, start, end, draws, reentry):
    lot = evaluate_lottery(frames, bench, calendar, order, start=start, end=end,
                           reentry_pct=reentry, draws=draws)
    gate = evaluate_gate(bench, calendar, start=start, end=end, draws=draws)
    stat = lot.diff[1.0]
    empty = stat.point is None
    n_days = int(((calendar >= pd.Timestamp(start)) & (calendar <= pd.Timestamp(end))).sum())
    table = None if empty else {f"{k:.2f}": v for k, v in required_table(stat).items()}
    return {"lottery_avoid": {"reentry_pct": reentry, "required_months": table,
                              "sd_monthly": None if empty else effective_sd(stat), "n_months": lot.n_months},
            "ma_gate": {"big_drop_episodes": len(gate.episodes), "switches": gate.switches, "n_days": n_days,
                        "episodes_per_year": episodes_per_year(gate.episodes, n_days)}}


def main(argv=None, *, fetch_listing=default_fetch_listing, fetch_candles=default_fetch_candles) -> int:
    parser = argparse.ArgumentParser(prog="python -m backtest.forward.run",
                                     description="순방향 검증 1단계: 학습·예행연습·필요 기간")
    parser.add_argument("--stage", choices=STAGES, required=True)
    parser.add_argument("--cache", type=Path, default=Path("backtest/cache"), help="일봉 캐시 폴더")
    parser.add_argument("--out", type=Path, default=Path("backtest/results/forward"), help="결과 폴더")
    parser.add_argument("--refresh", action="store_true", help="캐시를 무시하고 다시 받는다")
    parser.add_argument("--max-codes", type=int, default=None, help="앞 N개 종목만(시험용)")
    parser.add_argument("--draws", type=int, default=registry.DRAWS, help="재추출 횟수")
    parser.add_argument("--delay", type=float, default=0.2, help="종목 사이 대기(초)")
    args = parser.parse_args(argv)

    train_path = args.out / "train.json"
    if args.stage != "train" and not train_path.exists():
        print("먼저 --stage train 을 실행해야 한다", file=sys.stderr)
        return 2
    loaded = _load_data(args, fetch_listing, fetch_candles)
    if loaded is None:
        print("KODEX 200(069500) 일봉이 없다", file=sys.stderr)
        return 2
    listings, frames, skipped = loaded
    if args.stage == "train":
        frames = truncate(frames, registry.TRAIN_END)
        if BENCHMARK not in frames:
            print("KODEX 200(069500) 일봉이 없다", file=sys.stderr)
            return 2
    bench = frames[BENCHMARK]
    calendar = bench.index
    order = [item.code for item in listings if item.code in frames and item.code != BENCHMARK]
    stock_frames = {c: frames[c] for c in order}
    all_periods = periods(calendar)
    if not all_periods:
        print("월말이 두 번 이상 있어야 한다", file=sys.stderr)
        return 2

    if args.stage == "train":
        start, end = all_periods[0].trade_day, pd.Timestamp(registry.TRAIN_END)
    elif args.stage == "rehearsal":
        start, end = pd.Timestamp(registry.REHEARSAL_START), all_periods[-1].signal_day
    else:
        start, end = all_periods[0].trade_day, all_periods[-1].signal_day
    payload = _common(args.stage, listings, stock_frames, skipped, bench, start, end)
    run_args = (stock_frames, bench, calendar, order, start, end, args.draws)
    if args.stage == "train":
        payload.update(_train(*run_args))
    else:
        reentry = json.loads(train_path.read_text(encoding="utf-8"))["chosen_reentry_pct"]
        payload.update((_rehearsal if args.stage == "rehearsal" else _power)(*run_args, reentry))
    _write_json(args.out, f"{args.stage}.json", payload)

    payloads = {s: json.loads((args.out / f"{s}.json").read_text(encoding="utf-8"))
                for s in STAGES if (args.out / f"{s}.json").exists()}
    print(f"report: {write_report(args.out, payloads)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
