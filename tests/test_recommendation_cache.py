"""예산 구간별 추천 캐시. 네트워크 호출 없음(조회 함수를 주입/모킹)."""
import threading
import time

import pytest

import recommendation_cache as rc
from conftest import login


# ---- 구간 ----
@pytest.mark.parametrize("budget,expected", [
    (10_000, 10_000), (19_999, 10_000), (20_000, 20_000), (49_999, 20_000),
    (50_000, 50_000), (99_999, 50_000), (100_000, 100_000), (199_999, 100_000),
    (490_000, 200_000), (1_000_000, 1_000_000), (9_999_999, 5_000_000),
    (10_000_000, 10_000_000), (999_999_999, 10_000_000),
])
def test_budget_bucket_boundaries(budget, expected):
    assert rc.budget_bucket(budget) == expected


@pytest.mark.parametrize("budget", [9_999, 1, 0, -5])
def test_budget_below_minimum_uses_smallest_bucket(budget):
    assert rc.budget_bucket(budget) == 10_000


# ---- 캐시 ----
class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make_cache(ttl=300):
    calls = []
    clock = Clock()

    def compute(bucket_budget):
        calls.append(bucket_budget)
        return [{"code": f"R{bucket_budget}"}]

    return rc.RecommendationCache(compute, ttl=ttl, clock=clock), calls, clock


def test_different_buckets_are_cached_separately():
    cache, calls, _ = make_cache()
    a = cache.get(100_000)
    b = cache.get(1_000_000)
    assert calls == [100_000, 1_000_000]
    assert a.recs[0]["code"] == "R100000" and b.recs[0]["code"] == "R1000000"
    assert (a.bucket, b.bucket) == (100_000, 1_000_000)


def test_same_bucket_is_reused_within_ttl():
    cache, calls, clock = make_cache()
    cache.get(100_000)
    clock.t += 299
    r = cache.get(150_000)  # 같은 구간(10만~20만 미만)
    assert calls == [100_000]
    assert r.from_cache is True


def test_expired_entry_is_recomputed():
    cache, calls, clock = make_cache()
    cache.get(100_000)
    clock.t += 301
    r = cache.get(100_000)
    assert calls == [100_000, 100_000]
    assert r.from_cache is False


def test_force_bypasses_ttl():
    cache, calls, _ = make_cache()
    cache.get(100_000)
    cache.get(100_000, force=True)
    assert calls == [100_000, 100_000]


def test_force_refreshes_only_that_bucket():
    cache, calls, _ = make_cache()
    cache.get(100_000)
    cache.get(1_000_000)
    cache.get(100_000, force=True)
    assert calls == [100_000, 1_000_000, 100_000]


def test_updated_at_is_the_compute_time():
    cache, _, clock = make_cache()
    first = cache.get(100_000)
    clock.t += 100
    again = cache.get(100_000)
    assert first.updated_at == again.updated_at == 1000.0


def test_failure_returns_stale_result_for_that_bucket_only():
    clock = Clock()
    state = {"fail": False}

    def compute(b):
        if state["fail"] and b == 100_000:
            raise RuntimeError("naver down")
        return [{"code": f"R{b}"}]

    cache = rc.RecommendationCache(compute, ttl=300, clock=clock)
    cache.get(100_000)
    cache.get(1_000_000)
    clock.t += 400
    state["fail"] = True
    stale = cache.get(100_000)
    assert stale.recs == [{"code": "R100000"}] and stale.updated_at == 1000.0
    other = cache.get(1_000_000)  # 다른 구간은 정상 갱신
    assert other.updated_at == 1400.0


def test_first_failure_returns_empty_without_raising():
    def compute(b):
        raise RuntimeError("down")

    r = rc.RecommendationCache(compute, clock=Clock()).get(100_000)
    assert r.recs == [] and r.updated_at == 0


def test_concurrent_requests_for_one_bucket_compute_once():
    calls = []

    def slow(b):
        calls.append(b)
        time.sleep(0.2)
        return [{"code": "X"}]

    cache = rc.RecommendationCache(slow)
    threads = [threading.Thread(target=cache.get, args=(100_000,)) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert calls == [100_000]


# ---- 요청 예산으로 수량 재계산 ----
def rec(code, price, score):
    return {"code": code, "current_price": price, "score": score,
            "sizing": {"recommended_quantity": 1, "total_cost": price, "budget_ratio_pct": 0}}


def test_sizing_is_recomputed_for_the_exact_budget():
    # 구간 하한(20만)으로 캐시된 종목을 현금 49만 사용자가 볼 때: 수량이 49만 기준이어야 한다
    out = rc.recs_for_budget([rec("A", 30_500, 90)], 490_000)
    s = out[0]["sizing"]
    assert s["recommended_quantity"] == 8
    assert s["total_cost"] == 244_000
    assert s["budget_ratio_pct"] == 49.8


def test_items_above_the_budget_are_dropped():
    out = rc.recs_for_budget([rec("A", 150_000, 90), rec("B", 30_500, 80)], 100_000)
    assert [r["code"] for r in out] == ["B"]


def test_result_is_sliced_to_top_n_keeping_order():
    recs = [rec(c, 10_000, s) for c, s in [("A", 90), ("B", 80), ("C", 70), ("D", 60)]]
    out = rc.recs_for_budget(recs, 100_000, top_n=3)
    assert [r["code"] for r in out] == ["A", "B", "C"]


def test_original_recs_are_not_mutated():
    original = rec("A", 30_500, 90)
    rc.recs_for_budget([original], 490_000)
    assert original["sizing"]["recommended_quantity"] == 1


# ---- API ----
@pytest.fixture
def api(client, monkeypatch):
    import server
    calls = []

    def fake_recommendations(cands, provider, budget=100_000, top_n=3):
        calls.append(budget)
        return [rec("005930", 30_500, 90), rec("0183J0", 7_600, 80)]

    monkeypatch.setattr(server, "get_market_candidate_stocks", lambda **kw: [{"code": "x"}])
    monkeypatch.setattr(server, "get_recommendations", fake_recommendations)
    monkeypatch.setattr(server, "get_stock_daily_candles", lambda code, count=60: None)
    monkeypatch.setattr(server, "rec_cache", rc.RecommendationCache(server._compute_bucket))
    monkeypatch.setattr(server, "forced_at", {})
    client.compute_calls = calls
    return client


def test_api_returns_sizing_for_the_requested_budget(api):
    r = api.get("/api/recommendations?budget=490000").json()
    assert r["budget_bucket"] == 200_000
    first = r["recommendations"][0]
    assert first["sizing"]["recommended_quantity"] == 8  # 49만 기준 (캐시는 20만 기준으로 계산됨)
    assert api.compute_calls == [200_000]


def test_api_budgets_in_different_buckets_compute_separately(api):
    api.get("/api/recommendations?budget=100000")
    api.get("/api/recommendations?budget=1000000")
    api.get("/api/recommendations?budget=150000")  # 첫 번째와 같은 구간 → 재사용
    assert api.compute_calls == [100_000, 1_000_000]


@pytest.mark.parametrize("budget", [10_000, 20_000])
def test_api_keeps_only_items_affordable_with_the_budget(api, budget):
    # 30,500원 종목은 이 예산으로 1주도 못 사므로 빠지고, 7,600원 종목만 남는다
    r = api.get(f"/api/recommendations?budget={budget}").json()
    assert [x["code"] for x in r["recommendations"]] == ["0183J0"]


def test_api_refresh_429_tells_remaining_seconds(api, monkeypatch):
    import config
    monkeypatch.setattr(config, "REFRESH_MIN_INTERVAL", 60)
    login(api)
    assert api.get("/api/recommendations?refresh=true").status_code == 200
    r = api.get("/api/recommendations?refresh=true")
    assert r.status_code == 429
    assert "초" in r.json()["detail"]
    assert 1 <= int(r.headers["Retry-After"]) <= 60


def test_api_budget_change_style_request_is_not_rate_limited(api):
    # 예산 변경 뒤에는 강제 갱신이 아니라 일반 조회를 하므로 429 가 나지 않는다
    login(api)
    api.get("/api/recommendations?refresh=true&budget=100000")
    for budget in (100_000, 1_000_000, 50_000, 3_000_000):
        assert api.get(f"/api/recommendations?budget={budget}").status_code == 200
