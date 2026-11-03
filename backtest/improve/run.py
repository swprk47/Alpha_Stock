"""개선 후보 검증 실행: python -m backtest.improve.run --stage {train,test}

train: 원시 일봉을 학습 끝(TRAIN_END)에서 자른 뒤 다시 준비한 프레임으로 기준선과 후보 8개를 평가하고 선별 결과를 잠근다.
test: 잠긴 후보만 검증 기간에서 딱 한 번 평가한다(코드·데이터·설정이 train 때와 다르면 거부). 일봉은 캐시에서만 읽는다.
"""
import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

import clock

from backtest.analysis.features import compute_features
from backtest.analysis.panel import TRAIN_END
from backtest.analysis.run import _plain, load_listing
from backtest.data import CandleCache, fetch_listing as default_fetch_listing, prepare_frame
from backtest.run import _executor, _generate_days
from backtest.signals import trading_dates

from . import lock
from .candidates import BASELINE, REGISTRY, Combo, exit_kwargs, registry_fingerprint
from .evaluate import Window, evaluate, vs_baseline
from .judge import judge_candidate
from .ranking import candidate_days
from .report import write_improve_report
from .select import decide_combo, select_train, train_mde
from .slots import K
from .stats import ANNUAL, BLOCK, DRAWS, SEED, log_growth_excess, significant

VALIDATION_START = pd.Timestamp("2022-01-01")
HOLD_TAIL = 20                    # 검증 신호 끝 = 합집합 달력의 마지막 날에서 20거래일 앞(최대 보유일)
DIVIDEND_YIELD = 0.02             # KODEX 200 분배금 민감도용 임의 가정(연 2%p, 확인 못 한 값)
DEFAULT_CONFIRM = (100_000, 500_000)


@dataclass
class ImproveConfig:
    stage: str
    out_dir: Path = lock.OUT_DIR
    cache_dir: Path = Path("backtest/cache")
    workers: int = 1
    max_codes: "int | None" = None
    benchmark_code: str = "069500"        # KODEX 200
    bucket: int = 200_000
    k: int = K
    slippage_pct: float = 0.1
    seed: int = SEED
    draws: int = DRAWS
    allow_rerun: bool = False
    confirm_buckets: tuple = DEFAULT_CONFIRM


def load_frames_cut(codes, cache, end=None, *, min_rows: int = 60):
    """캐시의 **원시** 일봉을 end(포함) 이하로 자른 뒤 prepare_frame 을 적용한다(end 가 None 이면 자르지 않는다).
    분할 감지(vol_break/pre_split)가 이후 행을 보므로, 자르기 전에 준비하면 학습 프레임에 검증 기간 정보가 샌다."""
    frames, skipped = {}, []
    for code in codes:
        raw = cache.load(code)
        if raw is not None and end is not None:
            raw = raw[raw["date"] <= pd.Timestamp(end)].reset_index(drop=True)
        if raw is None or len(raw) < min_rows:
            skipped.append(code)
        else:
            frames[code] = prepare_frame(raw)
    return frames, skipped


def calendar_info(cache, codes, *, min_rows: int = 60):
    """일봉 CSV 의 날짜 열만 모은 전체 종목 합집합 거래일 달력과 프레임이 될 종목 수(가격은 쓰지 않는다)."""
    dates, n_frames = set(), 0
    for code in codes:
        raw = cache.load(code)
        if raw is None or len(raw) < min_rows:
            continue
        n_frames += 1
        dates.update(pd.to_datetime(raw["date"]).tolist())
    return sorted(dates), n_frames


def training_window(frames_cut: dict) -> Window:
    """절단된 프레임 합집합 거래일의 warmup(60일) 뒤 첫 날 ~ 마지막 날. 신호와 계좌 창이 같다."""
    dates = trading_dates(frames_cut)
    if not dates:
        raise ValueError("학습 기간에 거래일이 없다")
    return Window(dates[0], dates[-1], dates)


def validation_window(all_dates: list):
    """신호 2022-01-01 ~ test_end(합집합 달력의 마지막 날에서 20거래일 앞), 계좌 창은 2022-01-01 이후 첫 거래일 ~ 마지막 거래일.
    창이 마지막 신호일보다 뒤까지 이어져야 모든 거래의 청산일 비용이 창 안에 들어온다."""
    if len(all_dates) <= HOLD_TAIL:
        raise ValueError("거래일이 너무 적다")
    test_end = all_dates[-(HOLD_TAIL + 1)]
    account = [d for d in all_dates if d >= VALIDATION_START]
    return Window(VALIDATION_START, test_end, account), test_end


# ── 공통 ──


def _config_dict(cfg: ImproveConfig) -> dict:
    return {"bucket": cfg.bucket, "slippage_pct": cfg.slippage_pct, "entry_mode": "next_open", "k": cfg.k, "block": BLOCK,
            "draws": cfg.draws, "seed": cfg.seed}


def _listing_and_codes(cfg, fetch_listing):
    listings = load_listing(cfg.cache_dir, fetch_listing)
    if cfg.max_codes:
        listings = listings[:cfg.max_codes]
    codes = [item.code for item in listings]
    return listings, codes + ([cfg.benchmark_code] if cfg.benchmark_code not in codes else [])


def _snapshot(cfg, cache, wanted):
    all_dates, n_frames = calendar_info(cache, wanted)
    window, test_end = validation_window(all_dates)
    snap = lock.data_snapshot(cfg.cache_dir, wanted, n_frames=n_frames, first_date=all_dates[0].date().isoformat(),
                              last_date=all_dates[-1].date().isoformat(), test_end=test_end.date().isoformat())
    return all_dates, window, test_end, snap


def _base_days(cfg, listings, frames, dates, bucket):
    with _executor(cfg.workers, listings, frames) as pool:
        return _generate_days(pool, cfg.workers, listings, frames, bucket, dates)


def _evaluate_spec(spec, base_days, frames, features, bench, window, cfg, bucket=None):
    bucket = bucket or cfg.bucket
    days = candidate_days(spec, base_days, frames, features, bench, bucket)
    kwargs = spec.exit_kwargs() if isinstance(spec, Combo) else exit_kwargs(spec)
    return evaluate(days, frames, bench, window, exit_kwargs=kwargs, bucket=bucket, k=cfg.k, slippage_pct=cfg.slippage_pct,
                    seed=cfg.seed, draws=cfg.draws)


def _summary(ev) -> dict:
    return {"n_trades": ev.n_trades, "trade_mean": ev.trade_mean, "vs_kodex": ev.vs_kodex, "vs_cash": ev.vs_cash,
            "kodex_excess": ev.trade_kodex_excess_mean, "avg_hold_days": ev.avg_hold_days, "exposure": ev.exposure,
            "avg_slots": ev.avg_slots}


def _train_row(spec, ev, *, selected: bool, fold_reason) -> dict:
    return {"name": spec.name, "direction": "combo" if isinstance(spec, Combo) else spec.direction, "pre_exposed": spec.pre_exposed,
            **_summary(ev), "selected": selected, "fold_reason": fold_reason}


# ── 학습 단계 ──


def run_train(cfg: ImproveConfig, *, fetch_listing=default_fetch_listing) -> dict:
    lock.check_train_allowed(cfg.out_dir)
    listings, wanted = _listing_and_codes(cfg, fetch_listing)
    cache = CandleCache(cfg.cache_dir)
    all_dates, test_window, test_end, snapshot = _snapshot(cfg, cache, wanted)
    frames, skipped = load_frames_cut(wanted, cache, end=TRAIN_END)               # 원시 일봉 절단 -> prepare_frame
    bench = frames[cfg.benchmark_code]
    features = {code: compute_features(frame) for code, frame in frames.items()}
    window = training_window(frames)
    print(f"train frames: {len(frames)}, dates: {len(window.dates)}")
    base_days = _base_days(cfg, listings, frames, window.dates, cfg.bucket)

    baseline = _evaluate_spec(BASELINE, base_days, frames, features, bench, window, cfg)
    evals = {c.name: _evaluate_spec(c, base_days, frames, features, bench, window, cfg) for c in REGISTRY}
    selection = select_train(evals, baseline)
    combo_eval = None
    if selection.combo is not None:
        combo_eval = _evaluate_spec(selection.combo, base_days, frames, features, bench, window, cfg)
    selection = decide_combo(selection, combo_eval, evals)
    mde = train_mde(evals, baseline, selection.finalists, train_days=len(window.dates), test_days=len(test_window.dates),
                    combo_eval=combo_eval)

    chosen = set(name for name in selection.chosen.values() if name)
    rows = [_train_row(BASELINE, baseline, selected=False, fold_reason=None)]
    for c in REGISTRY:
        folded = selection.folded.get(c.direction)
        rows.append(_train_row(c, evals[c.name], selected=c.name in chosen, fold_reason=folded if c.name not in chosen else None))
    if selection.combo is not None and combo_eval is not None:
        included = any(isinstance(f, Combo) for f in selection.finalists)
        rows.append(_train_row(selection.combo, combo_eval, selected=included, fold_reason=None if included else "combo_not_better"))
    payload = _plain(lock.build_selection_payload(selection, mde, _config_dict(cfg), snapshot, lock.code_hashes(), registry_fingerprint(),
                                                  rows, test_end.date().isoformat()))
    payload["skipped"] = skipped
    lock.write_selection(cfg.out_dir, payload)
    write_improve_report(cfg.out_dir, payload, None)
    print(f"selection: n={selection.n} finalists={[f.name for f in selection.finalists]}")
    return {"payload": payload, "selection": selection}


# ── 검증 단계 ──


def _yearly(ev) -> dict:
    by_year = {}
    for t in ev.trades:
        by_year.setdefault(t.signal_date.year, []).append(t.net_return_pct)
    out = {str(y): {"trade_mean": sum(v) / len(v)} for y, v in by_year.items()}
    for year, grp in ev.ret.groupby(ev.ret.index.year):
        out.setdefault(str(year), {})["account"] = float((1 + grp).prod() - 1) * 100
    return out


def run_test(cfg: ImproveConfig, *, fetch_listing=default_fetch_listing) -> dict:
    listings, wanted = _listing_and_codes(cfg, fetch_listing)
    cache = CandleCache(cfg.cache_dir)
    all_dates, window, test_end, snapshot = _snapshot(cfg, cache, wanted)
    current = {"code": lock.code_hashes(), "data": snapshot, "config": _config_dict(cfg), "registry": registry_fingerprint()}
    mismatches = lock.check_test_allowed(cfg.out_dir, current, allow_rerun=cfg.allow_rerun)     # 거부할 때는 여기서 끝난다
    rerun = bool(cfg.allow_rerun and (lock.test_result_exists(cfg.out_dir) or mismatches))
    selection = lock.read_selection(cfg.out_dir)
    finalists, n = lock.finalists_from_json(selection["finalists"]), selection["n"]

    frames, _ = load_frames_cut(wanted, cache)
    bench = frames[cfg.benchmark_code]
    features = {code: compute_features(frame) for code, frame in frames.items()}
    signal_dates = [d for d in all_dates if window.signal_start <= d <= window.signal_end]
    print(f"test frames: {len(frames)}, signal dates: {len(signal_dates)}, N={n}")
    base_days = _base_days(cfg, listings, frames, signal_dates, cfg.bucket)
    baseline = _evaluate_spec(BASELINE, base_days, frames, features, bench, window, cfg)

    confirm_days = {b: _base_days(cfg, listings, frames, signal_dates, b) for b in cfg.confirm_buckets} if finalists else {}
    confirm_base = {b: _evaluate_spec(BASELINE, d, frames, features, bench, window, cfg, bucket=b).trade_mean.point
                    for b, d in confirm_days.items()}
    candidates = []
    for spec in finalists:
        ev = _evaluate_spec(spec, base_days, frames, features, bench, window, cfg)
        vs_b = vs_baseline(ev.ret, baseline.ret, seed=cfg.seed, draws=cfg.draws)
        verdict = judge_candidate(ev.trade_mean, ev.vs_kodex, vs_b, ev.vs_cash, n, pre_exposed=spec.pre_exposed)
        if verdict.label == "합격":                                        # 분배금 민감도: 연 2%p 를 뺐을 때 ②가 유지되는가
            adjusted = log_growth_excess(ev.ret.to_numpy(), (ev.kodex_ret + DIVIDEND_YIELD / ANNUAL).to_numpy(), seed=cfg.seed, draws=cfg.draws)
            if not significant(adjusted, 0.05 / n):
                verdict = judge_candidate(ev.trade_mean, ev.vs_kodex, vs_b, ev.vs_cash, n, pre_exposed=spec.pre_exposed, dividend_sensitive=True)
        confirm = {str(b): _evaluate_spec(spec, d, frames, features, bench, window, cfg, bucket=b).trade_mean.point for b, d in confirm_days.items()}
        candidates.append({"name": spec.name, "kind": "combo" if isinstance(spec, Combo) else "candidate", "pre_exposed": spec.pre_exposed,
                           "summary": _summary(ev), "vs_baseline": vs_b, "verdict": {"label": verdict.label, "flags": verdict.flags},
                           "yearly": _yearly(ev), "confirm": confirm})
    payload = _plain({"baseline": _summary(baseline), "baseline_yearly": _yearly(baseline), "baseline_confirm": confirm_base,
                      "candidates": candidates, "n": n, "alpha_adj": (0.05 / n) if n else None, "no_candidates": n == 0,
                      "test_end": test_end.date().isoformat()})
    sel_hash = lock.selection_hash(cfg.out_dir)
    lock.write_test_result(cfg.out_dir, payload, selection_hash=sel_hash, rerun=rerun, mismatches=mismatches)
    banner = ("검증 기간 재사용 또는 코드·데이터 변경(결과 신뢰도 하락): " + (", ".join(mismatches) or "재실행")) if rerun else None
    write_improve_report(cfg.out_dir, selection, payload, banner=banner)
    return dict(payload, rerun=rerun, mismatches=mismatches, selection_hash=sel_hash)


def main(argv=None, *, fetch_listing=default_fetch_listing) -> int:
    parser = argparse.ArgumentParser(prog="python -m backtest.improve.run", description="개선 후보 검증(학습 선별 -> 검증 한 번)")
    parser.add_argument("--stage", required=True, choices=("train", "test"))
    parser.add_argument("--workers", type=int, default=1, help="기준선 신호 계산 프로세스 수")
    parser.add_argument("--out", type=Path, default=lock.OUT_DIR, help="결과 폴더(기본 backtest/results/improve)")
    parser.add_argument("--cache", type=Path, default=Path("backtest/cache"), help="일봉 캐시 폴더")
    parser.add_argument("--max-codes", type=int, default=None, help="앞 N개 종목만(시험용)")
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--draws", type=int, default=DRAWS, help="부트스트랩 재추출 횟수(시험용으로만 줄인다)")
    parser.add_argument("--allow-rerun", action="store_true", help="검증 기간을 다시 쓴다(결과에 재사용으로 기록된다)")
    parser.add_argument("--confirm-buckets", type=int, nargs="*", default=list(DEFAULT_CONFIRM), help="확인용 예산 구간(판정에 쓰지 않음)")
    args = parser.parse_args(argv)
    cfg = ImproveConfig(stage=args.stage, out_dir=args.out, cache_dir=args.cache, workers=args.workers, max_codes=args.max_codes,
                        seed=args.seed, draws=args.draws, allow_rerun=args.allow_rerun, confirm_buckets=tuple(args.confirm_buckets))
    (run_train if args.stage == "train" else run_test)(cfg, fetch_listing=fetch_listing)
    print(f"report: {Path(cfg.out_dir) / 'improve_report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
