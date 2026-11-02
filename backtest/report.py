"""보고서 출력: report.md, trades.csv, metrics.json."""
import csv
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

from .metrics import CheckItem, ControlSummary, SensRow, Summary
from .simulate import Trade

TRADE_COLUMNS = ["code", "bucket", "entry_mode", "signal_date", "entry_date", "exit_date", "entry_price",
                 "exit_price", "exit_reason", "net_return_pct", "held_days", "score"]


@dataclass
class ScenarioResult:
    bucket: int
    entry_mode: str
    summary: Summary                 # 그날의 추천 상위 3개 기준
    all_passes_summary: Summary      # 점수를 통과한 전체 기준
    yearly: dict
    bands: dict
    states: dict
    excess_pct: "float | None"
    control: ControlSummary
    sensitivity: list
    checklist: list
    trades: list


@dataclass
class DataQuality:
    n_listed: int
    n_with_data: int
    failed: list
    skipped_short: list
    excluded_days: dict
    first_date: str
    last_date: str


@dataclass
class RunResults:
    generated_at: str
    scenarios: list
    data_quality: DataQuality


LIMITS = (
    "**생존 편향**: 후보 풀을 오늘의 시가총액 상위 목록으로 만들었습니다. 이미 상장폐지된 종목은 빠져 있고, "
    "과거 시점의 시총 순위는 구할 수 없습니다. 그래서 결과가 실제보다 좋게 나올 수 있습니다.",
    "**일봉의 한계**: 장중에 신호를 보고 그 순간 가격으로 사는 앱의 실제 사용과 장중 거래량이 덜 쌓이는 문제는 재현하지 못합니다. "
    "같은 날 익절과 손절이 모두 닿으면 손절로 계산했습니다(보수적).",
    "**표본**: 거래 수가 적은 구간이나 연도는 우연의 영향이 큽니다. 점검표의 거래 100건 기준을 함께 보세요.",
    "**투자 조언이 아니며** 과거 성적이 미래 수익을 보장하지 않습니다. 이 보고서는 전략을 고칠지 판단하는 근거 자료입니다.",
)


def _num(value, digits=2, suffix=""):
    return "-" if value is None else f"{value:.{digits}f}{suffix}"


def _rate(value):
    return f"{value * 100:.1f}%"


SUMMARY_HEADER = "| 구분 | 거래 수 | 승률 | 익절 | 손절 | 만료 | 기대 손익 | 손익비 | 평균 보유일 | 최대 낙폭 | 최대 연속 손실 |\n|---|---|---|---|---|---|---|---|---|---|---|\n"


def _summary_row(label: str, s: Summary) -> str:
    return (f"| {label} | {s.n} | {_rate(s.win_rate)} | {_rate(s.target_rate)} | {_rate(s.stop_rate)} | {_rate(s.expire_rate)} | "
            f"{_num(s.expectancy_pct, 2, '%')} | {_num(s.profit_factor)} | {_num(s.avg_held_days, 1)} | "
            f"{_num(s.max_drawdown_pct, 2, '%p')} | {s.max_loss_streak} |\n")


def _table(title: str, groups: dict) -> str:
    return f"\n**{title}**\n\n" + SUMMARY_HEADER + "".join(_summary_row(str(k), v) for k, v in groups.items())


def _scenario_markdown(sc: ScenarioResult) -> str:
    out = [f"\n## 예산 구간 {sc.bucket}원 / 매수 {sc.entry_mode}\n"]
    if sc.summary.n == 0:
        out.append("\n거래 없음 — 이 조건에서 추천이 한 번도 나오지 않았거나, 보유 기간이 데이터 끝을 넘어 거래가 완결되지 않았습니다.\n")
    else:
        out.append("\n**기본 성적**\n\n" + SUMMARY_HEADER)
        out.append(_summary_row("그날의 추천 상위 3", sc.summary))
        out.append(_summary_row("점수 통과 전체", sc.all_passes_summary))
        c = sc.control
        out.append(f"| 대조군(무작위 3, 평균) | {_num(c.mean_n, 1)} | {_num(None if c.mean_win_rate is None else c.mean_win_rate * 100, 1, '%')} "
                   f"| - | - | - | {_num(c.mean_expectancy_pct, 2, '%')} | - | - | - | - |\n")
        out.append(f"\n시장 대비 초과수익(KODEX 200, 비용 미반영 벤치마크): {_num(sc.excess_pct, 2, '%p')}\n")
        out.append(_table("연도별", sc.yearly))
        out.append(_table("점수대별", sc.bands))
        out.append(_table("시장 상태별(신호일 KODEX 200 종가 vs 20일선)", sc.states))
        out.append("\n**민감도** (익절 x 손절 x 보유일, 마지막 두 줄은 슬리피지)\n\n| 익절 | 손절 | 보유일 | 슬리피지 | 거래 수 | 기대 손익 |\n|---|---|---|---|---|---|\n")
        for r in sc.sensitivity:
            out.append(f"| {r.target_pct}% | {r.stop_pct}% | {r.hold_days}일 | {r.slippage_pct}% | {r.n} | {_num(r.expectancy_pct, 2, '%')} |\n")
    out.append("\n**점검표**(결론이 아니라 증거입니다)\n\n")
    for item in sc.checklist:
        out.append(f"- [{'x' if item.passed else ' '}] {item.label} — {item.detail}\n")
    return "".join(out)


def _quality_markdown(q: DataQuality) -> str:
    worst = sorted(q.excluded_days.items(), key=lambda kv: -kv[1])[:10]
    lines = [
        "\n## 데이터 품질\n",
        f"\n- 목록 {q.n_listed}개, 일봉 확보 {q.n_with_data}개, 기간 {q.first_date} ~ {q.last_date}\n",
        f"- 받기 실패 종목: {', '.join(q.failed) if q.failed else '없음'}\n",
        f"- 일봉이 부족하거나 없어 뺀 종목: {', '.join(q.skipped_short) if q.skipped_short else '없음'}\n",
        f"- 분할 구간으로 신호에서 제외한 날이 많은 종목(상위 10): {', '.join(f'{c}({n}일)' for c, n in worst) if worst else '없음'}\n",
        "- 분할은 삼성전자 한 종목에서만 직접 확인했고 배당 조정은 확인하지 않았습니다.\n",
    ]
    return "".join(lines)


def _clean(value):
    """JSON 에 쓸 수 없는 값(무한대·NaN)은 None 으로, 날짜는 문자열로."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def _scenario_json(sc: ScenarioResult) -> dict:
    return _clean({
        "bucket": sc.bucket, "entry_mode": sc.entry_mode,
        "summary": asdict(sc.summary), "all_passes_summary": asdict(sc.all_passes_summary),
        "yearly": {y: asdict(s) for y, s in sc.yearly.items()}, "bands": {k: asdict(s) for k, s in sc.bands.items()},
        "states": {k: asdict(s) for k, s in sc.states.items()}, "excess_pct": sc.excess_pct,
        "control": asdict(sc.control), "sensitivity": [asdict(r) for r in sc.sensitivity],
        "checklist": [asdict(i) for i in sc.checklist], "n_trades": len(sc.trades)})


def write_report(out_dir, results: RunResults) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    md = [f"# 스윙 추천 규칙 백테스트 보고서\n\n생성: {results.generated_at}\n\n## 한계 (먼저 읽어 주세요)\n\n"]
    md += [f"- {line}\n" for line in LIMITS]
    md.append(_quality_markdown(results.data_quality))
    md += [_scenario_markdown(sc) for sc in results.scenarios]
    (out / "report.md").write_text("".join(md), encoding="utf-8")

    with open(out / "trades.csv", "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(TRADE_COLUMNS)
        for sc in results.scenarios:
            for t in sc.trades:
                writer.writerow([t.code, t.bucket, t.entry_mode, t.signal_date.date().isoformat(),
                                 t.entry_date.date().isoformat(), t.exit_date.date().isoformat(), t.entry_price,
                                 t.exit_price, t.exit_reason, round(t.net_return_pct, 4), t.held_days, t.score])

    payload = {"generated_at": results.generated_at, "data_quality": _clean(asdict(results.data_quality)),
               "scenarios": [_scenario_json(sc) for sc in results.scenarios]}
    with open(out / "metrics.json", "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, allow_nan=False)
