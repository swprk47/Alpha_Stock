"""분석 보고서: 한계를 결과보다 먼저 적고, 수치에는 표본 수와 95% 구간을 붙인다. 근거가 모자라면 "근거 부족"이라고 쓴다."""
import json
from pathlib import Path

MODE_LABEL = {"close": "종가 진입", "next_open": "다음날 시가 진입"}
NO_SAMPLE = "표본 없음"

LIMITS = (
    "후보 풀이 오늘의 시총 목록이라 **생존 편향**이 있다(결과가 실제보다 좋게 나오는 쪽).",
    "일봉이라 장중 신호·장중 거래량 문제를 재현하지 못하고, 계좌 곡선의 낙폭은 종가 기준이라 장중 낙폭을 과소평가한다.",
    "같은 날 익절·손절이 모두 닿으면 손절로 가정했다.",
    "요소는 6개와 앱 점수로 한정했다. 다른 요소는 보지 않았다.",
    "검증 기간(2022~)은 약 5년이라 표본이 제한적이다. 못 본 것일 수 있어 근거가 모자라면 '근거 부족'으로 적는다.",
    "상장 목록이 기준선 실행(2026-11-02) 때와 다를 수 있어 기준선 숫자와 조금 다를 수 있다.",
    "분할로 의심되는 종목·날짜는 기존 백테스트 규칙대로 후보에서 제외했다(오탐 가능성은 확인 못 함).",
    "점수 요소는 앱 함수가 60점 미만에 값을 주지 않아 통과 종목만으로 검정했다.",
)


def _num(x, nd=2, suffix=""):
    return "-" if x is None else f"{x:.{nd}f}{suffix}"


def _pct(x, nd=1):
    return "-" if x is None else f"{x * 100:.{nd}f}%"


def _boot(b, nd=3, scale=1.0, unit="") -> str:
    if b is None or b.get("point") is None:
        return "판정 불가"
    return (f"{b['point'] * scale:+.{nd}f}{unit} [{b['lo'] * scale:+.{nd}f}, {b['hi'] * scale:+.{nd}f}] "
            f"(일수 {b['n_days']}, p={b['p']:.3f})")


def _title(s) -> str:
    return f"예산 {s['bucket']:,}원 · {MODE_LABEL.get(s['entry_mode'], s['entry_mode'])}"


def _factor_lines(s) -> list:
    out = [f"### {_title(s)}", ""]
    if s["panel_rows"]["main"] == 0:
        return out + [NO_SAMPLE, ""]
    out += [f"후보-날짜 {s['panel_rows']['main']:,}건(본 분석: 후보 풀 앞 30개)", "",
            "| 요소 | 판정 | 학습 순위상관 [95%] | 검증 순위상관 [95%] | 학습 n | 검증 n | Holm p | 연도 방향(+/-) |", "|---|---|---|---|---|---|---|---|"]
    for name, f in s["factors"]["main"].items():
        signs = list(f["yearly_signs"].values())
        out.append(f"| {name} | **{f['verdict']}** | {_boot(f['train'])} | {_boot(f['test'])} | {f['n_train']:,} | {f['n_test']:,} | "
                   f"{_num(f['holm_p'], 3)} | {signs.count(1)}/{signs.count(-1)} |")
    full = s["factors"]["full"]
    if full:
        out += ["", f"확인용(필터 통과 전체 풀, {s['panel_rows']['full']:,}건) 판정: "
                + ", ".join(f"{name} {f['verdict']}" for name, f in full.items())]
    out += ["", "구간별 평균 순손익(%, 건수):"]
    for name, f in s["factors"]["main"].items():
        cells = ", ".join(f"{row['label']}: {_num(row['mean'])} ({row['n']:,})" for row in f["table"]) or NO_SAMPLE
        out.append(f"- {name}: {cells}")
    return out + [""]


def _equity_lines(s) -> list:
    out = [f"### {_title(s)}", ""]
    if not s["trades"]:
        return out + [NO_SAMPLE, ""]
    e = s["equity"]
    out += [f"추천 상위 3 거래 {s['trades']:,}건. 보유 중인 포지션에 균등 배분, 보유가 없는 날은 현금.", "",
            "| 대상 | 연수익 | 최대 낙폭 | 샤프 | 시장 노출 |", "|---|---|---|---|---|"]
    for label, key in (("전략", "strategy"), ("KODEX 200 계속 보유", "kodex_hold"), ("KODEX 200 같은 날만", "kodex_matched"), ("현금", "cash")):
        p = e.get(key)
        if p:
            out.append(f"| {label} | {_pct(p['ann_return'])} | {_pct(p['max_drawdown'])} | {_num(p['sharpe'])} | {_pct(p['exposure'], 0)} |")
    out.append("")
    for label, key in (("KODEX 200 계속 보유", "vs_kodex_hold"), ("KODEX 200 같은 날만", "vs_kodex_matched"), ("현금", "vs_cash")):
        b = e["excess"].get(key)
        if b:
            out.append(f"- 연환산 초과수익(전략 - {label}): {_boot(b, 1, 100, '%p')}")
    if e.get("information_ratio") is not None:
        out.append(f"- 정보비율(KODEX 200 대비): {_num(e['information_ratio'])}")
    d = s["cost_drag"]
    out.append(f"- 비용: 수수료·세금 전 평균 {_num(d['gross_mean_pct'])}% → 후 {_num(d['net_mean_pct'])}% (깎은 양 {_num(d['drag_pct'])}%p)")
    if s["states"]:
        out.append("- 시장 상태별 거래당 기대 손익: " + ", ".join(
            f"{'20일선 위' if k == 'up' else '20일선 아래'} " + (f"{_num(v['expectancy_pct'])}% ({v['n']:,}건)" if v["n"] else NO_SAMPLE)
            for k, v in s["states"].items()))
    return out + [""]


def _correlation_lines(s) -> list:
    out = [f"### {_title(s)}", ""]
    c = s["correlation"]
    if not c:
        return out + [NO_SAMPLE, ""]
    p, a = c["picks_vs_random"], c["all_stop"]
    out.append(f"- 추천 3종목 평균 상관 {_num(p['picks_mean'], 3)} vs 후보 풀 무작위 3종목 {_num(p['random_mean'], 3)} "
               f"({p['n_days']:,}일, 추천 1~2개라 제외 {p['n_skipped']:,}일)")
    out.append(f"- 3종목이 모두 손절된 날: 관측 {_pct(a['observed'], 2)} vs 독립 가정 {_pct(a['expected'], 2)} "
               f"(차이 {_boot(a['diff'], 4)}, {a['n_days']:,}일)")
    if c["terciles"]:
        out += ["", "| 상관 3분위 | 일수 | 3종목 평균 손익 | 표준편차 | 하위 5% 평균 |", "|---|---|---|---|---|"]
        out += [f"| {t['label']} | {t['n_days']:,} | {_num(t['mean_ret'])}% | {_num(t['std_ret'])} | {_num(t['lowest5_mean'])}% |" for t in c["terciles"]]
    else:
        out.append("- 상관 3분위: 표본이 30일 미만이라 나누지 않았다")
    return out + [""]


def _risk_lines(s) -> list:
    out = [f"### {_title(s)}", ""]
    r = s["risk"]
    if not r:
        return out + [NO_SAMPLE, ""]
    out += ["| 기간(거래일) | 이익 확률 | 하위 5% 수익 | 하위 5% 평균(CVaR) | 낙폭 중앙값 | 낙폭 95퍼센타일 | 낙폭 20% 이상 확률 |", "|---|---|---|---|---|---|---|"]
    for h, v in r["horizons"].items():
        out.append(f"| {h} | {_pct(v['prob_profit'])} | {_pct(v['p5'])} | {_pct(v['cvar5'])} | {_pct(v['mdd_median'])} | {_pct(v['mdd_p95'])} | {_pct(v['prob_mdd_20'])} |")
    for state, v in r["regime"].items():
        label = "KODEX 200이 20일선 위인 날만" if state == "up" else "KODEX 200이 20일선 아래인 날만"
        out.append(f"- {label}(252일, {v['n_days']:,}일 풀): 이익 확률 {_pct(v['risk']['prob_profit'])}, 하위 5% 평균 {_pct(v['risk']['cvar5'])}")
    cal = r["calibration"]
    if cal:
        out += ["", f"보정 점검(Kupiec 방식, 21일): 학습 기간 분포의 하위 5% 경계 {_pct(cal['p5'])}, 검증 기간 구간 중 그보다 나쁜 비율 "
                    f"{_pct(cal['exceed_rate'])} (기대 5%, 95% 구간 [{_pct(cal['ci_lo'])}, {_pct(cal['ci_hi'])}], 구간 {cal['n_windows']:,}개)"]
    else:
        out += ["", "보정 점검: 검증 기간이 짧아 계산하지 못했다"]
    return out + [""]


def _delay_lines(scenarios) -> list:
    by_bucket = {}
    for s in scenarios:
        if s["cost_drag"]:
            by_bucket.setdefault(s["bucket"], {})[s["entry_mode"]] = s["cost_drag"]["net_mean_pct"]
    out = []
    for bucket, modes in by_bucket.items():
        if {"close", "next_open"} <= set(modes):
            out.append(f"- 예산 {bucket:,}원: 종가 진입 {_num(modes['close'])}% vs 다음날 시가 진입 {_num(modes['next_open'])}% "
                       f"(하루 늦은 진입의 차이 {_num(modes['close'] - modes['next_open'])}%p)")
    return out


def build_markdown(results: dict) -> str:
    d, scenarios = results["data"], results["scenarios"]
    lines = ["# 스윙 추천 규칙 검증 분석 보고서", "",
             f"작성 {d['generated_at']} · 시드 {d['seed']} · 부트스트랩 {d['draws']:,}회(날짜 {d['block']}일 블록) · 슬리피지 {d['slippage_pct']}% · 위험 분포 경로 {d['paths']:,}개", "",
             "> 이 보고서는 미래를 맞히는 것이 아니라 과거 분포가 이어진다고 가정한 범위를 보여준다. 시장이 바뀌면 틀릴 수 있다.", "",
             "## 한계", ""] + [f"- {item}" for item in LIMITS]
    lines += ["", "## 데이터", "",
              f"- 상장 목록 {d['n_listed']}종목 중 일봉이 있는 종목 {d['n_frames']}개(벤치마크 포함), 거래일 {d['n_dates']:,}일 ({d['first_date']} ~ {d['last_date']})",
              f"- 일봉이 없어 뺀 종목: {', '.join(d['skipped']) if d['skipped'] else '없음'}",
              "- 판정: 학습(2014-08~2021-12) Holm 보정 후 유의 + 검증(2022-01~) 같은 방향·95% 구간이 0 제외 + 연도 3분의 2 이상 같은 방향일 때만 '유의'",
              "", "## 요소별 예측력", "",
              "순위상관은 손절·익절·만료 결과의 **순서를 보는** 값이라 평균 손익의 방향과 다를 수 있다(손절이 잦아도 익절 폭이 크면 평균은 비슷하다). "
              "아래 구간별 평균 순손익을 함께 읽는다. 손절 -3%·익절 +6.5%가 고정이라 변동성(atr_pct)처럼 규칙 자체가 만드는 기계적 효과도 섞일 수 있다.", ""]
    for s in scenarios:
        lines += _factor_lines(s)
    lines += ["## 추천 선택 효과", "", "추천 상위 3 평균 순손익 - 그날 후보 풀 평균 순손익(%p):", ""]
    lines += [f"- {_title(s)}: {NO_SAMPLE}" if s["selection"]["point"] is None else f"- {_title(s)}: {_boot(s['selection'], 3, 1.0, '%p')}" for s in scenarios]
    lines += ["", "## 계좌 곡선과 단순 보유 비교", "",
              "연수익은 보유 중인 포지션에 **전액을 매일 재투자**한다고 가정한 값이라 '거래당 손익 x 연 회전 횟수'에 가깝고, 회전이 잦을수록 크게 증폭된다. "
              "실제로 자금을 일부만 쓰면 이 숫자보다 작게 움직인다.", ""]
    for s in scenarios:
        lines += _equity_lines(s)
    delay = _delay_lines(scenarios)
    if delay:
        lines += ["### 하루 늦게 진입하면 얼마나 바뀌나", ""] + delay + [""]
    lines += ["## 추천 3종목 상관", ""]
    for s in scenarios:
        lines += _correlation_lines(s)
    lines += ["## 위험 분포", "", "실제 일별 계좌 수익률을 5일 블록으로 다시 뽑은 가상 경로의 분포다(낙폭은 깊이).",
              "시장 상태별 줄은 **전날 종가** 기준 KODEX 200과 20일선의 관계로 날을 나누고(그날의 움직임이 분류를 정하지 않게), 그 상태의 날만 252일 이어 붙인 경로다. "
              "상태가 1년 내내 이어진다고 가정한 극단 시나리오라 실제 확률로 읽으면 안 된다.", ""]
    for s in scenarios:
        lines += _risk_lines(s)
    return "\n".join(lines) + "\n"


def write_analysis_report(out_dir, results: dict) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "analysis_report.md").write_text(build_markdown(results), encoding="utf-8")
    (out / "analysis.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
