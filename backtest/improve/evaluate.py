"""후보 하나를 한 창(학습 또는 검증)에서 평가한다: 슬롯 제한 계좌의 거래당 순손익(①), KODEX 200 대비(②)·현금 대비(④) 로그성장 초과.

기준선 대비(③)는 후보 계좌와 기준선 계좌의 일간 수익률이 모두 있어야 하므로 `vs_baseline` 으로 따로 계산한다.
"""
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from backtest.analysis.equity import benchmark_returns, matched_benchmark, perf

from .slots import K, run_slots, slot_account, utilisation
from .stats import DRAWS, SEED, Stat, log_growth_excess, ratio_stat


@dataclass(frozen=True)
class Window:
    """signal_start..signal_end(포함)에 신호가 난 거래만 쓰고, 계좌 일간 수익률은 dates(오름차순, 모든 거래일) 전체에서 센다.
    계좌 창이 마지막 신호일보다 뒤까지 이어져야 마지막 거래의 청산일 비용이 창 안에 들어온다."""
    signal_start: pd.Timestamp
    signal_end: pd.Timestamp
    dates: list


@dataclass
class Evaluation:
    trades: list
    ret: pd.Series                       # 계좌 일간 수익률(인덱스 = window.dates)
    open: pd.Series                      # 그날 열린 포지션 수
    n_trades: int
    trade_mean: Stat                     # ① 거래당 순손익(%) 평균(신호일별 합계의 비율 통계)
    vs_kodex: Stat                       # ② KODEX 200 보유 대비 계좌 로그성장 초과(연환산)
    vs_cash: Stat                        # ④ 현금 대비 계좌 로그성장 초과(연환산)
    kodex_ret: pd.Series
    avg_hold_days: "float | None"
    exposure: float
    avg_slots: float
    trade_kodex_excess_mean: "float | None"   # 참고: 거래당 순손익(%) - 같은 구간 KODEX 수익률(%)의 평균
    perf: dict
    vs_kodex_matched: Stat = None        # 참고: 우리가 투자한 날만 KODEX 200을 보유한 것과 비교한 로그성장 초과(연환산)
    kodex_perf: dict = None              # 참고: 같은 창에서 KODEX 200 계속 보유의 연수익·최대 낙폭·샤프


def _trade_kodex_excess(trades: list, bench: pd.DataFrame):
    values = []
    for t in trades:
        if t.entry_date not in bench.index or t.exit_date not in bench.index:
            continue
        start = bench["open"].loc[t.entry_date] if t.entry_mode == "next_open" else bench["close"].loc[t.entry_date]
        if start <= 0:
            continue
        values.append(t.net_return_pct - (bench["close"].loc[t.exit_date] / start - 1) * 100)
    return math.fsum(values) / len(values) if values else None


def evaluate(days: list, frames: dict, bench: pd.DataFrame, window: Window, *, exit_kwargs: dict, bucket: int = 200_000,
             k: int = K, slippage_pct: float = 0.1, entry_mode: str = "next_open", seed: int = SEED,
             draws: int = DRAWS) -> Evaluation:
    in_window = [d for d in days if window.signal_start <= d.date <= window.signal_end]
    trades = run_slots(in_window, frames, entry_mode, bucket=bucket, k=k, slippage_pct=slippage_pct, **exit_kwargs)
    account = slot_account(trades, frames, window.dates, k)
    kodex = benchmark_returns(bench, window.dates)

    index = pd.Index(window.dates)
    sums = pd.Series(0.0, index=index)
    counts = pd.Series(0.0, index=index)
    for t in trades:
        sums.loc[t.signal_date] += t.net_return_pct
        counts.loc[t.signal_date] += 1.0
    use = utilisation(account, k)
    return Evaluation(
        trades=trades, ret=account["ret"], open=account["open"], n_trades=len(trades),
        trade_mean=ratio_stat(sums.to_numpy(), counts.to_numpy(), seed=seed, draws=draws),
        vs_kodex=log_growth_excess(account["ret"].to_numpy(), kodex.to_numpy(), seed=seed, draws=draws),
        vs_cash=log_growth_excess(account["ret"].to_numpy(), None, seed=seed, draws=draws),
        kodex_ret=kodex, avg_hold_days=float(np.mean([t.held_days for t in trades])) if trades else None,
        exposure=use["exposure"], avg_slots=use["avg_slots"], trade_kodex_excess_mean=_trade_kodex_excess(trades, bench),
        perf=perf(account["ret"], account["open"] > 0),
        vs_kodex_matched=log_growth_excess(account["ret"].to_numpy(), matched_benchmark(kodex, account["open"] > 0).to_numpy(),
                                           seed=seed, draws=draws),
        kodex_perf=perf(kodex))


def vs_baseline(ret, baseline_ret, *, seed: int = SEED, draws: int = DRAWS) -> Stat:
    """③ 기준선 계좌 대비 계좌 로그성장 초과(연환산)."""
    return log_growth_excess(np.asarray(ret, dtype=float), np.asarray(baseline_ret, dtype=float), seed=seed, draws=draws)
