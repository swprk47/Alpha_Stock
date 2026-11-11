"""월 단위 엔진 테스트: 기대값은 모두 손으로 계산한다(엔진 호출로 만들지 않는다)."""
import pandas as pd
import pytest

from backtest.forward.costs import CostModel
from backtest.forward.engine import PortfolioResult, monthly_returns, run_portfolio
from tests.bt_fw_helpers import frame_from_closes, frame_from_rows

CM = CostModel()
B = CM.buy_rate()


def cal(n, start="2020-01-01"):
    return pd.bdate_range(start, periods=n)


def S(day):
    return CM.sell_rate(day, etf=False)


def test_buy_and_hold_single_stock_pays_buy_cost_once():
    # 시가→종가 +1%, 이후 종가도 매일 +1%
    frames = {"A": frame_from_rows([(100, 101), (101, 102.01), (102.01, 103.0301)])}
    c = cal(3)
    r = run_portfolio(frames, c, {c[0]: {"A": 1.0}}, CM, start=c[0], end=c[-1])
    assert isinstance(r, PortfolioResult)
    assert r.daily.iloc[0] == pytest.approx((1 - B) * 1.01 - 1)
    assert r.daily.iloc[1] == pytest.approx(0.01)
    assert r.daily.iloc[2] == pytest.approx(0.01)
    assert list(r.turnover.index) == [c[0]]
    assert r.turnover[c[0]] == pytest.approx(1.0)
    assert r.cost[c[0]] == pytest.approx(B)


def test_equal_weight_rebalance_turnover_and_cost():
    frames = {"A": frame_from_closes([100, 200, 200]), "B": frame_from_closes([100, 100, 100])}
    c = cal(3)
    tg = {c[0]: {"A": 0.5, "B": 0.5}, c[2]: {"A": 0.5, "B": 0.5}}
    r = run_portfolio(frames, c, tg, CM, start=c[0], end=c[-1])
    # d0 후 각 0.5k (k=1-B); A 두 배 → A=k, B=0.5k, V=1.5k; 목표 각 0.75k → A 0.25k 매도, B 0.25k 매수
    assert r.turnover[c[2]] == pytest.approx(0.25 / 1.5)
    assert r.cost[c[2]] == pytest.approx((0.25 * B + 0.25 * S(c[2])) / 1.5)
    assert r.turnover[c[0]] == pytest.approx(1.0)


def test_move_to_cash_and_back():
    frames = {"A": frame_from_closes([100, 110, 120, 130, 140])}
    c = cal(5)
    tg = {c[0]: {"A": 1.0}, c[1]: {}, c[3]: {"A": 1.0}}
    r = run_portfolio(frames, c, tg, CM, start=c[0], end=c[-1])
    k = 1 - B
    assert r.daily.iloc[0] == pytest.approx(k - 1)
    # d1: A는 1.1배가 된 뒤 전량 매도 → V = 1.1k(1-s)
    assert r.daily.iloc[1] == pytest.approx(1.1 * (1 - S(c[1])) - 1)
    assert r.turnover[c[1]] == pytest.approx(1.0)
    assert r.cost[c[1]] == pytest.approx(S(c[1]))
    assert r.daily.iloc[2] == 0.0
    # d3: 현금 전액 매수 → 매수 비용만큼 줄어든다(130→130 시가=종가)
    assert r.daily.iloc[3] == pytest.approx(-B)
    assert r.turnover[c[3]] == pytest.approx(1.0)
    assert r.daily.iloc[4] == pytest.approx(140 / 130 - 1)


def test_etf_sell_has_no_tax():
    frames = {"A": frame_from_closes([100, 100, 100])}
    c = cal(3)
    tg = {c[0]: {"A": 1.0}, c[1]: {}}
    plain = run_portfolio(frames, c, tg, CM, start=c[0], end=c[-1])
    etf = run_portfolio(frames, c, tg, CM, start=c[0], end=c[-1], etf_codes={"A"})
    sell_etf = CM.sell_rate(c[1], etf=True)
    assert etf.cost[c[1]] == pytest.approx(sell_etf)
    assert plain.cost[c[1]] == pytest.approx(S(c[1]))
    assert plain.cost[c[1]] - etf.cost[c[1]] == pytest.approx(0.0025)   # 2020년 매도세 0.25%
    assert etf.daily.iloc[1] == pytest.approx(-sell_etf)


def test_halted_stock_is_frozen_and_others_fill_the_rest():
    frames = {
        "A": frame_from_rows([(100, 100), (100, 100, 0), (200, 200)]),
        "B": frame_from_closes([100, 100, 100]),
        "C": frame_from_closes([100, 100, 100]),
    }
    c = cal(3)
    third = 1 / 3
    tg = {c[0]: {"A": 0.5, "B": 0.5}, c[1]: {"A": third, "B": third, "C": third}}
    r = run_portfolio(frames, c, tg, CM, start=c[0], end=c[-1])
    # d1: V=k, A 묶임 0.5k; B·C 목표 = 0.5k*1*(1/3)/(2/3)=0.25k → B 0.25k 매도, C 0.25k 매수
    assert r.turnover[c[1]] == pytest.approx(0.25)
    assert r.cost[c[1]] == pytest.approx(0.25 * (B + S(c[1])))
    # d2: A가 두 배 → A는 d1 이후에도 전체의 절반 → 일간 수익률 +50%
    assert r.daily.iloc[2] == pytest.approx(0.5)


def test_missing_row_for_held_stock_does_not_crash():
    a = frame_from_closes([100, 100, 200, 200])
    a = a.drop(a.index[1])                       # d1에는 A 행이 없다
    frames = {"A": a, "B": frame_from_closes([100, 100, 100, 100])}
    c = cal(4)
    r = run_portfolio(frames, c, {c[0]: {"A": 0.5, "B": 0.5}}, CM, start=c[0], end=c[-1])
    assert r.daily.iloc[1] == 0.0                # A 가치 그대로, B 그대로
    assert r.daily.iloc[2] == pytest.approx(0.5)  # A는 마지막 가격 100 대비 두 배, 비중 절반
    assert r.daily.iloc[3] == 0.0                # 상장폐지로 오인해 팔지 않았다


def test_delisted_stock_is_sold_at_last_close():
    frames = {"A": frame_from_closes([100, 120]), "B": frame_from_closes([100] * 4)}
    c = cal(4)
    r = run_portfolio(frames, c, {c[0]: {"A": 0.5, "B": 0.5}}, CM, start=c[0], end=c[-1])
    k = 1 - B
    assert r.daily.iloc[1] == pytest.approx(0.1)   # 마지막 거래일에는 아직 보유: (0.6k+0.5k)/k-1
    # d2: A 0.6k를 팔아 현금 0.6k(1-s); 전날 V = 1.1k
    assert r.daily.iloc[2] == pytest.approx((0.6 * (1 - S(c[2])) + 0.5) / 1.1 - 1)
    assert r.daily.iloc[3] == 0.0                  # 보유에서 빠졌으므로 다시 팔지 않는다


def test_cost_multiplier_scales_costs():
    frames = {"A": frame_from_closes([100, 100])}
    c = cal(2)
    tg = {c[0]: {"A": 1.0}}
    one = run_portfolio(frames, c, tg, CostModel(1.0), start=c[0], end=c[-1])
    two = run_portfolio(frames, c, tg, CostModel(2.0), start=c[0], end=c[-1])
    assert one.cost[c[0]] == pytest.approx(B)
    assert two.cost[c[0]] == pytest.approx(2 * B)
    assert two.daily.iloc[0] == pytest.approx(-2 * B)


def test_days_before_first_target_are_cash():
    frames = {"A": frame_from_closes([100, 110, 121])}
    c = cal(3)
    r = run_portfolio(frames, c, {c[1]: {"A": 1.0}}, CM, start=c[0], end=c[-1])
    assert len(r.daily) == 3
    assert r.daily.iloc[0] == 0.0
    assert list(r.turnover.index) == [c[1]]


def test_monthly_returns_compound_between_trade_days():
    c = cal(5)
    daily = pd.Series([0.01] * 5, index=c)
    m = monthly_returns(daily, [c[0], c[3]])
    assert list(m.index) == [c[0]]
    assert m.iloc[0] == pytest.approx(1.01 ** 3 - 1)
