import json

from bt_helpers import sample_results
from backtest.report import write_report


def test_report_files_and_required_sections(tmp_path):
    write_report(tmp_path, sample_results())
    md = (tmp_path / "report.md").read_text(encoding="utf-8")
    for text in ("생존 편향", "투자 조언이 아니며", "대조군", "점검표", "100000", "next_open", "실패 종목", "BAD1"):
        assert text in md
    assert (tmp_path / "trades.csv").read_text(encoding="utf-8").splitlines()[0] == (
        "code,bucket,entry_mode,signal_date,entry_date,exit_date,entry_price,exit_price,exit_reason,net_return_pct,held_days,score")
    data = json.loads((tmp_path / "metrics.json").read_text(encoding="utf-8"))
    assert data["scenarios"][0]["summary"]["n"] == 5 and data["data_quality"]["failed"] == ["BAD1"]
    assert len((tmp_path / "trades.csv").read_text(encoding="utf-8").splitlines()) == 1 + 5


def test_report_marks_empty_scenarios(tmp_path):
    write_report(tmp_path, sample_results())
    md = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "거래 없음" in md
    data = json.loads((tmp_path / "metrics.json").read_text(encoding="utf-8"))
    empty = data["scenarios"][1]
    assert empty["summary"]["n"] == 0 and empty["summary"]["expectancy_pct"] is None and empty["n_trades"] == 0


def test_infinite_or_missing_values_serialize_as_null(tmp_path):
    results = sample_results()
    results.scenarios[0].excess_pct = float("inf")                       # 무한대·NaN 은 JSON 에서 null
    results.scenarios[0].control = results.scenarios[0].control.__class__(float("nan"), None, None)
    write_report(tmp_path, results)
    text = (tmp_path / "metrics.json").read_text(encoding="utf-8")
    assert "Infinity" not in text and "NaN" not in text
    data = json.loads(text)
    assert data["scenarios"][0]["excess_pct"] is None and data["scenarios"][0]["summary"]["profit_factor"] is not None
    assert data["scenarios"][1]["summary"]["profit_factor"] is None
