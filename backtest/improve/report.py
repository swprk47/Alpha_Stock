"""개선 후보 검증 보고서(설계서 9절): 첫 줄은 투자 권유가 아니라는 문장, 한계는 결과보다 앞, 불합격은 "효과 없음"이 아니다."""
from pathlib import Path

import clock

DISCLAIMER = "이 보고서는 투자 권유가 아니며, 이 결과만으로 실계좌 규칙을 바꾸면 안 된다."
NO_CANDIDATES = "개선 후보 없음"
FOLD_TEXT = {"no_data": "데이터 없음", "metric_not_better": "기준선보다 낫지 않음", "absolute_not_better": "절대 기대값이 기준선 이하",
             "combo_not_better": "단일 후보를 넘지 못함"}
DIRECTION_TEXT = {"filter": "시장 필터", "exit": "청산 규칙", "signal": "새 신호", "baseline": "기준선", "combo": "조합"}

LIMITS = (
    "후보 풀이 오늘의 시총 목록이라 **생존 편향**이 있다(결과가 실제보다 좋게 나오는 쪽).",
    "기존 도구의 분할 감지(`pre_split`/`vol_break`)가 미래 행을 써서 후보 풀과 신호에서 걸러지는 날짜가 미래 정보에 의존한다. "
    "학습(절단 후 준비)과 검증(전체 프레임)은 이 플래그가 달라 같은 날짜의 후보 풀이 다를 수 있다(기준선 포함, 크기는 확인 못 함).",
    "일봉이라 장중 움직임을 못 보고, 다음날 시가·손절가 체결 가정이 낙관적이며 계좌 낙폭도 낙관적이다.",
    "후보 8개는 근거가 약한 가설이다. F1·E1~E3·S4는 검증 기간을 포함한 전체 기간 결과를 본 뒤 골랐다(사전 노출). E1~E3의 값은 민감도 격자 바깥으로 외삽한 대표 지점이다.",
    "학습에서 방향별 최고를 골랐으므로 학습 성적은 낙관적이고 검증 한 번이 판정의 근거다. 검증 기간(2022~)은 약 5년이며 국면 의존성이 크다. 시험 횟수 보정은 검증 후보 수 N에만 적용했다.",
    "판정용 계좌는 동시 보유 K=2, 매일 1/K 재조정, 전액 투자 근사다. 실제 동시 보유는 가격에 따라 1~2종목이다. K=2 계좌는 분산이 커서 ②의 검출 한계(MDE)가 크다.",
    "KODEX 200은 **가격 수익률**이라 분배금이 빠져 있다(크기는 확인 못 함, 후보가 KODEX를 이기기 쉬운 쪽의 편향). 연 2%p 민감도는 임의의 가정이다. 부트스트랩 p는 귀무가설 아래 분포가 아닌 근사다.",
    "S 후보는 점수 60 필터가 없어 거의 매일 후보가 생겨 노출과 회전이 기준선과 다를 수 있다. 불합격은 효과가 없다는 뜻이 아니다(표본·검정력 한계).",
)


def _num(x, nd=2, suffix=""):
    return "-" if x is None else f"{x:.{nd}f}{suffix}"


def _p(stat) -> str:
    if not stat or stat.get("p_one") is None:
        return "p=-"
    if stat["p_one"] == 0:
        return f"p<{1 / max(stat.get('draws') or 1, 1):.0e}"
    return f"p={stat['p_one']:.4f}"


def _st(stat, scale=1.0, nd=2, unit="", with_p=False) -> str:
    if not stat or stat.get("point") is None:
        return "판정 불가"
    text = f"{stat['point'] * scale:+.{nd}f}{unit} [{stat['lo'] * scale:+.{nd}f}, {stat['hi'] * scale:+.{nd}f}]"
    return f"{text} ({_p(stat)})" if with_p else text


def _flags(verdict) -> str:
    f = verdict["flags"]
    marks = []
    if f.get("pre_exposed"):
        marks.append("(검증 기간 사전 노출)")
    if f.get("dividend_sensitive"):
        marks.append("분배금 가정에 민감")
    if any(f.get("near_threshold", {}).values()):
        marks.append("경계")
    return " ".join(marks) or "-"


def _train_lines(train: dict) -> list:
    out = ["## 학습 단계", "",
           "원시 일봉을 학습 끝(2021-12-31)에서 자른 뒤 다시 준비한 프레임으로 기준선과 후보를 같은 슬롯 계좌(K=2)에서 비교했다. "
           "선별 지표는 학습 계좌의 KODEX 200 대비 로그성장 초과(연환산)이고, 보조로 거래당 절대 순손익을 본다.", "",
           "| 후보 | 방향 | 사전 노출 | KODEX 대비 로그성장 초과(연 %) [95%] | 거래당 순손익(%) [95%] | 거래 수 | 평균 보유일 | 시장 노출 | 평균 슬롯 사용률 | 결과 |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for row in train["train"]:
        result = "기준선" if row["direction"] == "baseline" else ("선별" if row.get("selected") else
                 f"접힘({FOLD_TEXT.get(row.get('fold_reason'), row.get('fold_reason') or '-')})" if row.get("fold_reason") else "-")
        out.append(f"| {row['name']} | {DIRECTION_TEXT.get(row['direction'], row['direction'])} | {'예' if row.get('pre_exposed') else '-'} | "
                   f"{_st(row['vs_kodex'], 100, 1)} | {_st(row['trade_mean'])} | {row['n_trades']:,} | {_num(row['avg_hold_days'], 1)} | "
                   f"{_num(None if row['exposure'] is None else row['exposure'] * 100, 0, '%')} | "
                   f"{_num(None if row['avg_slots'] is None else row['avg_slots'] * 100, 0, '%')} | {result} |")
    out += ["", f"검증 후보 수 N = {train['n']} (뽑힌 단일 후보 + 조건을 만족한 조합)."]
    folded = {d: FOLD_TEXT.get(r, r) for d, r in train.get("folded", {}).items() if r}
    if folded:
        out.append("접힌 방향: " + ", ".join(f"{DIRECTION_TEXT.get(d, d)}({reason})" for d, reason in folded.items()))
    if train["n"] == 0:
        out += ["", f"**{NO_CANDIDATES}**: 학습 단계에서 모든 방향이 접혔다. 이 자체가 결론이며 검증 기간은 쓰지 않는다."]
    else:
        out += ["", "### 최소 검출 효과(MDE, 추정)", "",
                "| 후보 | ① 0 기준 거래당 순손익(%) | ① 기준선 대비로 필요한 개선(%p) | ② KODEX 대비 로그성장 초과(연 %p) |", "|---|---|---|---|"]
        for name, m in train["mde"].items():
            out.append(f"| {name} | {_num(m.get('trade_mean'))} | {_num(m.get('trade_vs_baseline_needed'))} | "
                       f"{_num(None if m.get('vs_kodex') is None else m['vs_kodex'] * 100, 1)} |")
        out += ["", "정규 근사 추정이며 확정이 아니다. **② 검출 한계가 위 값이라 합격은 효과가 매우 클 때만 가능하다.**"]
    return out + [""]


def _test_lines(test: dict) -> list:
    out = ["## 검증 단계", "", f"검증 신호는 2022-01-01 ~ {test['test_end']}, 계좌 창은 마지막 거래일까지다. 모든 후보와 기준선이 같은 창을 쓴다.", ""]
    base = test["baseline"]
    out += ["기준선: 거래 " + f"{base['n_trades']:,}건, 거래당 순손익 {_st(base['trade_mean'])}%, KODEX 대비 {_st(base['vs_kodex'], 100, 1)}%p, 시장 노출 "
            f"{_num(None if base['exposure'] is None else base['exposure'] * 100, 0, '%')}", ""]
    if test["no_candidates"]:
        return out + [f"**{NO_CANDIDATES}**: 검증할 후보가 없어 기준선만 기록했다.", ""]
    out += [f"보정 기준 alpha_adj = 0.05 / {test['n']} = {test['alpha_adj']:.4f} (한쪽 p, 점추정 > 0).", "",
            "| 후보 | 판정 | ① 거래당 순손익(%) | ② KODEX 대비(연 %p) | ③ 기준선 대비(연 %p) | ④ 현금 대비(연 %p) | 시장 노출 / 평균 슬롯 | 표시 |",
            "|---|---|---|---|---|---|---|---|"]
    for c in test["candidates"]:
        s = c["summary"]
        out.append(f"| {c['name']} | **{c['verdict']['label']}** | {_st(s['trade_mean'], 1, 2, '', True)} | {_st(s['vs_kodex'], 100, 1, '', True)} | "
                   f"{_st(c['vs_baseline'], 100, 1, '', True)} | {_st(s['vs_cash'], 100, 1, '', True)} | "
                   f"{_num(None if s['exposure'] is None else s['exposure'] * 100, 0, '%')} / {_num(None if s['avg_slots'] is None else s['avg_slots'] * 100, 0, '%')} | "
                   f"{_flags(c['verdict'])} |")
    out += ["", "- **합격**은 앱 반영을 논의할 후보일 뿐이며, 사전 노출 표시가 있는 후보는 새 데이터(앞으로의 구간 또는 별도 표본)로 다시 확인하기 전에는 앱 반영 논의 대상이 아니다.",
            "- **유망**은 앱 반영 근거가 아니라 다음 시험의 출발점이다(기준선보다 낫지만 합격 기준은 못 넘었다).",
            "- **불합격**은 효과가 없다는 뜻이 아니다. 검출 한계(MDE) 이하의 개선은 이 검증으로 가려낼 수 없다.", ""]
    years = sorted({y for c in test["candidates"] for y in c.get("yearly", {})} | set(test.get("baseline_yearly", {})))
    if years:
        out += ["### 참고: 연도별 거래당 순손익(%) / 계좌 수익(%)", "", "| 연도 | " + " | ".join(["기준선"] + [c["name"] for c in test["candidates"]]) + " |",
                "|---" * (len(test["candidates"]) + 2) + "|"]
        for y in years:
            cells = [test.get("baseline_yearly", {}).get(str(y))] + [c.get("yearly", {}).get(str(y)) for c in test["candidates"]]
            out.append(f"| {y} | " + " | ".join("-" if cell is None else f"{_num(cell.get('trade_mean'))} / {_num(cell.get('account'))}" for cell in cells) + " |")
        out.append("")
    buckets = sorted({b for c in test["candidates"] for b in c.get("confirm", {})})
    if buckets:
        out += ["### 참고: 다른 예산 구간의 거래당 순손익(%) (판정에 쓰지 않음)", ""]
        for b in buckets:
            out.append(f"- 예산 {int(b):,}원: " + ", ".join(f"{c['name']} {_num(c.get('confirm', {}).get(b))}" for c in test["candidates"]))
        out.append("")
    return out


def build_markdown(train: dict, test: "dict | None", *, banner: "str | None" = None) -> str:
    lines = [DISCLAIMER, ""]
    if banner:
        lines += [f"> **{banner}**", ""]
    lines += ["# 스윙 추천 개선 후보 검증 보고서", "", f"작성 {clock.now_str()}", "", "## 한계", ""] + [f"- {item}" for item in LIMITS] + [""]
    lines += _train_lines(train)
    lines += _test_lines(test) if test is not None else ["## 검증 단계", "", "검증 단계는 아직 실행하지 않았다.", ""]
    return "\n".join(lines) + "\n"


def write_improve_report(out_dir, train: dict, test: "dict | None" = None, *, banner: "str | None" = None) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "improve_report.md"
    path.write_text(build_markdown(train, test, banner=banner), encoding="utf-8")
    return path
