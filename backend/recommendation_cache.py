"""
recommendation_cache.py
예산 구간별 추천 캐시.

- 예산을 1-2-5 간격 구간으로 묶어 구간마다 한 번만 계산하고 TTL 동안 공유한다.
- 구간 계산은 그 구간의 **하한 예산**으로 한다. 하한으로 살 수 있는 종목은 구간 안 어떤 예산으로도 살 수 있다.
- 수량·비중(sizing)은 예산에 따라 달라지므로 요청마다 **요청 예산으로 다시 계산**한다(네트워크 없음).
- strategy.py 는 수정하지 않고 calculate_position_sizing 만 호출한다.
"""
import threading
import time
from typing import Callable, NamedTuple

from strategy import calculate_position_sizing

# 구간 하한 (원). 1-2-5 간격이라 하한과 실제 예산의 차이가 최대 2.5배다.
BUCKETS = (10_000, 20_000, 50_000, 100_000, 200_000, 500_000,
           1_000_000, 2_000_000, 5_000_000, 10_000_000)

CACHE_TTL_SECONDS = 300
CACHE_TOP_N = 10   # 구간 캐시에 보관하는 후보 수 (요청마다 예산으로 걸러 3개를 돌려준다)


def budget_bucket(budget: int) -> int:
    """예산이 속한 구간의 하한. 최소 구간보다 작으면 최소 구간."""
    found = BUCKETS[0]
    for b in BUCKETS:
        if budget >= b:
            found = b
    return found


class CacheResult(NamedTuple):
    recs: list
    updated_at: float   # 마지막으로 계산에 성공한 시각(epoch). 한 번도 없으면 0
    bucket: int
    from_cache: bool


class RecommendationCache:
    def __init__(self, compute: Callable[[int], list], ttl: int = CACHE_TTL_SECONDS,
                 clock: Callable[[], float] = time.time):
        self._compute = compute
        self._ttl = ttl
        self._clock = clock
        self._entries: dict = {}   # bucket -> {"recs": list, "updated": float}
        self._locks: dict = {}     # bucket -> Lock (같은 구간 동시 요청은 한 번만 계산)
        self._guard = threading.Lock()

    def _lock_for(self, bucket: int) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(bucket, threading.Lock())

    def get(self, budget: int, force: bool = False) -> CacheResult:
        bucket = budget_bucket(budget)
        with self._lock_for(bucket):
            now = self._clock()
            entry = self._entries.get(bucket)
            if entry and not force and now - entry["updated"] < self._ttl:
                return CacheResult(entry["recs"], entry["updated"], bucket, True)
            try:
                recs = self._compute(bucket)
            except Exception as e:  # 시세 조회 실패 등: 그 구간의 이전 결과를 유지한다
                print(f"Error updating recommendations (bucket {bucket}): {e}")
                if entry:
                    return CacheResult(entry["recs"], entry["updated"], bucket, True)
                return CacheResult([], 0, bucket, False)
            self._entries[bucket] = {"recs": recs, "updated": now}
            return CacheResult(recs, now, bucket, False)


def recs_for_budget(recs: list, budget: int, top_n: int = 3) -> list:
    """캐시된 추천을 요청 예산 기준으로 다시 계산해 돌려준다. 원본은 바꾸지 않는다.
    이 예산으로 1주도 못 사는 종목(sizing 이 None)은 제외하고 점수 순서를 유지한 채 top_n 개만 남긴다."""
    out = []
    for r in recs:
        sizing = calculate_position_sizing({"current_price": r["current_price"]}, budget=budget)
        if sizing is None:
            continue
        out.append({**r, "sizing": sizing})
        if len(out) >= top_n:
            break
    return out
