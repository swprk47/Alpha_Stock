import pytest

from bt_helpers import make_trade
from backtest.metrics import by_score_band, by_year, summarize


def test_summary_hand_computed():
    ts = [make_trade(n, r, d) for n, r, d in [(6.0, "target", "2026-01-05"), (-3.2, "stop", "2026-01-06"),
          (6.0, "target", "2026-01-07"), (-3.2, "stop", "2026-01-08"), (0.5, "expire", "2026-01-09")]]
    s = summarize(ts)
    assert s.n == 5 and s.win_rate == pytest.approx(0.6)
    assert (s.target_rate, s.stop_rate, s.expire_rate) == (pytest.approx(0.4),) * 2 + (pytest.approx(0.2),)
    assert s.expectancy_pct == pytest.approx(1.22) and s.avg_win_pct == pytest.approx(4.1667, abs=1e-3)
    assert s.avg_loss_pct == pytest.approx(-3.2) and s.profit_factor == pytest.approx(1.953125)
    assert s.max_drawdown_pct == pytest.approx(3.2) and s.max_loss_streak == 1


def test_empty_trades_summary_has_no_division_errors():
    s = summarize([])
    assert s.n == 0 and s.expectancy_pct is None and s.profit_factor is None and s.max_drawdown_pct == 0
    assert (s.target_rate, s.stop_rate, s.expire_rate, s.win_rate) == (0.0, 0.0, 0.0, 0.0)


def test_all_wins_has_no_profit_factor():
    s = summarize([make_trade(2.0), make_trade(3.0, signal_date="2026-01-06")])
    assert s.profit_factor is None and s.avg_loss_pct is None and s.max_loss_streak == 0


def test_loss_streak_counts_consecutive_losses():
    nets = [-1, -1, -1, 1, -1]
    ts = [make_trade(n, signal_date=f"2026-01-{5 + i:02d}") for i, n in enumerate(nets)]
    assert summarize(ts).max_loss_streak == 3


def test_by_year_and_by_score_band_keys():
    ts = [make_trade(1.0, signal_date="2025-03-03"), make_trade(1.0, signal_date="2026-03-03")]
    assert set(by_year(ts)) == {2025, 2026}
    scored = [make_trade(1.0, score=s, signal_date=f"2026-02-{2 + i:02d}") for i, s in enumerate([60, 64, 65, 69, 70, 85])]
    assert {k: v.n for k, v in by_score_band(scored).items()} == {"60-64": 2, "65-69": 2, "70+": 2}
