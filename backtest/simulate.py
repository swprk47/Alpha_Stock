"""거래 시뮬레이션: 앱의 익절·손절·보유 만료 규칙을 일봉에 적용한다(보수적 가정)."""
from dataclasses import dataclass

import pandas as pd

from fees import calc_buy_cost, calc_sell_proceeds
from orders import DEFAULT_STOP_RATIO, DEFAULT_TARGET_RATIO

from .signals import daily_picks

NOTIONAL_SHARES = 1000          # 수수료 내림(원 단위) 영향을 없애려고 1,000주 기준으로 비용을 계산한다
ENTRY_MODES = ("close", "next_open")


@dataclass(frozen=True)
class Trade:
    code: str
    bucket: int
    entry_mode: str            # "close" | "next_open"
    signal_date: pd.Timestamp
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_price: int
    exit_price: int
    exit_reason: str           # "target" | "stop" | "expire"
    net_return_pct: float
    held_days: int             # 진입 행과 청산 행의 행 번호 차
    score: int


def _slipped(price, slippage_pct: float, sign: int) -> int:
    return int(round(float(price) * (1 + sign * slippage_pct / 100)))


def simulate_trade(frame, code, signal_date, entry_mode, *, score=0, bucket=0,
                   target_ratio=DEFAULT_TARGET_RATIO, stop_ratio=DEFAULT_STOP_RATIO,
                   hold_days=5, slippage_pct=0.0):
    """신호 하나의 거래 결과. 진입 불가이거나 보유 기간이 데이터 끝을 넘으면(미완결) None."""
    if entry_mode not in ENTRY_MODES:
        raise ValueError(f"unknown entry_mode: {entry_mode}")
    index = frame.index
    if signal_date not in index:
        return None
    pos = index.get_loc(signal_date)
    last_pos = pos + hold_days
    if last_pos >= len(frame):
        return None
    if entry_mode == "close":
        entry_pos, raw_entry = pos, frame["close"].iloc[pos]
    else:
        entry_pos = pos + 1
        if frame["halt"].iloc[entry_pos]:
            return None
        raw_entry = frame["open"].iloc[entry_pos]
    entry_price = _slipped(raw_entry, slippage_pct, +1)
    target = int(entry_price * target_ratio)
    stop = int(entry_price * stop_ratio)

    exit_pos, reason, raw_exit = last_pos, "expire", frame["close"].iloc[last_pos]
    for p in range(pos + 1, last_pos + 1):
        row = frame.iloc[p]
        if row["halt"]:
            continue                                         # 거래정지일은 판단에서 건너뛴다
        if row["low"] <= stop:                               # 같은 날 둘 다 닿아도 손절이 먼저
            exit_pos, reason, raw_exit = p, "stop", min(row["open"], stop)   # 갭 하락이면 시가로 체결
            break
        if row["high"] >= target:
            exit_pos, reason, raw_exit = p, "target", target                 # 갭 상승 보너스 없이 목표가
            break
    exit_price = _slipped(raw_exit, slippage_pct, -1)

    buy_total = calc_buy_cost(entry_price, NOTIONAL_SHARES)["total"]
    sell_net = calc_sell_proceeds(exit_price, NOTIONAL_SHARES)["net"]
    return Trade(code, bucket, entry_mode, signal_date, index[entry_pos], index[exit_pos],
                 entry_price, exit_price, reason, (sell_net / buy_total - 1) * 100, exit_pos - entry_pos, int(score))


def simulate_picks(days, frames, entry_mode, *, bucket, top_n=3, **sim_kwargs) -> list:
    """날짜순으로 그날의 추천을 거래로 만든다. 같은 종목이 보유 중이면(직전 청산일 이하) 새 거래로 세지 않는다."""
    trades, busy_until = [], {}
    for day in sorted(days, key=lambda d: d.date):
        for sig in daily_picks(day, top_n):
            if sig.code in busy_until and sig.date <= busy_until[sig.code]:
                continue
            trade = simulate_trade(frames[sig.code], sig.code, sig.date, entry_mode,
                                   score=sig.score, bucket=bucket, **sim_kwargs)
            if trade is None:
                continue
            busy_until[sig.code] = trade.exit_date
            trades.append(trade)
    return trades
