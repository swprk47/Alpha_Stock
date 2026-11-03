import re

from bt_helpers import flat_rows, make_raw
from backtest.data import CandleCache, Listing, download_candles, fetch_listing, load_frames


class _Resp:
    def __init__(self, status, codes):
        self.status_code, self._codes = status, codes

    def json(self):
        return {"stocks": [{"itemCode": c, "stockName": f"n{c}"} for c in self._codes]}


PAGES = {("KOSPI", 1): (200, ["A", "B"]), ("KOSPI", 2): (500, []), ("KOSPI", 3): (200, ["B", "C"]),
         ("KOSDAQ", 1): (200, ["D"]), ("KOSDAQ", 2): (200, []), ("KOSDAQ", 3): (200, [])}


def fake_get(url, headers=None, timeout=None):
    market, page = re.search(r"marketValue/(\w+)\?page=(\d+)&pageSize=50", url).groups()
    return _Resp(*PAGES[(market, int(page))])


def test_listing_order_dedupe_and_page_errors():
    got = fetch_listing(get=fake_get)
    assert [(l.code, l.market, l.rank) for l in got] == [("A", "KOSPI", 0), ("B", "KOSPI", 1), ("C", "KOSPI", 2), ("D", "KOSDAQ", 3)]


def test_cache_roundtrip_and_corrupt_file_is_treated_as_missing(tmp_path):
    cache = CandleCache(tmp_path)
    assert cache.load("A") is None
    cache.save("A", make_raw(flat_rows(5)))
    assert len(cache.load("A")) == 5
    (tmp_path / "B.csv").write_text("garbage,,\n\x00\x01")
    assert cache.load("B") is None
    (tmp_path / "C.csv").write_text("")
    assert cache.load("C") is None


def test_download_skips_cached_reports_failures_and_resumes(tmp_path):
    calls = []

    def fetch(code, count):
        calls.append(code)
        return None if code == "BAD" else make_raw(flat_rows(70))

    run = lambda: download_candles(["A", "BAD", "C"], CandleCache(tmp_path), fetch, delay_s=0, sleep=lambda s: None)
    assert run() == ["BAD"] and calls == ["A", "BAD", "C"]
    calls.clear()
    assert run() == ["BAD"]
    assert calls == ["BAD"]                                  # 이어서 받기: 성공한 종목은 다시 받지 않는다


def test_fetch_exception_counts_as_failure_and_continues(tmp_path):
    def fetch(code, count):
        if code == "X":
            raise RuntimeError("blocked")
        return make_raw(flat_rows(70))

    failed = download_candles(["X", "Y"], CandleCache(tmp_path), fetch, delay_s=0, sleep=lambda s: None)
    assert failed == ["X"] and CandleCache(tmp_path).load("Y") is not None


def test_load_frames_drops_short_histories(tmp_path):
    cache = CandleCache(tmp_path)
    cache.save("A", make_raw(flat_rows(70)))
    cache.save("S", make_raw(flat_rows(30)))
    frames, skipped = load_frames(["A", "S", "MISSING"], cache)
    assert list(frames) == ["A"] and skipped == ["S", "MISSING"]
