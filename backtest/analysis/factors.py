"""요소별 예측력 검정: 요소 하나당 순위상관 한 번(구간별 전수 비교 없음), Holm 보정, 학습/검증 동시 통과 판정.

순위는 넘겨받은 표본 전체에서 한 번만 매기고 재추출 동안 고정한다(날짜별 합계로 계산해 속도를 확보).
"""
import math

import numpy as np
import pandas as pd

from .bootstrap import DEFAULT_SEED, DRAWS, BootResult, bootstrap_sums

MIN_BIN = 200
FACTOR_COLUMNS = ("gap20", "ma_gap", "rsi", "vol_ratio", "pctb", "atr_pct", "score")
FIXED_EDGES = {"gap20": [0, 0.03, 0.06], "rsi": [30, 45, 60, 70], "pctb": [0, 0.5, 1], "score": [70, 80]}
QUANTILE_BINS = {"ma_gap": 4, "vol_ratio": 5, "atr_pct": 3}
SCORE = "score"
PASS_P = 0.05
STABLE_SHARE = 2 / 3
_NONE = BootResult(None, None, None, None, 0, 0)


def train_edges(panel: pd.DataFrame) -> dict:
    """요소별 구간 경계. 분위수 요소는 학습 기간 행으로만 계산한다(검증 기간 값은 경계에 영향이 없다)."""
    edges = {col: list(values) for col, values in FIXED_EDGES.items()}
    train = panel[panel["period"] == "train"] if len(panel) else panel
    for col, parts in QUANTILE_BINS.items():
        values = train[col].dropna() if len(train) else pd.Series(dtype=float)
        edges[col] = [float(q) for q in np.quantile(values, [i / parts for i in range(1, parts)])] if len(values) else []
    return edges


def assign_bins(values: pd.Series, edges: list) -> pd.Series:
    """경계 이상·다음 경계 미만이 한 구간(0..len(edges)). NaN 은 NaN 으로 둔다."""
    out = pd.Series(np.nan, index=values.index, dtype=float)
    ok = values.notna()
    out[ok] = np.digitize(values[ok].to_numpy(dtype=float), edges)
    return out


def merge_small_bins(counts: list, min_n: int = MIN_BIN) -> list:
    """원래 구간마다 병합 구간 번호. 둘 이상이고 min_n 미만인 구간이 있으면 가장 작은 구간을 인접 구간 중 건수가 적은 쪽
    (같으면 왼쪽)에 합치고 반복한다."""
    groups = [[i] for i in range(len(counts))]
    sizes = [int(c) for c in counts]
    while len(groups) > 1 and min(sizes) < min_n:
        j = sizes.index(min(sizes))
        neighbours = [k for k in (j - 1, j + 1) if 0 <= k < len(groups)]
        target = min(neighbours, key=lambda k: (sizes[k], k))
        lo, hi = sorted((j, target))
        groups[lo] = groups[lo] + groups[hi]
        sizes[lo] += sizes[hi]
        del groups[hi], sizes[hi]
    mapping = [0] * len(counts)
    for gi, members in enumerate(groups):
        for m in members:
            mapping[m] = gi
    return mapping


def _usable(panel: pd.DataFrame, column: str) -> pd.DataFrame:
    """점수는 앱이 60 점 미만에 None 을 돌려줘 통과 종목에서만 알 수 있으므로 통과 행만 쓴다."""
    frame = panel[panel["passed"].astype(bool)] if column == SCORE else panel      # 빈 패널의 object 열은 불리언 마스크로 쓰면 열 선택으로 해석된다
    return frame[["date", column, "net_return_pct"]].dropna()


def _pearson(sums: np.ndarray) -> float:
    n, sx, sy, sxy, sxx, syy = sums
    var_x, var_y = n * sxx - sx * sx, n * syy - sy * sy
    if var_x <= 1e-9 * max(n * sxx, 1.0) or var_y <= 1e-9 * max(n * syy, 1.0):
        return math.nan
    return (n * sxy - sx * sy) / math.sqrt(var_x * var_y)


def rank_corr_test(panel: pd.DataFrame, column: str, *, seed: int = DEFAULT_SEED, draws: int = DRAWS) -> BootResult:
    """요소와 순손익의 순위상관(스피어만)과 날짜 블록 부트스트랩 신뢰구간·p값. 퇴화(상수 열·상수 손익)면 점추정이 None."""
    frame = _usable(panel, column)
    if len(frame) < 3:
        return _NONE
    x = frame[column].rank(method="average").to_numpy()
    y = frame["net_return_pct"].rank(method="average").to_numpy()
    sums = pd.DataFrame({"date": frame["date"].to_numpy(), "n": 1.0, "x": x, "y": y, "xy": x * y, "xx": x * x, "yy": y * y})
    day_stats = sums.groupby("date").sum().to_numpy()
    return bootstrap_sums(day_stats, _pearson, draws=draws, seed=seed)


def holm(pvals: dict) -> dict:
    """Holm 보정 p값. None 은 그대로 None 이고 비교 개수에서 뺀다."""
    valid = sorted((p, name) for name, p in pvals.items() if p is not None)
    m = len(valid)
    out = {name: None for name in pvals}
    running = 0.0
    for j, (p, name) in enumerate(valid):
        running = max(running, min(1.0, (m - j) * p))
        out[name] = running
    return out


def _sign(value) -> int:
    return 0 if value is None or value == 0 or math.isnan(value) else (1 if value > 0 else -1)


def yearly_signs(panel: pd.DataFrame, column: str) -> dict:
    """연도별 표본 순위상관의 부호(+1/-1, 계산 불가나 0 은 0)."""
    frame = _usable(panel, column)
    signs = {int(year): 0 for year in pd.to_datetime(panel["date"]).dt.year.unique()}
    for year, part in frame.groupby(pd.to_datetime(frame["date"]).dt.year):
        if len(part) >= 3:
            rho = _pearson(_rank_sums(part[column].rank().to_numpy(), part["net_return_pct"].rank().to_numpy()))
            signs[int(year)] = _sign(rho)
    return signs


def _rank_sums(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.array([float(len(x)), x.sum(), y.sum(), (x * y).sum(), (x * x).sum(), (y * y).sum()])


def judge(train: BootResult, test: BootResult, signs: dict, holm_p) -> str:
    """"유의" 는 학습 Holm 통과 + 검증 같은 방향·95% 구간이 0 제외 + 연도 3분의 2 이상 같은 방향일 때만."""
    if holm_p is None or train.point is None or test.point is None or test.lo is None:
        return "판정 불가"
    direction = _sign(train.point)
    passed = (holm_p < PASS_P and direction != 0 and _sign(test.point) == direction
              and (test.lo > 0 or test.hi < 0))
    if not passed:
        return "근거 부족"
    considered = [s for s in signs.values() if s != 0]
    if not considered or sum(1 for s in considered if s == direction) / len(considered) < STABLE_SHARE:
        return "불안정"
    return "유의"


def _label(lo, hi) -> str:
    if lo is None and hi is None:
        return "전체"
    if lo is None:
        return f"<{hi:.4g}"
    if hi is None:
        return f">={lo:.4g}"
    return f"{lo:.4g}~{hi:.4g}"


def bin_table(panel: pd.DataFrame, column: str, edges: list) -> list:
    """병합(건수 200 미만) 뒤 구간별 건수와 평균 순손익."""
    frame = _usable(panel, column)
    if frame.empty:
        return []
    bins = assign_bins(frame[column], edges).astype(int)
    counts = [int((bins == i).sum()) for i in range(len(edges) + 1)]
    mapping = merge_small_bins(counts)
    merged = bins.map(lambda b: mapping[b])
    table = []
    for gi in sorted(set(mapping)):
        members = [i for i, g in enumerate(mapping) if g == gi]
        lo = edges[members[0] - 1] if members[0] > 0 else None
        hi = edges[members[-1]] if members[-1] < len(edges) else None
        rows = frame.loc[merged == gi, "net_return_pct"]
        table.append({"label": _label(lo, hi), "n": int(len(rows)), "mean": float(rows.mean()) if len(rows) else None})
    return table
