"""일봉 데이터 준비: 상장 목록, 캐시·다운로드, 프레임(거래정지·분할 표시)."""
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from market_data import HEADERS

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


# ── 상장 목록 ──

MARKETS = ("KOSPI", "KOSDAQ")
LISTING_PAGES = (1, 2, 3)
LISTING_PAGE_SIZE = 50


@dataclass(frozen=True)
class Listing:
    code: str
    name: str
    market: str
    rank: int          # 앱의 후보 순서(코스피 먼저, 시가총액 순)에서의 위치


def fetch_listing(get=requests.get) -> list:
    """앱의 후보 선정과 같은 목록: 코스피 → 코스닥, 시총 순 3쪽 x 50개. 중복 코드는 한 번만, 실패한 쪽은 건너뛴다."""
    listings, seen = [], set()
    for market in MARKETS:
        for page in LISTING_PAGES:
            url = f"https://m.stock.naver.com/api/stocks/marketValue/{market}?page={page}&pageSize={LISTING_PAGE_SIZE}"
            try:
                res = get(url, headers=HEADERS, timeout=5)
                if res.status_code != 200:
                    continue
                stocks = res.json().get("stocks", [])
            except Exception as e:
                print(f"listing {market} page {page} failed: {e}")
                continue
            for item in stocks:
                code = item.get("itemCode")
                if not code or code in seen:
                    continue
                seen.add(code)
                listings.append(Listing(code, item.get("stockName", ""), market, len(listings)))
    return listings


# ── 일봉 캐시와 다운로드 ──

CANDLE_COLUMNS = ["date", "open", "high", "low", "close", "volume"]


class CandleCache:
    def __init__(self, root):
        self.root = Path(root)

    def _path(self, code: str) -> Path:
        return self.root / f"{code}.csv"

    def load(self, code: str):
        """저장된 일봉. 파일이 없거나 비었거나 손상됐으면 None(다시 받으면 된다)."""
        path = self._path(code)
        if not path.exists():
            return None
        try:
            df = pd.read_csv(path, parse_dates=["date"])
        except Exception:
            return None
        if df.empty or any(col not in df.columns for col in CANDLE_COLUMNS):
            return None
        return df[CANDLE_COLUMNS]

    def save(self, code: str, df: pd.DataFrame) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        df[CANDLE_COLUMNS].to_csv(self._path(code), index=False)


def download_candles(codes, cache, fetch, *, count=3000, delay_s=0.2, sleep=time.sleep, refresh=False) -> list:
    """캐시에 없는 종목만 받아 저장하고, 못 받은 종목 코드를 돌려준다(이어서 받기)."""
    failed = []
    for i, code in enumerate(codes, 1):
        if not refresh and cache.load(code) is not None:
            continue
        try:
            df = fetch(code, count)
        except Exception as e:
            print(f"download {code} failed: {e}")
            df = None
        if df is None or len(df) == 0:
            failed.append(code)
        else:
            cache.save(code, df)
        if i % 25 == 0:
            print(f"downloaded {i}/{len(codes)}")
        sleep(delay_s)
    return failed


def load_frames(codes, cache, *, min_rows=60):
    """캐시된 일봉을 준비된 프레임으로 읽는다. (프레임 딕셔너리, min_rows 미만이거나 없어서 뺀 코드 목록)."""
    frames, skipped = {}, []
    for code in codes:
        raw = cache.load(code)
        if raw is None or len(raw) < min_rows:
            skipped.append(code)
        else:
            frames[code] = prepare_frame(raw)
    return frames, skipped
