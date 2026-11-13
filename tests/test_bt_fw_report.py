"""보고서(report) 테스트: 손으로 만든 JSON 모양 payload로 문구와 순서를 확인한다."""
import re
from pathlib import Path

from backtest.forward import registry
from backtest.forward.report import LIMITS, write_report

SPEC = Path(__file__).resolve().parents[1] / "docs/superpowers/specs/2026-11-10-forward-validation-design.md"
SURVIVOR_TILT = ("오늘의 시총 상위 목록에는 과거의 고변동·급등 종목 중 크게 오른 것만 남아 있고, "
                 "그 종목들은 \"전체 보유\" 쪽에만 들어간다. 그래서 회피 − 전체 차이는 회피에 불리한 쪽으로 "
                 "치우칠 수 있다. 상대 비교도 이 치우침에서 자유롭지 않으며, 학습의 완충 폭 선택과 "
                 "예행연습의 탈락 표시를 읽을 때 감안해야 한다.")
STOCK_DIVIDEND = "개별 종목 수익률도 배당이 빠진 가격 수익률이다. 복권형 종목은 배당이 낮은 편이라 회피 쪽에 조금 불리하다."
VALID_DAYS = ("한 달의 유효한 날은 종목과 KODEX 200 모두 수익률이 있는 날로 센다. "
              "거래정지 하루는 이틀을 빼므로 설계서의 \"거래정지가 아닌 날 15일\"보다 조금 엄격하다.")

FIRST = "이 보고서는 투자 권유가 아니며, 이 결과만으로 실계좌 규칙을 바꾸면 안 된다."


def _stat(point=0.002):
    return {"point": point, "lo": -0.001, "hi": 0.005, "p_one": 0.12, "se": 0.002, "n": 90}


def _lottery(point=0.002):
    return {"diff": {"1.0": _stat(point), "1.5": _stat(None), "2.0": _stat(0.001)},
            "turnover_tilt": 0.12, "turnover_base": 0.05, "excluded_mean": 20.0,
            "yearly_diff": {"2020": 0.01}, "vs_kodex_annual": 0.03, "n_months": 90,
            "first_month": "2015-02-02", "last_month": "2021-12-01",
            "eligible_min": 41, "eligible_median": 233.5, "eligible_max": 290,
            "eligible_by_year": {"2015": 120.0, "2021": 280.5}}


def _gate(point=0.05):
    return {"mdd_gate": 0.10, "mdd_hold": 0.30, "mdd_diff": _stat(point),
            "return_given_up_annual": 0.02, "vol_gate": 0.1, "vol_hold": 0.2,
            "switches": 7, "episodes": [{"peak_day": "2020-01-02", "end_day": "2020-05-01",
                                         "depth_hold": 0.3, "depth_gate": 0.1}]}


def _common(stage):
    return {"stage": stage, "window": {"start": "2015-01-02", "end": "2021-12-31"},
            "n_listed": 300, "n_frames": 290, "skipped": ["111111"] * 10,
            "first_date": "2014-08-01", "last_date": "2024-12-31",
            "draws": registry.DRAWS, "max_codes": None, "refresh": False, "data_last_date": "2024-12-31"}


def _train():
    return {**_common("train"), "chosen_reentry_pct": 0.3,
            "lottery": {"0.2": _lottery(0.001), "0.3": _lottery(0.002)}, "gate": _gate()}


def _rehearsal():
    return {**_common("rehearsal"), "reentry_pct": 0.3, "lottery": _lottery(-0.001),
            "gate": _gate(), "drop": {"lottery_avoid": True, "ma_gate": False}}


def _power():
    return {**_common("power"),
            "lottery_avoid": {"reentry_pct": 0.3, "sd_monthly": 0.02, "n_months": 120,
                              "required_months": {"0.01": 900, "0.02": 225, "0.03": 100, "0.05": 36}},
            "ma_gate": {"big_drop_episodes": 3, "episodes_per_year": 0.3, "n_days": 2500, "switches": 20}}


def test_report_first_line_and_limits_before_results(tmp_path):
    path = write_report(tmp_path, {"train": _train(), "rehearsal": _rehearsal(), "power": _power()})
    text = path.read_text(encoding="utf-8")
    assert path.name == "report.md"
    assert text.splitlines()[0] == FIRST
    assert text.index("## 한계") < text.index("## 학습") < text.index("## 예행연습") < text.index("## 필요 기간")
    for fragment in ("생존편향", "상위 300", "IVOL은 시장 1요인 잔차", "정리매매", "분배금이 빠진 가격 수익률",
                     "재추출 근사", "법령 원문은 확인 못 했다", "시장 국면 하나"):
        assert fragment in text
    limits = text[text.index("## 한계"):text.index("## 학습")]
    assert limits.count("\n- ") == 15 == len(LIMITS)
    for item in LIMITS:
        assert f"- {item}\n" in limits


def _spec_limits():
    text = SPEC.read_text(encoding="utf-8")
    section = text[text.index("## 10. 보고서와 한계"):text.index("## 11.")]
    return tuple(line[2:] for line in section.splitlines() if line.startswith("- "))


def test_limits_match_spec_section_10_in_order():
    assert LIMITS == _spec_limits()


def test_limits_include_survivorship_tilt_dividend_and_valid_day_items():
    assert LIMITS[1] == SURVIVOR_TILT
    kodex = next(i for i, item in enumerate(LIMITS) if item.startswith("KODEX 200은 분배금"))
    assert LIMITS[kodex + 1] == STOCK_DIVIDEND
    assert LIMITS[-1] == VALID_DAYS


def test_report_only_includes_existing_stages(tmp_path):
    text = write_report(tmp_path, {"train": _train()}).read_text(encoding="utf-8")
    assert "## 학습" in text
    assert "## 예행연습" not in text and "## 필요 기간" not in text
    text = write_report(tmp_path, {"power": _power()}).read_text(encoding="utf-8")
    assert "## 필요 기간" in text and "## 학습" not in text
    assert "5년(60개월) 이상이면 잠그기 전에 다시 정한다" in text
    for months in ("900", "225", "100", "36"):
        assert months in text


def test_report_marks_rehearsal_as_already_seen(tmp_path):
    text = write_report(tmp_path, {"rehearsal": _rehearsal()}).read_text(encoding="utf-8")
    section = text[text.index("## 예행연습"):]
    # 구간·개수 묶음이 먼저, 그다음 "이미 본 기간" 문장
    assert (section.index("- 구간: ") < section.index("- 상장 목록")
            < section.index("이미 본 기간이라 통과해도 증거가 아니다"))
    assert ("- 후보 ① 복권형 종목 회피: 탈락 (생존편향이 회피에 불리한 쪽으로 작용할 수 있다. 한계 참조)"
            in section)
    assert "- 후보 ② 지수 이동평균 게이트: 남음" in section
    assert "lottery_avoid" not in section and "ma_gate" not in section


def test_report_lottery_sections_show_months_and_eligible_counts(tmp_path):
    text = write_report(tmp_path, {"train": _train(), "rehearsal": _rehearsal()}).read_text(encoding="utf-8")
    assert text.count("### 후보 ① 복권형 회피") == 3
    assert text.count("(측정 2015-02-02 ~ 2021-12-01)") == 3
    assert text.count("- 대상 종목 수: 최소 41 · 중앙값 233.5 · 최대 290. 초기에는 대상 종목이 적어 변동이 크다") == 3
    assert text.count("- 연도별 대상 종목 수 중앙값: 2015 120, 2021 280.5") == 3


def test_report_lottery_section_without_months_says_no_data(tmp_path):
    train = _train()
    train["lottery"]["0.2"].update(first_month=None, last_month=None, eligible_min=None,
                                   eligible_median=None, eligible_max=None, eligible_by_year={})
    text = write_report(tmp_path, {"train": train}).read_text(encoding="utf-8")
    assert "### 후보 ① 복권형 회피, 복귀 0.2 (측정 자료 없음)" in text
    assert "- 대상 종목 수: 자료 없음" in text


def test_report_header_shows_draws_and_marks_trial_runs(tmp_path):
    text = write_report(tmp_path, {"train": _train()}).read_text(encoding="utf-8")
    assert f"- 재추출 {registry.DRAWS}번" in text
    assert "시험 실행(등록값과 다른 설정)이다" not in text
    for change in ({"draws": 300}, {"max_codes": 8}):
        text = write_report(tmp_path, {"train": {**_train(), **change}}).read_text(encoding="utf-8")
        assert "- 시험 실행(등록값과 다른 설정)이다" in text
    text = write_report(tmp_path, {"train": {**_train(), "draws": 300}}).read_text(encoding="utf-8")
    assert "- 재추출 300번" in text


def test_report_power_section_wording(tmp_path):
    text = write_report(tmp_path, {"power": _power()}).read_text(encoding="utf-8")
    assert "월 표준편차(재추출 표준오차에서 되돌린 값) 2.00%" in text
    assert "필요 개월 수는 앞으로 새로 쌓일 개월 수이며 비용 2배 조건은 반영하지 않았다" in text
    assert "큰 하락 2번을 보려면 약 6.7년" in text          # 2 / 0.3
    assert "고점에서 회복까지를 한 구간으로 세므로 한 구간이 수년 이어질 수 있다" in text
    power = _power()
    power["ma_gate"].update(big_drop_episodes=0, episodes_per_year=0.0)
    text = write_report(tmp_path, {"power": power}).read_text(encoding="utf-8")
    assert "큰 하락 2번을 보려면: 자료 없음" in text and not re.search(r"약 [\d.]+년", text)


def test_report_formats_percentages_and_missing_values(tmp_path):
    text = write_report(tmp_path, {"train": _train()}).read_text(encoding="utf-8")
    assert "0.20%" in text            # 월 차이 0.002
    assert "2.40%" in text            # 연 환산 x12
    assert "자료 없음" in text         # 배수 1.5의 point 가 None
    assert "배수 1.5" in text and "배수 2.0" in text
    assert "290" in text and "300" in text
