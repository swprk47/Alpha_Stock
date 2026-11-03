from backtest.improve.judge import Verdict, judge_candidate, no_candidates_verdict
from backtest.improve.stats import Stat


def _s(point, p=0.001):
    return Stat(point, None, None, p, 0.1, 100, 1000)


def _judge(trade, kodex, base, cash, n=1, **kw):
    return judge_candidate(trade, kodex, base, cash, n, pre_exposed=kw.pop("pre_exposed", False), **kw)


def test_pass_needs_both_trade_mean_and_vs_kodex():
    assert _judge(_s(0.3), _s(0.2), _s(0.1), _s(0.1)).label == "합격"
    only_trade = _judge(_s(0.3), _s(0.2, p=0.3), _s(0.1, p=0.3), _s(0.1))
    only_kodex = _judge(_s(0.3, p=0.3), _s(0.2), _s(0.1, p=0.3), _s(0.1))
    assert only_trade.label != "합격" and only_kodex.label != "합격"


def test_pass_uses_bonferroni_threshold():
    kwargs = dict(base=_s(0.1, p=0.9), cash=_s(0.1))
    at_four = _judge(_s(0.3, p=0.02), _s(0.2, p=0.02), kwargs["base"], kwargs["cash"], n=4)
    at_one = _judge(_s(0.3, p=0.02), _s(0.2, p=0.02), kwargs["base"], kwargs["cash"], n=1)
    assert at_four.label != "합격" and at_one.label == "합격"
    assert at_four.flags["alpha_adj"] == 0.05 / 4 and at_one.flags["alpha_adj"] == 0.05


def test_negative_point_is_never_significant():
    result = _judge(_s(-0.3, p=0.0001), _s(-0.2, p=0.0001), _s(-0.1, p=0.0001), _s(-0.1))
    assert result.label == "불합격"


def test_promising_requires_positive_trade_mean_and_cash_edge():
    base_sig = _s(0.1)                                                    # 기준선 대비는 유의
    promising = _judge(_s(0.3, p=0.4), _s(0.2, p=0.4), base_sig, _s(0.1))
    assert promising.label == "유망"
    negative_trade = _judge(_s(-0.1, p=0.4), _s(0.2, p=0.4), base_sig, _s(0.1))
    assert negative_trade.label == "불합격"


def test_candidate_worse_than_cash_is_not_promising():
    result = _judge(_s(0.3, p=0.4), _s(0.2, p=0.4), _s(0.1), _s(-0.05))   # 기준선보다는 낫지만 현금보다 나쁘다
    assert result.label == "불합격"


def test_near_threshold_flag_does_not_change_label():
    near = _judge(_s(0.3, p=0.05 * 1.1), _s(0.2, p=0.001), _s(0.1, p=0.9), _s(0.1), n=1)    # 문턱 0.05 의 +10%: 경계지만 통과하지 못한다
    assert near.flags["near_threshold"]["trade_mean"] is True
    assert near.label == "불합격"
    inside = _judge(_s(0.3, p=0.05 * 0.9), _s(0.2, p=0.001), _s(0.1, p=0.9), _s(0.1), n=1)  # 문턱의 -10%: 경계이고 통과
    assert inside.flags["near_threshold"]["trade_mean"] is True and inside.label == "합격"


def test_flags_carry_pre_exposed_and_dividend_sensitivity():
    result = _judge(_s(0.3), _s(0.2), _s(0.1), _s(0.1), pre_exposed=True, dividend_sensitive=True)
    assert isinstance(result, Verdict)
    assert result.flags["pre_exposed"] is True and result.flags["dividend_sensitive"] is True
    assert result.flags["p_trade_mean"] == 0.001


def test_no_candidates_verdict_text():
    assert no_candidates_verdict() == "개선 후보 없음"
