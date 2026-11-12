"""월 단위 교체 엔진: 목표 비중 → 일간 수익률, 회전율, 비용.

가치 1.0 현금으로 시작해 달력 날짜마다 시가 단계(교체일만)와 종가 단계(매일)를 처리한다.
거래 가능 = 그날 행이 있고 halt가 아님. 묶인 종목(행 없음·halt)은 가치를 유지하고 사고팔지 않는다.
"""
from dataclasses import dataclass

import pandas as pd

from backtest.forward.costs import CostModel


@dataclass
class PortfolioResult:
    daily: pd.Series      # 달력 날짜 인덱스의 일간 수익률
    turnover: pd.Series   # 교체일 인덱스, 가치 대비 비율
    cost: pd.Series       # 교체일 인덱스, 가치 대비 비율


class _Prices:
    """프레임 하나의 날짜별 거래 가능 여부·시가·종가를 빠르게 찾는 도구."""

    def __init__(self, frame):
        self.pos = {ts: i for i, ts in enumerate(frame.index)}
        self.open = frame["open"].to_numpy(dtype=float)
        self.close = frame["close"].to_numpy(dtype=float)
        self.halt = frame["halt"].to_numpy(dtype=bool)
        self.last_date = frame.index[-1] if len(frame) else None

    def tradable(self, d):
        i = self.pos.get(d)
        return i is not None and not self.halt[i]

    def at(self, d, col):
        return (self.open if col == "open" else self.close)[self.pos[d]]


def run_portfolio(frames, calendar, targets, cost: CostModel, *, start, end,
                  etf_codes=frozenset()) -> PortfolioResult:
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    days = [d for d in calendar if start <= d <= end]
    px = {code: _Prices(f) for code, f in frames.items()}
    trade_set = {pd.Timestamp(k) for k in targets}
    tgt = {pd.Timestamp(k): v for k, v in targets.items()}

    cash = 1.0
    hold = {}      # 코드 -> [가치, 마지막 가격]
    prev_v = 1.0
    daily, turnover, costs = {}, {}, {}
    for d in days:
        if d in trade_set:
            cash = _rebalance(d, tgt[d], px, hold, cash, cost, etf_codes, turnover, costs)
        # 종가 단계
        for code, h in hold.items():
            p = px[code]
            if p.tradable(d):
                c = p.at(d, "close")
                h[0] *= c / h[1]
                h[1] = c
        # 일봉이 끝난(상장폐지) 종목은 마지막 종가로 판다. 그날이 교체일이면 시가 단계에서는 행이 없어
        # 묶인 종목으로 남고(재조정 대상 아님), 여기서 판 돈은 다음 교체일까지 현금으로 남는다.
        for code in [c for c, _ in hold.items() if px[c].last_date < d]:
            cash += hold[code][0] * (1.0 - cost.sell_rate(d, etf=code in etf_codes))
            del hold[code]
        v = cash + sum(h[0] for h in hold.values())
        daily[d] = v / prev_v - 1.0
        prev_v = v
    idx = pd.DatetimeIndex(days)
    return PortfolioResult(
        daily=pd.Series(daily, index=idx, dtype=float),
        turnover=pd.Series(turnover, dtype=float).rename_axis(None).sort_index(),
        cost=pd.Series(costs, dtype=float).rename_axis(None).sort_index(),
    )


def _rebalance(d, target, px, hold, cash, cost, etf_codes, turnover, costs):
    """교체일 시가 단계. 갱신된 현금을 돌려주고 hold를 제자리에서 고친다."""
    for code, h in hold.items():
        p = px[code]
        if p.tradable(d):
            o = p.at(d, "open")
            h[0] *= o / h[1]
            h[1] = o
    v = cash + sum(h[0] for h in hold.values())
    frozen = sum(h[0] for c, h in hold.items() if not px[c].tradable(d))
    live = {c: w for c, w in target.items() if c in px and px[c].tradable(d)}
    s_all, w_live = sum(target.values()), sum(live.values())
    want = {c: ((v - frozen) * s_all * w / w_live if w_live else 0.0) for c, w in live.items()}
    for c, h in hold.items():
        if px[c].tradable(d) and c not in want:
            want[c] = 0.0
    buys = sells = fee = 0.0
    for c, goal in want.items():
        delta = goal - (hold[c][0] if c in hold else 0.0)
        if delta > 0:
            buys += delta
            fee += delta * cost.buy_rate()
        elif delta < 0:
            sells -= delta
            fee += -delta * cost.sell_rate(d, etf=c in etf_codes)
    turnover[d] = max(buys, sells) / v if v else 0.0
    costs[d] = fee / v if v else 0.0
    scale = (v - fee) / v if v else 1.0
    for c, goal in want.items():
        if c in hold:
            hold[c][0] = goal
        elif goal > 0:
            hold[c] = [goal, px[c].at(d, "open")]
    for c in [c for c, h in hold.items() if h[0] <= 0]:
        del hold[c]
    for h in hold.values():
        h[0] *= scale
    return (v - frozen - sum(w for w in want.values())) * scale


def monthly_returns(daily: pd.Series, trade_days) -> pd.Series:
    """이웃한 교체일 쌍 [t_k, t_{k+1})의 일간 수익률을 복리로 묶는다. 마지막 교체일 뒤 구간은 넣지 않는다."""
    out = {}
    for a, b in zip(trade_days[:-1], trade_days[1:]):
        seg = daily[(daily.index >= a) & (daily.index < b)]
        out[a] = float((1.0 + seg).prod() - 1.0)
    return pd.Series(out, dtype=float)
