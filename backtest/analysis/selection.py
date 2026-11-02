"""추천 선택 효과: 추천 상위 3의 평균 순손익 - 그날 후보 풀 전체의 평균 순손익, 날짜 블록 부트스트랩 신뢰구간."""
import pandas as pd

from .bootstrap import DEFAULT_SEED, DRAWS, BootResult, bootstrap_sums


def _difference(sums) -> float:
    pick_sum, pick_n, pool_sum, pool_n = sums
    return pick_sum / pick_n - pool_sum / pool_n


def selection_effect(panel: pd.DataFrame, *, seed: int = DEFAULT_SEED, draws: int = DRAWS) -> BootResult:
    """추천(picked)이 하나도 없으면 점추정이 None 이다."""
    if panel.empty:
        return BootResult(None, None, None, None, 0, 0)
    picked = panel["picked"].astype(bool)
    net = panel["net_return_pct"]
    stats = pd.DataFrame({"date": panel["date"].to_numpy(), "pick_sum": net.where(picked, 0.0).to_numpy(),
                          "pick_n": picked.astype(float).to_numpy(), "pool_sum": net.to_numpy(), "pool_n": 1.0})
    return bootstrap_sums(stats.groupby("date").sum().to_numpy(), _difference, draws=draws, seed=seed)
