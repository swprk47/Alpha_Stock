"""후보-날짜 패널: 날짜별 후보 풀의 모든 종목에 요소값과 시뮬레이션 결과(순손익)를 붙인다.

추천을 통과한 종목만 보면 점수 필터가 이미 거른 뒤라 요소 자체의 힘을 못 보므로, 풀 전체를 행으로 둔다.
"""
import pandas as pd

from backtest.simulate import simulate_trade

from .features import FEATURE_COLUMNS

TRAIN_END = pd.Timestamp("2021-12-31")
PANEL_COLUMNS = ("date", "code", "bucket", "net_return_pct", *FEATURE_COLUMNS, "passed", "picked", "score", "period")


def pools_from_days(days) -> dict:
    return {day.date: list(day.pool) for day in days}


def passes_from_days(days) -> dict:
    return {day.date: list(day.signals) for day in days}


def build_panel(pools: dict, frames: dict, features: dict, entry_mode: str, *, bucket: int,
                slippage_pct: float = 0.1, passes: "dict | None" = None, top_n: int = 3) -> pd.DataFrame:
    """pools: {날짜: [코드]}, features: {코드: compute_features 결과}, passes: {날짜: 정렬된 통과 Signal 목록}.
    simulate_trade 가 None(진입 불가, 보유 기간 미완결)인 행은 뺀다. 요소값은 신호일 기준이다."""
    rows = []
    for date in sorted(pools):
        ranked = {sig.code: (i, sig) for i, sig in enumerate((passes or {}).get(date, []))}
        for code in pools[date]:
            trade = simulate_trade(frames[code], code, date, entry_mode, bucket=bucket, slippage_pct=slippage_pct)
            if trade is None:
                continue
            feat = features[code].loc[date]
            rank, sig = ranked.get(code, (None, None))
            row = {"date": date, "code": code, "bucket": bucket, "net_return_pct": trade.net_return_pct,
                   "passed": sig is not None, "picked": rank is not None and rank < top_n,
                   "score": float(sig.score) if sig is not None else float("nan"),
                   "period": "train" if date <= TRAIN_END else "test"}
            row.update({col: float(feat[col]) for col in FEATURE_COLUMNS})
            rows.append(row)
    return pd.DataFrame(rows, columns=list(PANEL_COLUMNS))
