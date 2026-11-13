"""일봉 프레임: 뒤 행을 보지 않는 열만 만든다(halt, ret, bad)."""
import numpy as np
import pandas as pd

from backtest.forward import registry

_COLS = ["open", "high", "low", "close", "volume"]


def prepare(raw: pd.DataFrame) -> pd.DataFrame:
    """date, open, high, low, close, volume 일봉을 날짜 인덱스 프레임(+ halt, ret, bad)으로 바꾼다.

    모든 열은 자기 행과 앞 행만으로 계산한다(기존 prepare_frame의 vol_break·pre_split은 뒤 행을 봐서 쓰지 않는다).
    """
    df = raw[["date"] + _COLS].copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.drop_duplicates(subset="date", keep="last").sort_values("date").set_index("date")
    # 값이 빠진(NaN) 행도 거래정지로 본다: 사고팔거나 평가하지 않고, 그 행과 다음 행의 ret 은 NaN.
    df["halt"] = ((df["volume"] == 0) | (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
                  | df[_COLS].isna().any(axis=1))
    prev_close = df["close"].shift(1)
    prev_halt = df["halt"].shift(1, fill_value=True)       # 첫 행은 직전이 없으므로 NaN으로 만든다
    valid = ~df["halt"] & ~prev_halt.astype(bool)
    ret = (df["close"] / prev_close - 1.0).where(valid, np.nan)
    df["ret"] = ret.astype(float)
    df["bad"] = (df["ret"].abs() > registry.BAD_RETURN).fillna(False).astype(bool)
    return df[_COLS + ["halt", "ret", "bad"]]


def load_all(codes, cache, *, min_rows=60):
    """캐시된 일봉을 prepare한 프레임과, 없거나 min_rows 미만이라 뺀 코드(codes 순서) 목록."""
    frames, skipped = {}, []
    for code in codes:
        raw = cache.load(code)
        if raw is None or len(raw) < min_rows:
            skipped.append(code)
        else:
            frames[code] = prepare(raw)
    return frames, skipped


def truncate(frames: dict, end) -> dict:
    """각 프레임에서 end 이하 행만 남긴 새 딕셔너리(행이 없는 코드는 뺀다). 입력은 바꾸지 않는다."""
    end = pd.Timestamp(end)
    out = {}
    for code, df in frames.items():
        cut = df.loc[df.index <= end]
        if len(cut):
            out[code] = cut.copy()
    return out
