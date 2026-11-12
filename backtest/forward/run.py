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


def _dropped(point) -> bool:
    """예행연습 탈락: 점추정이 0보다 큰 유한한 수가 아니면(None·NaN·무한대·0 이하) 뺀다."""
    return not (point is not None and math.isfinite(point) and point > 0)


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


# rehearsal·power 가 train.json 과 같아야 하는 값(등록표 지문·실행 설정·자료)
_SAME_AS_TRAIN = ("registry", "draws", "max_codes", "n_listed", "data_last_date")


def _common(stage, listings, stock_frames, skipped, bench, start, end, args, data_last_date):
    """단계 JSON 의 공통 머리. data_last_date 는 자르기 전 전체 KODEX 200 일봉의 마지막 날."""
    return {"stage": stage, "registry": registry.fingerprint(),
            "window": {"start": _day(start), "end": _day(end)},
            "n_listed": len(listings), "n_frames": len(stock_frames), "skipped": skipped,
            "first_date": _day(bench.index[0]), "last_date": _day(bench.index[-1]),
            "draws": args.draws, "max_codes": args.max_codes, "refresh": bool(args.refresh),
            "data_last_date": _day(data_last_date)}


def _train(frames, bench, calendar, order, start, end, draws):
    evals = {pct: evaluate_lottery(frames, bench, calendar, order, start=start, end=end,
                                   reentry_pct=pct, draws=draws)
             for pct in registry.LOTTERY.reentry_choices}
    # 후보값이 둘이다: 작은 값이 엄격히 나을 때만 고르고, 동점(점추정 없음끼리 포함)이면 큰 값
    low, high = min(registry.LOTTERY.reentry_choices), max(registry.LOTTERY.reentry_choices)
    chosen = low if _point(evals[low].diff[1.0]) > _point(evals[high].diff[1.0]) else high
    return {"chosen_reentry_pct": chosen, "lottery": evals,
            "gate": evaluate_gate(bench, calendar, start=start, end=end, draws=draws)}


def _rehearsal(frames, bench, calendar, order, start, end, draws, reentry):
    lot = evaluate_lottery(frames, bench, calendar, order, start=start, end=end,
                           reentry_pct=reentry, draws=draws)
    gate = evaluate_gate(bench, calendar, start=start, end=end, draws=draws)
    lp, gp = lot.diff[1.0].point, gate.mdd_diff.point
    return {"reentry_pct": reentry, "lottery": lot, "gate": gate,
            "drop": {"lottery_avoid": _dropped(lp), "ma_gate": _dropped(gp)}}


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
    data_last_date = frames[BENCHMARK].index[-1]
    if args.stage == "train":
        cut = truncate(frames, registry.TRAIN_END)
        if BENCHMARK not in cut:
            print(f"KODEX 200({BENCHMARK})에 {registry.TRAIN_END} 이전 일봉이 없다", file=sys.stderr)
            return 2
        # 학습 끝 이후에만 일봉이 있어 잘려 나간 종목도 뺀 종목으로 센다(목록 = 쓴 일봉 + 뺀 종목)
        skipped = skipped + [item.code for item in listings
                             if item.code in frames and item.code not in cut and item.code != BENCHMARK]
        frames = cut
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
    payload = _common(args.stage, listings, stock_frames, skipped, bench, start, end, args, data_last_date)
    if args.stage != "train":
        train = json.loads(train_path.read_text(encoding="utf-8"))
        differ = [k for k in _SAME_AS_TRAIN if train.get(k) != payload[k]]
        if differ:
            print(f"train.json 과 등록표·자료·설정이 다르다: {', '.join(differ)}", file=sys.stderr)
            return 2
    run_args = (stock_frames, bench, calendar, order, start, end, args.draws)
    if args.stage == "train":
        payload.update(_train(*run_args))
    else:
        reentry = train["chosen_reentry_pct"]
        payload.update((_rehearsal if args.stage == "rehearsal" else _power)(*run_args, reentry))
    _write_json(args.out, f"{args.stage}.json", payload)

    payloads = {s: json.loads((args.out / f"{s}.json").read_text(encoding="utf-8"))
                for s in STAGES if (args.out / f"{s}.json").exists()}
    print(f"report: {write_report(args.out, payloads)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
