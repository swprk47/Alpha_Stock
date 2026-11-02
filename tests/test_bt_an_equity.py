import numpy as np
import pandas as pd
import pytest

from backtest.analysis.equity import (benchmark_returns, cost_drag, excess_ci, information_ratio, matched_benchmark,
                                      perf, portfolio_daily, trade_daily_factors)
from backtest.simulate import simulate_trade
from bt_helpers import make_frame

FLAT = (10_000, 10_000, 10_000, 10_000, 100_000)


def _frame(day_rows, tail=10):
    last_close = day_rows[-1][3]
    return make_frame([FLAT] * 10 + list(day_rows) + [(last_close,) * 4 + (100_000,)] * tail)


SCENARIOS = {
    "target": [(10_000, 10_100, 9_900, 10_050, 100_000), (10_050, 10_700, 10_000, 10_300, 100_000)],
    "stop": [(10_000, 10_100, 9_900, 10_050, 100_000), (10_050, 10_100, 9_600, 9_800, 100_000)],
    "expire": [(10_000, 10_100, 9_900, 10_020, 100_000)] * 5,
}


@pytest.mark.parametrize("mode", ["close", "next_open"])
@pytest.mark.parametrize("name", list(SCENARIOS))
def test_trade_factors_product_equals_net_return(name, mode):
    frame = _frame(SCENARIOS[name])
    trade = simulate_trade(frame, "X", frame.index[9], mode, slippage_pct=0.1)
    assert trade is not None
    factors = trade_daily_factors(trade, frame)
    assert float(np.prod(factors.to_numpy())) == pytest.approx(1 + trade.net_return_pct / 100, rel=1e-12)
    assert factors.index[-1] == trade.exit_date


def _two_trades():
    f1, f2 = _frame(SCENARIOS["expire"]), _frame(SCENARIOS["expire"])
    t1 = simulate_trade(f1, "A", f1.index[9], "close")
    t2 = simulate_trade(f2, "B", f2.index[11], "close")
    return [t1, t2], {"A": f1, "B": f2}, f1


def test_portfolio_equal_weight_of_open_positions():
    trades, frames, f1 = _two_trades()
    daily = portfolio_daily(trades, frames, list(f1.index))
    both = [d for d in f1.index if d in trade_daily_factors(trades[0], frames["A"]).index
            and d in trade_daily_factors(trades[1], frames["B"]).index]
    assert both
    d = both[0]
    expected = ((trade_daily_factors(trades[0], frames["A"])[d] - 1) + (trade_daily_factors(trades[1], frames["B"])[d] - 1)) / 2
    assert daily.loc[d, "ret"] == pytest.approx(expected)
    assert daily.loc[d, "invested"]


def test_portfolio_cash_day_is_zero_and_not_invested():
    trades, frames, f1 = _two_trades()
    daily = portfolio_daily(trades, frames, list(f1.index))
    assert daily.loc[f1.index[0], "ret"] == 0.0 and not daily.loc[f1.index[0], "invested"]
    assert daily.loc[f1.index[-1], "ret"] == 0.0 and not daily.loc[f1.index[-1], "invested"]
    assert len(daily) == len(f1)


def test_perf_known_values():
    ret = pd.Series([0.001] * 252)
    out = perf(ret, pd.Series([True] * 126 + [False] * 126))
    assert out["ann_return"] == pytest.approx(1.001 ** 252 - 1)
    assert out["max_drawdown"] == 0.0
    assert out["sharpe"] is None                              # 분산이 0 이면 샤프를 정의할 수 없다
    assert out["exposure"] == 0.5 and out["n_days"] == 252
    alt = perf(pd.Series([0.01, -0.01] * 126))
    assert alt["sharpe"] == pytest.approx(np.mean([0.01, -0.01] * 126) / np.std([0.01, -0.01] * 126, ddof=1) * np.sqrt(252))
    assert alt["exposure"] is None


def test_max_drawdown_from_peak():
    assert perf(pd.Series([0.10, -0.20, 0.05]))["max_drawdown"] == pytest.approx(-0.20)
    assert perf(pd.Series([-0.10, 0.02]))["max_drawdown"] == pytest.approx(-0.10)      # 시작 값 1 이 첫 고점이다


def test_matched_benchmark_zero_on_cash_days():
    dates = pd.bdate_range("2026-01-05", periods=4)
    bench = pd.Series([0.01, 0.02, -0.01, 0.03], index=dates)
    invested = pd.Series([True, False, True, False], index=dates)
    assert list(matched_benchmark(bench, invested)) == [0.01, 0.0, -0.01, 0.0]


def test_benchmark_returns_from_close():
    frame = make_frame([(100, 100, 100, 100, 1), (100, 110, 100, 110, 1), (110, 110, 99, 99, 1)])
    out = benchmark_returns(frame, list(frame.index) + [pd.Timestamp("2030-01-01")])
    assert list(out) == pytest.approx([0.0, 0.10, -0.10, 0.0])


def test_information_ratio_none_when_identical():
    ret = pd.Series([0.01, -0.02, 0.03])
    assert information_ratio(ret, ret.copy()) is None
    assert information_ratio(ret, ret - 0.001 * np.array([1, 2, 3])) is not None


def test_excess_ci_positive_when_always_better():
    rng = np.random.default_rng(0)
    base = pd.Series(rng.normal(0, 0.01, 400))
    res = excess_ci(base + 0.002, base, draws=200)
    assert res.point == pytest.approx(0.002) and res.lo > 0


def test_cost_drag_positive():
    frame = _frame(SCENARIOS["target"])
    trades = [simulate_trade(frame, "X", frame.index[9], mode, slippage_pct=0.1) for mode in ("close", "next_open")]
    out = cost_drag(trades)
    assert out["gross_mean_pct"] > out["net_mean_pct"]
    assert out["drag_pct"] == pytest.approx(out["gross_mean_pct"] - out["net_mean_pct"])


def test_equity_empty_inputs():
    frame = _frame(SCENARIOS["expire"])
    daily = portfolio_daily([], {"A": frame}, list(frame.index))
    assert (daily["ret"] == 0.0).all() and not daily["invested"].any()
    cash = perf(daily["ret"], daily["invested"])
    assert cash["ann_return"] == 0.0 and cash["exposure"] == 0.0
    none = perf(pd.Series(dtype=float))
    assert none["ann_return"] is None and none["max_drawdown"] is None and none["sharpe"] is None and none["n_days"] == 0
    assert cost_drag([])["drag_pct"] is None
