"""보고서(report) 테스트: 손으로 만든 JSON 모양 payload로 문구와 순서를 확인한다."""
from backtest.forward.report import write_report

FIRST = "이 보고서는 투자 권유가 아니며, 이 결과만으로 실계좌 규칙을 바꾸면 안 된다."


def _stat(point=0.002):
    return {"point": point, "lo": -0.001, "hi": 0.005, "p_one": 0.12, "se": 0.002, "n": 90}


def _lottery(point=0.002):
    return {"diff": {"1.0": _stat(point), "1.5": _stat(None), "2.0": _stat(0.001)},
            "turnover_tilt": 0.12, "turnover_base": 0.05, "excluded_mean": 20.0,
            "yearly_diff": {"2020": 0.01}, "vs_kodex_annual": 0.03, "n_months": 90}


def _gate(point=0.05):
    return {"mdd_gate": 0.10, "mdd_hold": 0.30, "mdd_diff": _stat(point),
            "return_given_up_annual": 0.02, "vol_gate": 0.1, "vol_hold": 0.2,
            "switches": 7, "episodes": [{"peak_day": "2020-01-02", "end_day": "2020-05-01",
                                         "depth_hold": 0.3, "depth_gate": 0.1}]}


def _common(stage):
    return {"stage": stage, "window": {"start": "2015-01-02", "end": "2021-12-31"},
            "n_listed": 300, "n_frames": 290, "skipped": ["111111"] * 10,
            "first_date": "2014-08-01", "last_date": "2024-12-31"}


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
    assert limits.count("\n- ") == 12


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
    assert "이미 본 기간이라 통과해도 증거가 아니다" in text
    section = text[text.index("## 예행연습"):]
    assert "탈락" in section and "lottery_avoid" in section and "ma_gate" in section


def test_report_formats_percentages_and_missing_values(tmp_path):
    text = write_report(tmp_path, {"train": _train()}).read_text(encoding="utf-8")
    assert "0.20%" in text            # 월 차이 0.002
    assert "2.40%" in text            # 연 환산 x12
    assert "자료 없음" in text         # 배수 1.5의 point 가 None
    assert "배수 1.5" in text and "배수 2.0" in text
    assert "290" in text and "300" in text
