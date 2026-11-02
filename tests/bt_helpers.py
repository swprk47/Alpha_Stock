"""백테스트 테스트용 도우미: 손으로 만든 일봉 프레임."""
import pandas as pd

from backtest.data import Listing, prepare_frame
from backtest.simulate import Trade


def make_raw(rows, start="2026-01-05"):
    """rows 는 (open, high, low, close, volume) 튜플 목록. 날짜는 start 부터 영업일."""
    dates = pd.bdate_range(start, periods=len(rows))
    df = pd.DataFrame(list(rows), columns=["open", "high", "low", "close", "volume"])
    df.insert(0, "date", dates)
    return df


def make_frame(rows, start="2026-01-05"):
    return prepare_frame(make_raw(rows, start))


def flat_rows(n, price=10_000, volume=100_000):
    return [(price, price, price, price, volume)] * n


def one(close, volume, n=3):
    """같은 값의 일봉 n개짜리 프레임(마지막 날짜가 DATE)."""
    return make_frame([(close, close, close, close, volume)] * n)


def listing(codes):
    return [Listing(c, c, "KOSPI", i) for i, c in enumerate(codes)]


DATE = one(10_000, 1).index[-1]


def trending_rows(n):
    """완만한 상승과 눌림이 반복되는 일봉 n개. 앱의 analyze_stock_for_swing 점수가 80(RSI 약 58)이 되도록 맞춘 값."""
    rows, close = [], 10_000
    pattern = [60, -40, 50, -45, 55, -35]
    for i in range(n):
        new = close + pattern[i % len(pattern)]
        rows.append((close, max(close, new) + 20, min(close, new) - 20, new, 100_000))
        close = new
    return rows


def make_trade(net, reason="target", signal_date="2026-01-05", score=65, code="X", entry_mode="close",
               bucket=100_000, held_days=3):
    """지표 테스트용 Trade. 진입일 = 신호일, 청산일 = 신호일 + held_days 일."""
    d = pd.Timestamp(signal_date)
    return Trade(code, bucket, entry_mode, d, d, d + pd.Timedelta(days=held_days), 10_000, 10_000,
                 reason, float(net), held_days, score)


def sample_results():
    """보고서 테스트용: 거래 5건 시나리오 하나, 빈 시나리오 하나, 받기 실패 종목 BAD1."""
    from backtest.metrics import CheckItem, ControlSummary, SensRow, by_score_band, by_year, summarize
    from backtest.report import DataQuality, RunResults, ScenarioResult

    trades = [make_trade(n, r, d, score=sc) for n, r, d, sc in [
        (6.0, "target", "2025-01-06", 65), (-3.2, "stop", "2025-02-03", 60), (6.0, "target", "2026-01-05", 70),
        (-3.2, "stop", "2026-01-12", 62), (0.5, "expire", "2026-01-19", 66)]]
    full = summarize(trades)
    filled = ScenarioResult(
        bucket=100_000, entry_mode="close", summary=full, all_passes_summary=full, yearly=by_year(trades),
        bands=by_score_band(trades), states={"up": full, "down": summarize([])}, excess_pct=1.5,
        control=ControlSummary(4.0, 0.3, 0.5), sensitivity=[SensRow(6.5, 3.0, 5, 0.0, 5, 1.22)],
        checklist=[CheckItem("거래 100건 이상", False, "5건")], trades=trades)
    empty = summarize([])
    blank = ScenarioResult(
        bucket=100_000, entry_mode="next_open", summary=empty, all_passes_summary=empty, yearly={},
        bands=by_score_band([]), states={"up": empty, "down": empty}, excess_pct=None,
        control=ControlSummary(0.0, None, None), sensitivity=[SensRow(6.5, 3.0, 5, 0.0, 0, None)],
        checklist=[CheckItem("거래 100건 이상", False, "0건")], trades=[])
    quality = DataQuality(n_listed=300, n_with_data=298, failed=["BAD1"], skipped_short=["S1"],
                          excluded_days={"A": 12}, first_date="2014-08-07", last_date="2026-11-02")
    return RunResults("2026-11-02 14:00", [filled, blank], quality)
