"""학습 선별(설계서 5.1): 방향마다 1개를 뽑고, 기준선보다 낫지 않으면 접고, 조합과 검증 후보 수 N, 후보별 MDE를 정한다.

선별 지표는 학습 계좌의 KODEX 200 대비 로그성장 초과(`vs_kodex`)다. 거래마다 KODEX를 빼면 시장 필터(F1)처럼
시장 타이밍으로 이기는 후보가 지워지기 때문이다. 대신 절대 기대값이 기준선 이하인 후보는 접는다(비용 때문에 합격할 수 없는
후보가 검증 칸과 보정 몫을 차지하지 않게).
"""
from dataclasses import dataclass, field, replace

from .candidates import DIRECTIONS, REGISTRY, Candidate, Combo, by_name
from .stats import mde

_NEG_INF = float("-inf")


@dataclass
class Selection:
    chosen: dict                 # 방향 -> 후보 이름 또는 None
    folded: dict                 # 방향 -> 접힌 사유("no_data" | "metric_not_better" | "absolute_not_better")
    combo: "Combo | None"        # 뽑힌 방향이 둘 이상일 때 만든 조합(검증 후보에 넣을지는 decide_combo 가 정한다)
    finalists: list = field(default_factory=list)      # 검증 후보(Candidate / Combo)
    n: int = 0                   # 검증 후보 수 N


def _value(stat_holder, attr):
    return getattr(getattr(stat_holder, attr), "point", None)


def select_train(evals: dict, baseline) -> Selection:
    """evals: 후보 이름 -> 학습 Evaluation(vs_kodex, trade_mean 필요). 방향마다 선별 지표가 가장 높은 후보를 뽑고
    (동률이면 레지스트리 순서), 기준선보다 지표가 낮거나 같거나 절대 평균이 기준선 이하이면 그 방향은 접는다."""
    base_metric = _value(baseline, "vs_kodex")
    base_mean = _value(baseline, "trade_mean")
    base_metric = _NEG_INF if base_metric is None else base_metric
    base_mean = _NEG_INF if base_mean is None else base_mean
    chosen, folded = {}, {}
    for direction in DIRECTIONS:
        best, best_metric = None, None
        for candidate in REGISTRY:
            if candidate.direction != direction or candidate.name not in evals:
                continue
            metric = _value(evals[candidate.name], "vs_kodex")
            if metric is None:
                continue
            if best is None or metric > best_metric:           # 엄격히 클 때만 바꿔 동률은 등록 순서를 따른다
                best, best_metric = candidate, metric
        if best is None:
            chosen[direction], folded[direction] = None, "no_data"
            continue
        mean = _value(evals[best.name], "trade_mean")
        if best_metric <= base_metric:
            chosen[direction], folded[direction] = None, "metric_not_better"
        elif mean is None or mean <= base_mean:
            chosen[direction], folded[direction] = None, "absolute_not_better"
        else:
            chosen[direction] = best.name
    singles = [by_name(name) for name in chosen.values() if name is not None]
    combo = None
    if len(singles) >= 2:
        pick = {d: by_name(chosen[d]) if chosen[d] else None for d in DIRECTIONS}
        combo = Combo(signal=pick["signal"], filter=pick["filter"], exit=pick["exit"])
    return Selection(chosen=chosen, folded=folded, combo=combo, finalists=list(singles), n=len(singles))


def decide_combo(selection: Selection, combo_eval, evals: dict) -> Selection:
    """조합의 학습 평가가 뽑힌 단일 후보들의 최댓값을 지표와 절대 평균 모두에서 넘을 때만 검증 후보에 넣는다.
    학습 데이터만 쓰는 결정이며, 아니면 조합은 버린다."""
    if selection.combo is None or combo_eval is None:
        return replace(selection, n=len(selection.finalists))
    names = [name for name in selection.chosen.values() if name is not None]
    metrics = [_value(evals[name], "vs_kodex") for name in names]
    means = [_value(evals[name], "trade_mean") for name in names]
    combo_metric, combo_mean = _value(combo_eval, "vs_kodex"), _value(combo_eval, "trade_mean")
    if (combo_metric is None or combo_mean is None or any(m is None for m in metrics + means)
            or combo_metric <= max(metrics) or combo_mean < max(means)):
        return replace(selection, n=len(selection.finalists))
    finalists = list(selection.finalists) + [selection.combo]
    return replace(selection, finalists=finalists, n=len(finalists))


def train_mde(evals: dict, baseline, finalists: list, *, train_days: int, test_days: int, combo_eval=None) -> dict:
    """검증 후보마다 **그 후보 자신의 학습 표준오차**로 최소 검출 효과를 계산한다(후보마다 거래 수·분산이 다르다).
    trade_mean: 0 기준 MDE, trade_vs_baseline_needed: 기준선 학습 평균 대비로 필요한 개선 폭(MDE - 기준선 평균),
    vs_kodex: KODEX 대비 계좌 로그성장 초과(연환산)의 MDE. 정규 근사 추정이다."""
    n = len(finalists)
    base_mean = _value(baseline, "trade_mean")
    out = {}
    for candidate in finalists:
        ev = combo_eval if isinstance(candidate, Combo) else evals.get(candidate.name)
        if ev is None:
            out[candidate.name] = {"trade_mean": None, "trade_vs_baseline_needed": None, "vs_kodex": None}
            continue
        trade = mde(ev.trade_mean.se, train_days, test_days, n)
        out[candidate.name] = {
            "trade_mean": trade,
            "trade_vs_baseline_needed": None if trade is None or base_mean is None else trade - base_mean,
            "vs_kodex": mde(ev.vs_kodex.se, train_days, test_days, n)}
    return out
