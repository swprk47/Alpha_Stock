"""신호: 앱의 실제 analyze_stock_for_swing 을 과거 날짜마다 그대로 호출한다(점수 계산을 다시 구현하지 않는다)."""
from dataclasses import dataclass

import pandas as pd

from strategy import analyze_stock_for_swing, calculate_position_sizing

from .pool import POOL_LIMIT, select_pool

WINDOW = 60                  # 앱은 최근 60봉만 본다
RAW_COLUMNS = ["open", "high", "low", "close", "volume"]


@dataclass(frozen=True)
class Signal:
    code: str
    date: pd.Timestamp
    score: int
    risk_reward: float
    bucket: int


@dataclass
class DayResult:
    date: pd.Timestamp
    pool: list
    signals: list          # (점수, 손익비) 내림차순, 같으면 풀 순서


def evaluate(frame, code, date, bucket, *, analyze=analyze_stock_for_swing):
    """date 의 종가를 현재가로 최근 60봉을 분석한다. 통과(앱 기준 60점 이상, 수량 계산 가능)면 Signal, 아니면 None."""
    if date not in frame.index:
        return None
    row = frame.loc[date]
    if row["vol_break"] or row["halt"]:
        return None
    window = frame.loc[:date, RAW_COLUMNS].tail(WINDOW)
    stock = {"code": code, "name": code, "current_price": int(row["close"])}
    analysis = analyze(stock, window)
    if analysis is None:
        return None
    sizing = calculate_position_sizing(stock, budget=bucket)
    if sizing is None:
        return None
    return Signal(code, date, int(analysis["score"]), float(sizing["risk_reward_ratio"]), bucket)


def trading_dates(frames, warmup: int = 60) -> list:
    """모든 종목 날짜의 합집합을 정렬하고 앞 warmup 개를 뺀 목록."""
    all_dates = sorted({d for frame in frames.values() for d in frame.index})
    return all_dates[warmup:]


def generate_signals(listings, frames, bucket, dates, *, analyze=analyze_stock_for_swing, limit: int = POOL_LIMIT) -> list:
    days = []
    for date in dates:
        pool = select_pool(listings, frames, date, bucket, limit=limit)
        signals = []
        for code in pool:
            sig = evaluate(frames[code], code, date, bucket, analyze=analyze)
            if sig is not None:
                signals.append(sig)
        signals.sort(key=lambda s: (-s.score, -s.risk_reward))      # 안정 정렬이라 같으면 풀 순서가 유지된다
        days.append(DayResult(date, pool, signals))
    return days


def daily_picks(day: DayResult, top_n=3) -> list:
    """그날의 추천(앞 top_n 개). top_n 이 None 이면 통과한 전체."""
    return list(day.signals) if top_n is None else list(day.signals[:top_n])
