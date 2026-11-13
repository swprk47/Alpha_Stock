"""판정(설계서 6절): 합격 / 유망 / 불합격.

유의 = 점추정 > 0 이고 한쪽 p <= alpha_adj = 0.05 / N(검증 후보 수). 경계 표시는 판정을 바꾸지 않는다.
"""
from dataclasses import dataclass

from .stats import Stat, near_threshold, significant

ALPHA = 0.05


@dataclass(frozen=True)
class Verdict:
    label: str            # "합격" | "유망" | "불합격"
    flags: dict


def no_candidates_verdict() -> str:
    return "개선 후보 없음"


def judge_candidate(trade_mean: Stat, vs_kodex: Stat, vs_baseline: Stat, vs_cash: Stat, n: int, *, pre_exposed: bool,
                    dividend_sensitive: bool = False) -> Verdict:
    """합격: ① 거래당 순손익 유의 그리고 ② KODEX 200 보유 대비 유의.
    유망(합격 아님): ③ 기준선 대비 유의 그리고 ① 점추정 > 0 그리고 ④ 현금 대비 점추정 > 0
    (거래를 덜 하기만 해도 기준선 대비는 양수가 되므로, 현금보다 나쁜 후보가 유망이 되지 않게 한다)."""
    if n <= 0:
        raise ValueError("판정은 검증 후보 수 N >= 1 일 때만 한다")
    alpha_adj = ALPHA / n
    passed = significant(trade_mean, alpha_adj) and significant(vs_kodex, alpha_adj)
    promising = (not passed and significant(vs_baseline, alpha_adj)
                 and trade_mean.point is not None and trade_mean.point > 0
                 and vs_cash.point is not None and vs_cash.point > 0)
    label = "합격" if passed else ("유망" if promising else "불합격")
    return Verdict(label, {
        "alpha_adj": alpha_adj,
        "p_trade_mean": trade_mean.p_one, "p_vs_kodex": vs_kodex.p_one, "p_vs_baseline": vs_baseline.p_one,
        "near_threshold": {"trade_mean": near_threshold(trade_mean, alpha_adj), "vs_kodex": near_threshold(vs_kodex, alpha_adj),
                           "vs_baseline": near_threshold(vs_baseline, alpha_adj)},
        "pre_exposed": pre_exposed, "dividend_sensitive": dividend_sensitive})
