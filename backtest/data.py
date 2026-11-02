"""일봉 데이터 준비: 상장 목록, 캐시·다운로드, 프레임(거래정지·분할 표시)."""
import numpy as np
import pandas as pd

BREAK_RATIO = 10          # 분할로 보는 거래량 수준 변화(배)
BREAK_MAX_PRICE_MOVE = 0.35  # 종가가 이어지는 것으로 보는 최대 등락
BREAK_PAD = 6             # 분할 위치 앞뒤로 신호에서 빼는 봉 수
_WINDOW = 5               # 분할 판단에 쓰는 앞·뒤 봉 수


def _median_nonzero(values) -> float:
    nz = [v for v in values if v > 0]
    return float(np.median(nz)) if nz else 0.0


def _is_level_shift(v: float, before: float, after: float) -> bool:
    """해당 봉(v)과 이후 중앙값(after)이 앞 중앙값(before)에 비해 같은 방향으로 BREAK_RATIO 배 이상 바뀌었나."""
    if before <= 0 or after <= 0 or v <= 0:
        return False
    up = v / before >= BREAK_RATIO and after / before >= BREAK_RATIO
    down = v / before <= 1 / BREAK_RATIO and after / before <= 1 / BREAK_RATIO
    return up or down


def _volume_break_mask(close: np.ndarray, volume: np.ndarray) -> np.ndarray:
    n = len(volume)
    mask = np.zeros(n, dtype=bool)
    move = np.zeros(n)                                       # 일별 등락률 절댓값
    move[1:] = np.abs(close[1:] / np.where(close[:-1] > 0, close[:-1], np.nan) - 1)
    move = np.nan_to_num(move, nan=1.0)
    prev_flagged = False
    for i in range(_WINDOW, n - _WINDOW + 1):
        flagged = False
        if volume[i] > 0 and move[i - _WINDOW + 1:i + 1].max() <= BREAK_MAX_PRICE_MOVE:   # 직전 5봉 동안 가격이 이어졌다
            before = _median_nonzero(volume[i - _WINDOW:i])
            after = _median_nonzero(volume[i:i + _WINDOW])
            flagged = _is_level_shift(float(volume[i]), before, after)
        if flagged and not prev_flagged:                     # 연속으로 걸리면 첫 위치만 분할로 본다
            mask[max(0, i - BREAK_PAD):i + BREAK_PAD + 1] = True
        prev_flagged = flagged
    return mask


def prepare_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """date, open, high, low, close, volume 열의 일봉을 날짜 인덱스 프레임으로 바꾸고 halt·vol_break 를 붙인다."""
    df = raw[["date", "open", "high", "low", "close", "volume"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.drop_duplicates(subset="date", keep="last").sort_values("date").set_index("date")
    df["halt"] = df["volume"] == 0
    df["vol_break"] = _volume_break_mask(df["close"].to_numpy(dtype=float), df["volume"].to_numpy(dtype=float))
    return df
