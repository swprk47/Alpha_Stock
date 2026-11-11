import datetime as dt
import pytest
from backtest.forward.costs import CostModel, sell_tax_rate

@pytest.mark.parametrize("day, rate", [
    ("2014-08-18", 0.0030), ("2019-05-29", 0.0030), ("2019-05-30", 0.0025), ("2020-12-31", 0.0025),
    ("2021-01-01", 0.0023), ("2022-12-31", 0.0023), ("2023-06-01", 0.0020), ("2024-06-01", 0.0018),
    ("2025-06-01", 0.0015), ("2026-01-01", 0.0020), ("2031-01-01", 0.0020)])
def test_sell_tax_rate_by_trade_date(day, rate):
    assert sell_tax_rate(dt.date.fromisoformat(day)) == pytest.approx(rate)

def test_cost_model_rates_and_multiplier():
    day = dt.date(2024, 6, 3)
    assert CostModel().buy_rate() == pytest.approx(0.00015 + 0.001)
    assert CostModel().sell_rate(day, etf=False) == pytest.approx(0.00015 + 0.0018 + 0.001)
    assert CostModel().sell_rate(day, etf=True) == pytest.approx(0.00015 + 0.001)
    assert CostModel(2.0).sell_rate(day, etf=False) == pytest.approx(2 * (0.00015 + 0.0018 + 0.001))
