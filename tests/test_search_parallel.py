"""search_stocks: 후보마다 받는 실시간 시세를 병렬로 받는다(예전에는 6개를 차례로 받아 응답이 느렸다).

- 결과 순서는 후보 순서 그대로(먼저 끝난 순서가 아니다)
- 한 종목의 시세가 실패(None)하거나 예외여도 나머지는 그대로 돌려준다(예전에는 예외 하나가 검색 전체를 []로 만들었다)
- 후보가 없으면 시세를 부르지 않고, 후보는 최대 SEARCH_LIMIT 개
- 이 파일은 네트워크 없이 검증한다. 병렬 여부는 시간 측정이 아니라 Barrier 로 확인한다(순차 실행이면 기다리다 실패한다)
"""
import threading

import pytest

import market_data as md
from symbol_index import Symbol


def S(code, name):
    return Symbol(code, name, "KOSPI", "stock", 0)


class FakeIndex:
    def __init__(self, symbols):
        self.symbols = symbols

    def search(self, q, limit):
        return self.symbols[:limit]


def _quote(price):
    return {"code": "x", "current_price": price, "change_rate": 1.0, "change_amount": 10, "logo_url": "", "security_type": "stock"}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(md, "_autocomplete_candidates", lambda q: [])

    def setup(symbols):
        monkeypatch.setattr(md, "symbol_index", FakeIndex(symbols))
    return setup


CODES = ["000001", "000002", "000003", "000004", "000005", "000006"]


def test_quotes_are_fetched_concurrently(env, monkeypatch):
    env([S(c, f"종목{c}") for c in CODES])
    barrier = threading.Barrier(len(CODES), timeout=5)

    def quote(code):
        barrier.wait()  # 여섯 개가 동시에 와야 지나간다. 순차 실행이면 첫 호출이 5초 기다리다 BrokenBarrierError
        return _quote(int(code))

    monkeypatch.setattr(md, "get_realtime_stock_info", quote)
    out = md.search_stocks("종목")
    assert [r["code"] for r in out] == CODES
    assert [r["current_price"] for r in out] == [int(c) for c in CODES]


def test_order_follows_the_candidates_even_when_the_first_quote_finishes_last(env, monkeypatch):
    env([S(c, f"종목{c}") for c in CODES])
    last_done = threading.Event()

    def quote(code):
        if code == CODES[0]:
            assert last_done.wait(5)  # 첫 후보는 마지막 후보가 끝난 뒤에야 끝난다
        else:
            if code == CODES[-1]:
                last_done.set()
        return _quote(int(code))

    monkeypatch.setattr(md, "get_realtime_stock_info", quote)
    assert [r["code"] for r in md.search_stocks("종목")] == CODES


def test_a_failing_or_missing_quote_does_not_break_the_others(env, monkeypatch):
    env([S(c, f"종목{c}") for c in CODES])

    def quote(code):
        if code == "000002":
            raise RuntimeError("network down")
        if code == "000003":
            return None
        return _quote(int(code))

    monkeypatch.setattr(md, "get_realtime_stock_info", quote)
    out = {r["code"]: r for r in md.search_stocks("종목")}
    assert list(out) == CODES  # 여섯 개 모두 돌아온다
    for bad in ("000002", "000003"):  # 시세를 못 받은 종목은 예전과 같은 모양(가격 0, 모름)
        assert out[bad]["current_price"] == 0 and out[bad]["change_rate"] == 0.0 and out[bad]["change_amount"] is None
        assert out[bad]["security_type"] == "" and out[bad]["budget_status"] == "FIT_SPLIT"
        assert out[bad]["logo_url"].endswith(f"Stock{bad}.png")
    assert out["000001"]["current_price"] == 1 and out["000006"]["current_price"] == 6


def test_no_candidates_makes_no_quote_calls(env, monkeypatch):
    env([])
    calls = []
    monkeypatch.setattr(md, "get_realtime_stock_info", lambda code: calls.append(code))
    assert md.search_stocks("없는종목") == [] and calls == []


def test_a_single_candidate_works(env, monkeypatch):
    env([S("000001", "하나")])
    monkeypatch.setattr(md, "get_realtime_stock_info", lambda code: _quote(55_000))
    out = md.search_stocks("하나")
    assert len(out) == 1 and out[0]["budget_status"] == "FIT_SINGLE"


def test_at_most_search_limit_quotes_are_requested(env, monkeypatch):
    env([S(f"{i:06d}", f"종목{i}") for i in range(1, 12)])
    calls = []
    lock = threading.Lock()

    def quote(code):
        with lock:
            calls.append(code)
        return _quote(1)

    monkeypatch.setattr(md, "get_realtime_stock_info", quote)
    out = md.search_stocks("종목")
    assert len(out) == md.SEARCH_LIMIT == len(calls)
