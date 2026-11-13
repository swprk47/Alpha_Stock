"""단계별 JSON(학습·예행연습·필요 기간)을 한 장의 Markdown 보고서로 쓴다.

첫 줄은 고정 문구, 한계는 결과보다 먼저 온다. 값이 None이면 "자료 없음"으로 적는다.
"""
from pathlib import Path

from backtest.forward.registry import DRAWS

FIRST_LINE = "이 보고서는 투자 권유가 아니며, 이 결과만으로 실계좌 규칙을 바꾸면 안 된다."
NO_DATA = "자료 없음"

LIMITS = (
    "학습·예행연습은 오늘의 종목 목록을 써서 생존편향이 있다. 상대 비교로만 읽고 절대 수익·KODEX 200 대비는 참고다.",
    "오늘의 시총 상위 목록에는 과거의 고변동·급등 종목 중 크게 오른 것만 남아 있고, 그 종목들은 \"전체 보유\" 쪽에만 "
    "들어간다. 그래서 회피 − 전체 차이는 회피에 불리한 쪽으로 치우칠 수 있다. 상대 비교도 이 치우침에서 자유롭지 않으며, "
    "학습의 완충 폭 선택과 예행연습의 탈락 표시를 읽을 때 감안해야 한다.",
    "2022~2026 예행연습은 이미 본 기간이라 통과해도 증거가 아니다. 변동성 관련 요소는 이전 분석에서 이 기간에 이미 봤다.",
    "월 관측이 적어 검정력이 낮다. 필요 기간 측정값과 가정한 효과 크기를 같이 적는다.",
    "판정 기간의 시장 국면 하나가 결과를 좌우할 수 있다.",
    "\"상위 300\"은 코스피 150 + 코스닥 150이며 문헌의 표본과 다르다. ①의 상위 300 한정 근거는 문헌에 없다.",
    "IVOL은 시장 1요인 잔차로, 문헌의 정의와 다를 수 있다.",
    "교체일 시가 체결·슬리피지 0.1% 가정은 낙관적일 수 있다. 같은 비중 300종목 보유는 소액 계좌에서 그대로 따라 할 수 없다"
    "(1주 단위, 소수점 거래 가능 종목 한정).",
    "상장폐지 종목을 마지막 종가에 판 것으로 본다(정리매매 손실 미반영).",
    "판정 기간이 길어질수록 고정한 300종목이 \"지금의 상위 300\"과 달라진다(의도한 대가).",
    "KODEX 200은 분배금이 빠진 가격 수익률이다.",
    "개별 종목 수익률도 배당이 빠진 가격 수익률이다. 복권형 종목은 배당이 낮은 편이라 회피 쪽에 조금 불리하다.",
    "확률과 구간은 재추출 근사다. 최대 낙폭의 구간은 특히 거칠다.",
    "세율은 2차 자료 기준이고 법령 원문은 확인 못 했다.",
    "한 달의 유효한 날은 종목과 KODEX 200 모두 수익률이 있는 날로 센다. 거래정지 하루는 이틀을 빼므로 "
    "설계서의 \"거래정지가 아닌 날 15일\"보다 조금 엄격하다.",
)

# 예행연습 탈락 표시에 쓰는 후보 이름(JSON 키 -> 보고서 이름)
CANDIDATE_NAMES = {"lottery_avoid": "후보 ① 복권형 종목 회피", "ma_gate": "후보 ② 지수 이동평균 게이트"}
SURVIVOR_NOTE = "(생존편향이 회피에 불리한 쪽으로 작용할 수 있다. 한계 참조)"


def _pct(v, digits=2, scale=1.0):
    return NO_DATA if v is None else f"{v * scale * 100:.{digits}f}%"


def _stat(stat, *, scale=1.0):
    """점추정 + 95% 구간 + 한쪽 확률. scale 은 월 -> 연 환산 등에 쓴다."""
    if not stat or stat.get("point") is None:
        return NO_DATA
    p = "" if stat.get("p_one") is None else f", 한쪽 확률 {stat['p_one']:.3f}"
    return (f"{_pct(stat['point'], scale=scale)} "
            f"(95% 구간 {_pct(stat['lo'], scale=scale)} ~ {_pct(stat['hi'], scale=scale)}{p})")


def _head(payload):
    w = payload["window"]
    lines = [f"- 구간: {w['start']} ~ {w['end']} (자료 {payload['first_date']} ~ {payload['last_date']})",
            f"- 상장 목록 {payload['n_listed']}개, 사용한 일봉 {payload['n_frames']}개, 뺀 종목 {len(payload['skipped'])}개"
            + (f" ({', '.join(payload['skipped'][:20])}{' ...' if len(payload['skipped']) > 20 else ''})"
               if payload["skipped"] else ""),
            f"- 재추출 {payload.get('draws', NO_DATA)}번"]
    if payload.get("max_codes") is not None or payload.get("draws", DRAWS) != DRAWS:
        lines.append("- 시험 실행(등록값과 다른 설정)이다")
    return lines + [f"- 등록표 지문: {payload.get('registry', NO_DATA)}", ""]


def _measured(ev):
    """① 제목 뒤에 붙이는 측정한 달(첫 교체일 ~ 마지막 교체일)."""
    first, last = ev.get("first_month"), ev.get("last_month")
    return f"(측정 {NO_DATA})" if first is None or last is None else f"(측정 {first} ~ {last})"


def _num(v):
    return f"{v:g}" if isinstance(v, float) else str(v)


def _eligible(ev):
    """측정한 달의 대상 종목 수 최소·중앙값·최대와 교체일 연도별 중앙값."""
    lo, mid, hi = ev.get("eligible_min"), ev.get("eligible_median"), ev.get("eligible_max")
    if None in (lo, mid, hi):
        counts = f"- 대상 종목 수: {NO_DATA}"
    else:
        counts = (f"- 대상 종목 수: 최소 {_num(lo)} · 중앙값 {_num(mid)} · 최대 {_num(hi)}. "
                  "초기에는 대상 종목이 적어 변동이 크다")
    by_year = ev.get("eligible_by_year") or {}
    years = ", ".join(f"{y} {_num(v)}" for y, v in by_year.items()) or NO_DATA
    return [counts, f"- 연도별 대상 종목 수 중앙값: {years}"]


def _lottery(ev):
    lines = ["| 비용 | 월 차이(회피 - 전체) | 연 환산(×12) |", "|---|---|---|"]
    for mult in ("1.0", "1.5", "2.0"):
        s = ev["diff"].get(mult)
        lines.append(f"| 배수 {mult} | {_stat(s)} | {_stat(s, scale=12)} |")
    lines += ["",
              f"- 월 관측 {ev['n_months']}개, 평균 회전율 회피 {_pct(ev['turnover_tilt'])}/월 · 전체 {_pct(ev['turnover_base'])}/월",
              f"- 월평균 제외 종목 {ev['excluded_mean']:.1f}개, KODEX 200 대비 연 {_pct(ev['vs_kodex_annual'])}(참고)",
              "- 연도별 월 차이 합: " + (", ".join(f"{y} {_pct(v)}" for y, v in ev["yearly_diff"].items()) or NO_DATA),
              *_eligible(ev), ""]
    return lines


def _gate(ev):
    eps = ev["episodes"]
    lines = [f"- 최대 낙폭: 게이트 {_pct(ev['mdd_gate'])} · 계속 보유 {_pct(ev['mdd_hold'])}",
             f"- 낙폭 차이(보유 - 게이트): {_stat(ev['mdd_diff'])}",
             f"- 포기한 수익 연 {_pct(ev['return_given_up_annual'])}, 변동성 게이트 {_pct(ev['vol_gate'])} · 보유 {_pct(ev['vol_hold'])}",
             f"- 전환 {ev['switches']}번, 큰 하락 {len(eps)}번"]
    for e in eps:
        lines.append(f"  - {e['peak_day']} ~ {e['end_day']}: 보유 -{_pct(e['depth_hold'])}, 게이트 -{_pct(e['depth_gate'])}")
    return lines + [""]


def _train(p):
    lines = ["## 학습", ""] + _head(p)
    lines += [f"- 선택한 완충 폭(복귀 순위): {p['chosen_reentry_pct']}", ""]
    for key, ev in p["lottery"].items():
        lines += [f"### 후보 ① 복권형 회피, 복귀 {key} {_measured(ev)}", ""] + _lottery(ev)
    return lines + ["### 후보 ② 10개월 평균 게이트", ""] + _gate(p["gate"])


def _rehearsal(p):
    lines = ["## 예행연습", ""] + _head(p) + ["이미 본 기간이라 통과해도 증거가 아니다. 탈락 여부만 거른다.", ""]
    lines += [f"- 학습에서 정한 완충 폭: {p['reentry_pct']}", "",
              f"### 후보 ① 복권형 회피 {_measured(p['lottery'])}", ""] + _lottery(p["lottery"])
    lines += ["### 후보 ② 10개월 평균 게이트", ""] + _gate(p["gate"])
    lines.append("### 탈락 여부")
    for key, dropped in p["drop"].items():
        note = f" {SURVIVOR_NOTE}" if key == "lottery_avoid" else ""
        lines.append(f"- {CANDIDATE_NAMES.get(key, key)}: {'탈락' if dropped else '남음'}{note}")
    return lines + [""]


def _power(p):
    lot, gate = p["lottery_avoid"], p["ma_gate"]
    lines = ["## 필요 기간", ""] + _head(p)
    lines.append("### 후보 ① 복권형 회피: 효과 크기별 필요 개월 수")
    table = lot["required_months"]
    if table is None:
        lines += ["", "필요 기간을 추정하지 못했다(월 관측 없음).", ""]
    else:
        lines += ["", f"복귀 {lot['reentry_pct']}, 월 표준편차(재추출 표준오차에서 되돌린 값) {_pct(lot['sd_monthly'])}, "
                      f"월 관측 {lot['n_months']}개 기준(한쪽 2.5%, 검정력 80%, 정규 근사).", "",
                  "| 가정한 연 초과수익 | 필요 개월 수 | 약 몇 년 |", "|---|---|---|"]
        for effect, months in table.items():
            lines.append(f"| {_pct(float(effect), 0)} | {months}개월 | {months / 12:.1f}년 |")
        lines += ["", "필요 개월 수는 앞으로 새로 쌓일 개월 수이며 비용 2배 조건은 반영하지 않았다.", ""]
    lines += ["5년(60개월) 이상이면 잠그기 전에 다시 정한다.", "",
              "### 후보 ② 10개월 평균 게이트",
              f"- 큰 하락 {gate['big_drop_episodes']}번, 연 {gate['episodes_per_year']:.2f}번 (거래일 {gate['n_days']}일 기준), 전환 {gate['switches']}번",
              _two_drops(gate["episodes_per_year"]),
              "- 고점에서 회복까지를 한 구간으로 세므로 한 구간이 수년 이어질 수 있다", ""]
    return lines


def _two_drops(rate):
    """큰 하락 2번을 보는 데 걸리는 대략의 햇수(2 / 연 빈도). 빈도가 0이면 자료 없음."""
    if not rate:
        return f"- 큰 하락 2번을 보려면: {NO_DATA}"
    return f"- 큰 하락 2번을 보려면 약 {2 / rate:.1f}년"


def write_report(out_dir, payloads: dict) -> Path:
    """있는 단계만 학습·예행연습·필요 기간 순서로 report.md 를 쓰고 경로를 돌려준다."""
    lines = [FIRST_LINE, "", "## 한계", ""] + [f"- {item}" for item in LIMITS] + [""]
    for stage, render in (("train", _train), ("rehearsal", _rehearsal), ("power", _power)):
        if stage in payloads:
            lines += render(payloads[stage])
    path = Path(out_dir) / "report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path
