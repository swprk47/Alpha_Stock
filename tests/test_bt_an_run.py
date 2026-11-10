import json

import pytest

import market_data
from backtest.analysis.report import write_analysis_report
from backtest.analysis.run import AnalysisConfig, load_listing, main, run_analysis
from backtest.data import CandleCache
from bt_helpers import listing, make_raw, trending_rows

CODES = ["A", "B", "C", "D"]
BENCH = "069500"


def _rows(k):
    return [(o * k, h * k, l * k, c * k, 400_000) for o, h, l, c, _ in trending_rows(400)]


def _seed_cache(root, codes=CODES, with_bench=True):
    cache = CandleCache(root)
    for i, code in enumerate(codes, 1):
        cache.save(code, make_raw(_rows(i), start="2021-01-04"))
    if with_bench:
        cache.save(BENCH, make_raw(_rows(1), start="2021-01-04"))
    return cache


def _cfg(tmp_path, **kw):
    base = dict(buckets=(100_000,), cache_dir=tmp_path / "cache", out_dir=tmp_path / "out", draws=40, paths=40, full_pool=False)
    base.update(kw)
    return AnalysisConfig(**base)


@pytest.fixture
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("분석은 일봉을 받으면 안 된다")
    monkeypatch.setattr(market_data, "get_stock_daily_candles", boom)


def test_load_listing_saves_then_reuses(tmp_path):
    calls = []

    def fetch():
        calls.append(1)
        return listing(CODES)

    first = load_listing(tmp_path, fetch)
    second = load_listing(tmp_path, fetch)
    assert first == second == listing(CODES) and len(calls) == 1
    assert (tmp_path / "listing.json").exists()
    load_listing(tmp_path, fetch, refresh=True)
    assert len(calls) == 2


def test_run_analysis_end_to_end_on_synthetic_data(tmp_path, no_network):
    _seed_cache(tmp_path / "cache")
    results = run_analysis(_cfg(tmp_path), fetch_listing=lambda: listing(CODES))
    assert results["data"]["n_frames"] == 5
    scenarios = results["scenarios"]
    assert {(s["bucket"], s["entry_mode"]) for s in scenarios} == {(100_000, "close"), (100_000, "next_open")}
    s = scenarios[0]
    for key in ("factors", "selection", "equity", "cost_drag", "correlation", "risk", "trades"):
        assert key in s
    assert set(s["factors"]["main"]) >= {"gap20", "rsi", "score"}
    assert all(v["verdict"] in ("유의", "순서만 유의", "근거 부족", "불안정", "판정 불가") for v in s["factors"]["main"].values())
    assert all("mean_train" in v and "mean_test" in v for v in s["factors"]["main"].values())
    assert s["trades"] > 0 and set(s["risk"]["horizons"]) == {"21", "63", "252", "756"}
    json.dumps(results)                                                  # JSON 직렬화 가능해야 한다


def test_run_skips_codes_missing_from_cache_without_fetching(tmp_path, no_network):
    _seed_cache(tmp_path / "cache", codes=["A", "B", "C"])
    results = run_analysis(_cfg(tmp_path), fetch_listing=lambda: listing(CODES))
    assert "D" in results["data"]["skipped"]


def test_report_puts_limits_before_results(tmp_path, no_network):
    _seed_cache(tmp_path / "cache")
    results = run_analysis(_cfg(tmp_path), fetch_listing=lambda: listing(CODES))
    write_analysis_report(tmp_path / "out", results)
    text = (tmp_path / "out" / "analysis_report.md").read_text(encoding="utf-8")
    assert text.index("## 한계") < text.index("## 요소별")
    assert "미래를 맞히는 것이 아니라" in text
    assert "순서를 보는" in text                      # 순위상관은 평균 손익의 방향과 다를 수 있다는 해석 주의
    assert "전액을 매일 재투자" in text                # 연환산 수치는 회전율에 크게 좌우된다는 가정 설명
    assert "전날 종가" in text and "내내 이어진다고 가정" in text   # 시장 상태별 위험 분포의 분류 기준과 극단 시나리오 설명
    assert "순서만 유의" in text and "판정 불가" in text            # 판정 라벨 설명
    assert "보정하지 않았다" in text                                # 시나리오 간 다중비교를 보정하지 않았다는 문구
    assert "일 중" in text and "사용" in text                       # 3종목 분석에 쓴 날과 전체 추천일 수
    assert json.loads((tmp_path / "out" / "analysis.json").read_text(encoding="utf-8"))["scenarios"]


def test_report_never_calls_insufficient_evidence_ineffective(tmp_path, no_network):
    _seed_cache(tmp_path / "cache")
    results = run_analysis(_cfg(tmp_path), fetch_listing=lambda: listing(CODES))
    write_analysis_report(tmp_path / "out", results)
    assert "효과 없음" not in (tmp_path / "out" / "analysis_report.md").read_text(encoding="utf-8")


def test_report_handles_scenario_without_trades(tmp_path, no_network):
    _seed_cache(tmp_path / "cache")
    results = run_analysis(_cfg(tmp_path, buckets=(1_000,)), fetch_listing=lambda: listing(CODES))   # 가격 상한 1,000원이라 풀이 비어 있다
    assert all(s["trades"] == 0 for s in results["scenarios"])
    write_analysis_report(tmp_path / "out", results)
    assert "표본 없음" in (tmp_path / "out" / "analysis_report.md").read_text(encoding="utf-8")


def test_cli_writes_report_files(tmp_path, no_network):
    _seed_cache(tmp_path / "cache")
    code = main(["--cache", str(tmp_path / "cache"), "--out", str(tmp_path / "out"), "--buckets", "100000",
                 "--no-full-pool", "--draws", "40", "--paths", "40"], fetch_listing=lambda: listing(CODES))
    assert code == 0
    assert (tmp_path / "out" / "analysis_report.md").exists() and (tmp_path / "out" / "analysis.json").exists()


def test_report_marks_next_open_as_main_and_lists_it_first(tmp_path, no_network):
    _seed_cache(tmp_path / "cache")
    results = run_analysis(_cfg(tmp_path), fetch_listing=lambda: listing(CODES))
    write_analysis_report(tmp_path / "out", results)
    text = (tmp_path / "out" / "analysis_report.md").read_text(encoding="utf-8")
    main_at, confirm_at = text.index("다음날 시가 진입(본 결과)"), text.index("종가 진입(확인용")
    assert main_at < confirm_at                                         # 같은 예산 구간에서 본 결과가 먼저 나온다
    assert text.count("다음날 시가 진입(본 결과)") == text.count("종가 진입(확인용")
