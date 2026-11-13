"""필요 기간 추정: 측정된 표준오차로 "미래 데이터가 몇 개월 필요한가"를 계산한다.

정규 근사 결과다(한쪽 2.5% 유의수준, 검정력 80%). 판정 시점을 정할 때 참고하는 값이며
정확한 보장이 아니다.
"""
import math

from backtest.forward.stats import Stat

EFFECTS_ANNUAL = (0.01, 0.02, 0.03, 0.05)  # 가정하는 연 초과수익 크기
Z_ALPHA = 1.959964  # 한쪽 2.5%
Z_POWER = 0.841621  # 검정력 80%


def effective_sd(stat: Stat) -> float:
    """묶음 재추출 표준오차에서 되돌린 월 단위 표준편차(se * sqrt(n))."""
    if stat.se is None or stat.n == 0:
        raise ValueError("빈 통계에서는 표준편차를 구할 수 없다")
    return stat.se * math.sqrt(stat.n)


def required_months(sd_monthly: float, effect_annual: float) -> int:
    """연 효과 effect_annual 을 검출하는 데 필요한 개월 수(올림)."""
    if effect_annual <= 0:
        raise ValueError("effect_annual 은 양수여야 한다")
    if sd_monthly == 0:
        return 0
    return math.ceil(((Z_ALPHA + Z_POWER) * sd_monthly / (effect_annual / 12)) ** 2)


def required_table(stat: Stat) -> dict:
    """EFFECTS_ANNUAL 마다의 필요 개월 수."""
    sd = effective_sd(stat)
    return {effect: required_months(sd, effect) for effect in EFFECTS_ANNUAL}


def episodes_per_year(episodes: list, n_days: int) -> float:
    """연(252거래일)당 낙폭 에피소드 수."""
    if n_days == 0:
        return 0.0
    return len(episodes) / (n_days / 252)
