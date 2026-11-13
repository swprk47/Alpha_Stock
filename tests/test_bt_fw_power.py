"""필요 기간 추정 테스트 (기댓값은 손으로 계산)."""
import pytest

from backtest.forward.power import (EFFECTS_ANNUAL, effective_sd, episodes_per_year,
                                    required_months, required_table)
from backtest.forward.stats import Episode, Stat


def test_required_months_formula():
    # (2.801585 * 0.01 / 0.0025) ** 2 = 11.20634 ** 2 = 125.58 -> 올림 126
    assert required_months(0.01, 0.03) == 126
    assert isinstance(required_months(0.01, 0.03), int)


def test_required_months_zero_sd_and_bad_effect():
    assert required_months(0.0, 0.03) == 0
    with pytest.raises(ValueError):
        required_months(0.01, 0.0)
    with pytest.raises(ValueError):
        required_months(0.01, -0.02)


def test_required_months_falls_as_effect_grows():
    months = [required_months(0.01, e) for e in EFFECTS_ANNUAL]
    assert months == sorted(months, reverse=True)
    assert len(set(months)) == len(months)
    # 효과 1% 는 3% 의 9배 제곱 관계: 1130.6 -> 1131
    assert months[0] == 1131


def test_effective_sd_inverts_standard_error():
    assert effective_sd(Stat(0.0, -0.01, 0.01, 0.5, 0.002, 100)) == pytest.approx(0.02)


def test_effective_sd_rejects_empty_stat():
    with pytest.raises(ValueError):
        effective_sd(Stat(None, None, None, None, None, 0))
    with pytest.raises(ValueError):
        effective_sd(Stat(0.0, 0.0, 0.0, 0.5, None, 10))


def test_required_table_has_all_effect_sizes():
    table = required_table(Stat(0.0, -0.01, 0.01, 0.5, 0.001, 100))  # sd = 0.01
    assert list(table) == [0.01, 0.02, 0.03, 0.05]
    assert table[0.03] == 126
    assert table[0.01] == 1131
    assert table[0.02] == 283   # 282.65 -> 283
    assert table[0.05] == 46    # 45.23 -> 46


def test_episodes_per_year():
    eps = [Episode(0, 1, 2, -0.1)] * 3
    assert episodes_per_year(eps, 2520) == pytest.approx(0.3)
    assert episodes_per_year(eps, 0) == 0.0
