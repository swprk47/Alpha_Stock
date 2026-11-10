"""날짜별 요소: 앱의 calculate_technical_indicators 를 그대로 쓰고(롤링뿐이라 최근 60봉 창과 같은 값), 앱에 없는 ATR 만 더한다."""
import numpy as np
import pandas as pd

from strategy import calculate_technical_indicators

from backtest.signals import RAW_COLUMNS

FEATURE_COLUMNS = ("gap20", "ma_gap", "rsi", "vol_ratio", "pctb", "atr_pct")
ATR_WINDOW = 14


def compute_features(frame: pd.DataFrame) -> pd.DataFrame:
    """프레임과 같은 날짜 인덱스의 요소 표. 날짜 t 의 값은 t 까지의 일봉만 쓴다. 지표를 만들 수 없으면 전부 NaN."""
    out = pd.DataFrame(np.nan, index=frame.index, columns=list(FEATURE_COLUMNS))
    ind = calculate_technical_indicators(frame[RAW_COLUMNS])
    if ind is None:
        return out
    close, ma20 = ind["close"], ind["ma20"]
    out["gap20"] = (close - ma20) / ma20
    out["ma_gap"] = (ind["ma5"] - ma20) / ma20
    out["rsi"] = ind["rsi14"]
    vol_ma5 = ind["vol_ma5"]
    out["vol_ratio"] = (ind["volume"] / (vol_ma5 + 1)).where(vol_ma5 > 0, 1.0).where(vol_ma5.notna())
    width = ind["bb_upper"] - ind["bb_lower"]
    out["pctb"] = ((close - ind["bb_lower"]) / width).where(width > 0)
    prev_close = close.shift(1)
    true_range = pd.concat([ind["high"] - ind["low"], (ind["high"] - prev_close).abs(),
                            (ind["low"] - prev_close).abs()], axis=1).max(axis=1)
    out["atr_pct"] = true_range.rolling(ATR_WINDOW).mean() / close
    return out
