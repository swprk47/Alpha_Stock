"""슬롯 제한 계좌(설계서 3절): 동시 보유를 K개로 제한하고, 열린 포지션들의 일간 수익률 합 / K 를 계좌 수익률로 본다.

PR #31 의 "열린 포지션 전체 균등 평균"은 동시 보유 수에 상한이 없어 보유가 긴 후보일수록 수십 종목을 평균했다.
앱 사이징이 종목당 예산의 50%를 배정하므로 실제 동시 보유는 대략 2종목이다(근사).
"""
import pandas as pd

from backtest.analysis.equity import trade_daily_factors
from backtest.signals import daily_picks
from backtest.simulate import simulate_trade

K = 2
PICKS = 3


def run_slots(days: list, frames: dict, entry_mode: str, *, bucket: int, k: int = K, slippage_pct: float = 0.1,
              top_n: int = PICKS, **exit_kwargs) -> list:
    """날짜순으로 그날 추천을 순위 순서로 훑어 거래를 연다. 건너뛰는 경우:
    같은 종목의 열린 거래(청산일 > 신호일)가 있거나, 열린 거래가 이미 k개. 청산일이 신호일 이하면 슬롯이 빈 것으로 본다
    (신호일 종가에 청산된 뒤 다음날 시가에 다시 들어갈 수 있다). simulate_trade 가 None 이면 슬롯을 쓰지 않고 다음 순위로 넘어간다."""
    accepted, open_trades = [], []
    for day in sorted(days, key=lambda d: d.date):
        date = day.date
        open_trades = [t for t in open_trades if t.exit_date > date]
        for sig in daily_picks(day, top_n):
            if len(open_trades) >= k:
                break
            if any(t.code == sig.code for t in open_trades):
                continue
            trade = simulate_trade(frames[sig.code], sig.code, date, entry_mode, score=sig.score, bucket=bucket,
                                   slippage_pct=slippage_pct, **exit_kwargs)
            if trade is None:
                continue
            accepted.append(trade)
            open_trades.append(trade)
    return accepted


def slot_account(trades: list, frames: dict, dates: list, k: int = K) -> pd.DataFrame:
    """dates 전체에 대한 계좌 일간 수익률 ret(열린 포지션 일간 수익률 합 / k, 빈 슬롯은 현금 0)과 열린 포지션 수 open."""
    index = pd.Index(dates)
    parts = [trade_daily_factors(t, frames[t.code]) - 1 for t in trades]
    if not parts:
        return pd.DataFrame({"ret": 0.0, "open": 0}, index=index)
    stacked = pd.concat(parts)
    total = stacked.groupby(level=0).sum() / k
    count = stacked.groupby(level=0).size()
    return pd.DataFrame({"ret": total.reindex(index).fillna(0.0), "open": count.reindex(index).fillna(0).astype(int)}, index=index)


def utilisation(account: pd.DataFrame, k: int = K) -> dict:
    """시장 노출(보유 포지션이 있는 날 비율)과 평균 슬롯 사용률(열린 포지션 수 / k 의 일평균)."""
    if len(account) == 0:
        return {"exposure": 0.0, "avg_slots": 0.0}
    return {"exposure": float((account["open"] > 0).mean()), "avg_slots": float((account["open"] / k).mean())}
