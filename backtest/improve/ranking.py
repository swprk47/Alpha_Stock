"""방향 ③ 새 신호 S1~S4와 방향 ① 시장 필터 F1(설계서 4절).

모든 판단은 날짜 t 까지의 일봉만 쓴다. "t-20" 같은 오프셋은 각 종목(KODEX 포함)의 자기 프레임 행 기준이다.
`Signal.score` 는 0, `risk_reward` 는 0.0 으로 두어 점수 기반 집계가 순위를 점수로 오인하지 않게 한다.
"""
import numpy as np
import pandas as pd

from backtest.signals import DayResult, Signal

from .candidates import Candidate, Combo

LOOKBACK = 20           # S1 수익률 구간, S2 고점 구간
S2_MIN_VALID_ROWS = 15  # S2 의 직전 20행 중 halt 를 뺀 유효 행 최소 개수
SHORT_RETURN = 5        # S3 의 단기 수익률 구간
MA_WINDOW = 60          # S3 의 이동평균


def _arrays(frame: pd.DataFrame) -> dict:
    return {"index": frame.index, "close": frame["close"].to_numpy(dtype=float), "high": frame["high"].to_numpy(dtype=float),
            "halt": frame["halt"].to_numpy(dtype=bool), "vol_break": frame["vol_break"].to_numpy(dtype=bool),
            "ma60": frame["close"].rolling(MA_WINDOW).mean().to_numpy(dtype=float)}


def _position(arrays: dict, date) -> int:
    return int(arrays["index"].get_indexer([date])[0])           # 행이 없으면 -1


def _usable_close(arrays: dict, pos: int) -> bool:
    return pos >= 0 and arrays["close"][pos] > 0 and not arrays["halt"][pos]


def _s1_key(a: dict, pos: int, b: "dict | None", date):
    if b is None or pos < LOOKBACK:
        return None
    bpos = _position(b, date)
    if bpos < LOOKBACK or not all(_usable_close(a, p) for p in (pos, pos - LOOKBACK)):
        return None
    if not all(_usable_close(b, p) for p in (bpos, bpos - LOOKBACK)):
        return None
    stock = a["close"][pos] / a["close"][pos - LOOKBACK] - 1
    bench = b["close"][bpos] / b["close"][bpos - LOOKBACK] - 1
    return stock - bench


def _s2_key(a: dict, pos: int, vol_ratio: float):
    if pos < LOOKBACK or not np.isfinite(vol_ratio):
        return None
    window = slice(pos - LOOKBACK, pos)
    valid = ~a["halt"][window]
    if valid.sum() < S2_MIN_VALID_ROWS:
        return None
    if a["close"][pos] < a["high"][window][valid].max():
        return None
    return vol_ratio


def _s3_key(a: dict, pos: int):
    ma60 = a["ma60"][pos]
    if pos < SHORT_RETURN or not np.isfinite(ma60) or a["close"][pos] < ma60 or not _usable_close(a, pos - SHORT_RETURN):
        return None
    return a["close"][pos] / a["close"][pos - SHORT_RETURN] - 1


# (순위 키 계산이 필요한 종류, 큰 순이면 True)
_DESCENDING = {"S1": True, "S2": True, "S3": False, "S4": False}


def rank_signals(candidate: Candidate, base_days: list, frames: dict, features: dict, bench, bucket: int) -> list:
    """S1~S4: 각 날의 후보 풀에서 규칙에 맞는 종목을 순위 순서로 정렬해 새 `signals`로 만든다(풀은 그대로).
    행이 없거나 t 행이 거래정지·분할 의심이면 제외하고, 필요한 값이 없거나 NaN 이거나 종가가 0 이하이면 제외한다.
    순위가 같으면 후보 풀 순서를 유지하고, 통과가 3개 미만이면 그만큼만 만든다."""
    name = candidate.name
    descending = _DESCENDING[name]
    cache = {}
    bench_arrays = _arrays(bench) if bench is not None else None
    out = []
    for day in base_days:
        date, keyed = day.date, []
        for order, code in enumerate(day.pool):
            frame = frames.get(code)
            if frame is None:
                continue
            if code not in cache:
                cache[code] = _arrays(frame)
            a = cache[code]
            pos = _position(a, date)
            if pos < 0 or a["halt"][pos] or a["vol_break"][pos]:
                continue
            if name == "S1":
                key = _s1_key(a, pos, bench_arrays, date)
            elif name == "S2":
                key = _s2_key(a, pos, float(features[code]["vol_ratio"].iloc[pos]))
            elif name == "S3":
                key = _s3_key(a, pos)
            else:                                                      # S4
                atr = float(features[code]["atr_pct"].iloc[pos])
                key = atr if np.isfinite(atr) else None
            if key is not None and np.isfinite(key):
                keyed.append((-key if descending else key, order, code))
        keyed.sort(key=lambda item: (item[0], item[1]))                # 키가 같으면 풀 순서
        signals = [Signal(code, date, 0, 0.0, bucket) for _, _, code in keyed]
        out.append(DayResult(date, list(day.pool), signals))
    return out


def apply_filter(candidate: Candidate, days: list, bench) -> list:
    """F1: 신호일 KODEX 200 종가가 20일 단순이동평균 이상이 아니면 그날 추천을 비운다(풀은 유지).
    벤치마크에 그날 행이 없거나 20봉이 안 쌓였으면 조건 불충족이다. 다른 후보면 입력을 그대로 돌려준다."""
    if candidate.name != "F1":
        return days
    close = bench["close"]
    ma20 = close.rolling(20).mean()
    allowed = ((close >= ma20) & ma20.notna()).to_dict()
    return [DayResult(day.date, list(day.pool), list(day.signals) if allowed.get(day.date, False) else []) for day in days]


def candidate_days(spec, base_days: list, frames: dict, features: dict, bench, bucket: int) -> list:
    """후보(또는 조합)의 날짜별 추천: 신호 후보면 순위를 새로 매기고, 필터 후보면 허용되지 않는 날을 비우고,
    청산·기준선은 기준선 신호를 그대로 쓴다. 조합은 신호 -> 필터 순으로 적용한다(청산은 시뮬레이션 인자로 반영)."""
    if isinstance(spec, Combo):
        days = base_days
        if spec.signal is not None:
            days = rank_signals(spec.signal, days, frames, features, bench, bucket)
        if spec.filter is not None:
            days = apply_filter(spec.filter, days, bench)
        return days
    if spec.direction == "signal":
        return rank_signals(spec, base_days, frames, features, bench, bucket)
    if spec.direction == "filter":
        return apply_filter(spec, base_days, bench)
    return base_days
