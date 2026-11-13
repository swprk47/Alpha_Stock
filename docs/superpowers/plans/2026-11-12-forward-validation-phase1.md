# 전진 검증 1단계(엔진·보정·과거 실행) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 월 단위 후보 2개(① 복권형 종목 회피, ② 지수 이동평균 게이트)를 과거 일봉으로 돌려 학습·예행연습·필요 기간 보고서를 내는 `backtest/forward/` 도구를 만든다(설계서 6절의 1단계).

**Architecture:** 일봉 프레임 → 월말 신호(후보별) → 월별 목표 비중 → 교체일 시가 체결 엔진(일별 가치·회전율·비용) → 월 묶음 재추출 통계 → 단계별 JSON과 보고서. 계산 함수는 프레임만 받고, 네이버 호출과 파일 입출력은 `run.py`에서만 한다. 잠금·스냅샷·판정(2단계)은 이 계획에 없다.

**Tech Stack:** Python, pandas, numpy, pytest. 새 의존성 없음.

**Spec:** `docs/superpowers/specs/2026-11-10-forward-validation-design.md` (이하 "설계서")

## Global Constraints

- 새 파일은 `backtest/forward/`와 `tests/test_bt_fw_*.py`에만 만든다. `backend/`, `strategy.py`, `frontend/`, 기존 `backtest/*.py`·`backtest/analysis/*.py`·`backtest/improve/*.py`는 **수정 금지**(import만).
- 브랜치는 `feat/forward-validation`(main 기준). main 직접 수정·push 금지. push와 PR은 사용자 승인 뒤에만.
- **사용자가 "진행해"라고 한 Task만 구현한다.** Task 하나 = 커밋 하나. 끝나면 `pytest -q`(저장소 루트) 전체 통과를 확인하고 결과를 보고한다. 앱 코드 변경이 없어 프론트 문법검사는 해당 없음.
- 테스트는 네이버에 접속하지 않는다(가짜 함수 주입). 실제 일봉 받기는 Task 10에서만 한다.
- `backend/data/users/`는 열지도 커밋하지도 않는다. `backtest/results/`·`backtest/cache/`는 커밋 제외(이미 `.gitignore`).
- 모듈 docstring과 주석은 한국어(기존 `backtest/` 관례). 커밋 메시지는 영어 `feat(backtest-forward): ...` 형식이고 끝에 `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`.
- 모든 보고서의 첫 줄: `이 보고서는 투자 권유가 아니며, 이 결과만으로 실계좌 규칙을 바꾸면 안 된다.` 한계는 결과보다 먼저 쓴다.
- 신호일 t의 계산은 t까지의 일봉만 쓴다. 기존 `prepare_frame`(분할 감지에 미래 봉 사용)은 쓰지 않는다.
- 설계서의 고정 값: 제외 20%, 복귀 완충 후보 {20%, 30%}, 최소 거래일 15, 이동평균 10개월, 자료 이상 ±31%, 슬리피지 0.1%, 비용 배수 1·1.5·2, 재추출 20,000회·시드 20261110, 묶음 3개월·63거래일, 큰 하락 15%, 학습 끝 2021-12-31, 예행연습 시작 2022-01-01.
- 설계서 9절의 `calendar.py`는 표준 라이브러리 이름과 겹쳐 `months.py`로 만든다. 설계서 9절에 없는 `evaluate.py`를 추가한다(신호→비중→엔진→통계를 잇는 조각).

## Review Focus

1. **일봉에 빈 날이 있는 종목**(달력에는 있는데 그 종목 행이 없는 날): 엔진이 멈추지 않고 그 종목 가치를 그대로 둔다 → Task 5 테스트.
2. **대상 종목이 아주 적은 달**(0~4개): 제외 수가 0이 되고, 대상이 0개면 그달은 현금이며 오류가 없다 → Task 3·8 테스트.
3. **종목과 KODEX 200의 거래일이 어긋나는 달**: 겹치는 날만으로 IVOL을 구하고, 겹치는 날이 15일 미만이면 그 종목은 그달 대상에서 빠진다 → Task 3 테스트.
4. **캐시에 일봉이 없거나 짧은 종목**: 건너뛰고 보고서에 수를 적는다. KODEX 200이 없으면 분명한 오류로 끝낸다 → Task 9 테스트.
5. **단계 순서를 어긴 실행**(train 없이 rehearsal·power): 무엇을 먼저 해야 하는지 알려 주고 종료 코드 2로 끝낸다 → Task 9 테스트.

## File Structure

| 파일 | 책임 |
|---|---|
| `backtest/forward/__init__.py` | 빈 파일 |
| `backtest/forward/registry.py` | 후보 등록표와 고정 상수, 등록표 지문 |
| `backtest/forward/costs.py` | 연도별 매도세율, 비용 배수, ETF 구분 |
| `backtest/forward/frames.py` | 일봉 → 일간 수익률·거래정지·자료 이상 표시(미래 봉 없음), 자르기 |
| `backtest/forward/months.py` | 월말 신호일과 교체일 |
| `backtest/forward/lottery.py` | ① MAX·IVOL·합성 순위·제외와 복귀 |
| `backtest/forward/gate.py` | ② 10개월 평균 신호 |
| `backtest/forward/engine.py` | 목표 비중 → 일별 수익률·회전율·비용, 월 수익률 |
| `backtest/forward/stats.py` | 재추출 통계, 최대 낙폭, 큰 하락 |
| `backtest/forward/power.py` | 필요 개월 수, 큰 하락 빈도 |
| `backtest/forward/evaluate.py` | 후보별 한 구간 평가 |
| `backtest/forward/report.py` | 보고서 쓰기 |
| `backtest/forward/run.py` | `--stage train|rehearsal|power` 명령, 파일 입출력 |
| `tests/bt_fw_helpers.py` | 테스트용 일봉 만들기 |

---

### Task 1: 등록표와 비용

**Files:**
- Create: `backtest/forward/__init__.py`, `backtest/forward/registry.py`, `backtest/forward/costs.py`
- Test: `tests/test_bt_fw_registry.py`, `tests/test_bt_fw_costs.py`

**Interfaces:**
- Produces (`registry.py`):
  - `@dataclass(frozen=True) LotterySpec(name="lottery_avoid", exclude_pct=0.20, reentry_choices=(0.20, 0.30), min_days=15)`
  - `@dataclass(frozen=True) GateSpec(name="ma_gate", months=10)`
  - `LOTTERY = LotterySpec()`, `GATE = GateSpec()`, `BENCHMARK = "069500"`
  - 상수: `BAD_RETURN = 0.31`, `SLIPPAGE = 0.001`, `COST_MULTIPLIERS = (1.0, 1.5, 2.0)`, `DRAWS = 20_000`, `SEED = 20261110`, `BLOCK_MONTHS = 3`, `BLOCK_DAYS = 63`, `N_CANDIDATES = 2`, `ALPHA = 0.05`, `MIN_EFFECT_ANNUAL = 0.01`, `BIG_DROP = 0.15`, `TRAIN_END = "2021-12-31"`, `REHEARSAL_START = "2022-01-01"`
  - `fingerprint() -> str`: 위 값 전체를 정렬된 JSON으로 만든 sha256 16진 문자열
- Produces (`costs.py`):
  - `sell_tax_rate(day) -> float` (`day`는 `datetime.date` 또는 `pd.Timestamp`)
  - `@dataclass(frozen=True) CostModel(multiplier: float = 1.0)`
    - `buy_rate() -> float` = `(config.BUY_FEE_RATE + SLIPPAGE) * multiplier`
    - `sell_rate(day, *, etf: bool) -> float` = `(config.SELL_FEE_RATE + (0 if etf else sell_tax_rate(day)) + SLIPPAGE) * multiplier`
  - 세율은 `config.SELL_TAX_RATE`를 쓰지 않는다(설계서 4절 표가 출처). 원 단위 절사는 하지 않는다(비율 계산).

- [ ] **Step 1: 실패하는 테스트 쓰기**

```python
# tests/test_bt_fw_registry.py
from backtest.forward import registry as r

def test_registry_matches_design_doc():
    assert (r.LOTTERY.name, r.LOTTERY.exclude_pct, r.LOTTERY.reentry_choices, r.LOTTERY.min_days) == ("lottery_avoid", 0.20, (0.20, 0.30), 15)
    assert (r.GATE.name, r.GATE.months) == ("ma_gate", 10)
    assert (r.BENCHMARK, r.BAD_RETURN, r.SLIPPAGE, r.COST_MULTIPLIERS) == ("069500", 0.31, 0.001, (1.0, 1.5, 2.0))
    assert (r.DRAWS, r.SEED, r.BLOCK_MONTHS, r.BLOCK_DAYS) == (20_000, 20261110, 3, 63)
    assert (r.N_CANDIDATES, r.ALPHA, r.MIN_EFFECT_ANNUAL, r.BIG_DROP) == (2, 0.05, 0.01, 0.15)
    assert (r.TRAIN_END, r.REHEARSAL_START) == ("2021-12-31", "2022-01-01")

def test_fingerprint_is_stable_and_changes_with_values(monkeypatch):
    first = r.fingerprint()
    assert first == r.fingerprint() and len(first) == 64
    monkeypatch.setattr(r, "BIG_DROP", 0.20)
    assert r.fingerprint() != first
```

```python
# tests/test_bt_fw_costs.py
import datetime as dt
import pytest
from backtest.forward.costs import CostModel, sell_tax_rate

@pytest.mark.parametrize("day, rate", [
    ("2014-08-18", 0.0030), ("2019-05-29", 0.0030), ("2019-05-30", 0.0025), ("2020-12-31", 0.0025),
    ("2021-01-01", 0.0023), ("2022-12-31", 0.0023), ("2023-06-01", 0.0020), ("2024-06-01", 0.0018),
    ("2025-06-01", 0.0015), ("2026-01-01", 0.0020), ("2031-01-01", 0.0020)])
def test_sell_tax_rate_by_trade_date(day, rate):
    assert sell_tax_rate(dt.date.fromisoformat(day)) == pytest.approx(rate)

def test_cost_model_rates_and_multiplier():
    day = dt.date(2024, 6, 3)
    assert CostModel().buy_rate() == pytest.approx(0.00015 + 0.001)
    assert CostModel().sell_rate(day, etf=False) == pytest.approx(0.00015 + 0.0018 + 0.001)
    assert CostModel().sell_rate(day, etf=True) == pytest.approx(0.00015 + 0.001)
    assert CostModel(2.0).sell_rate(day, etf=False) == pytest.approx(2 * (0.00015 + 0.0018 + 0.001))
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_bt_fw_registry.py tests/test_bt_fw_costs.py -q` → Expected: FAIL (`ModuleNotFoundError: backtest.forward`)
- [ ] **Step 3: `registry.py`, `costs.py` 구현** (위 Interfaces 그대로. 세율표는 `(시작일, 세율)` 튜플 목록으로 두고 시작일 이하인 마지막 항목을 고른다)
- [ ] **Step 4: 통과 확인** — Run: 같은 명령 → Expected: PASS. 이어서 `pytest -q` 전체 통과.
- [ ] **Step 5: 커밋** — `git add backtest/forward tests/test_bt_fw_registry.py tests/test_bt_fw_costs.py` / `feat(backtest-forward): candidate registry and the yearly cost model`

---

### Task 2: 일봉 프레임과 월 달력

**Files:**
- Create: `backtest/forward/frames.py`, `backtest/forward/months.py`, `tests/bt_fw_helpers.py`
- Test: `tests/test_bt_fw_frames.py`, `tests/test_bt_fw_months.py`

**Interfaces:**
- Produces (`frames.py`):
  - `prepare(raw: pd.DataFrame) -> pd.DataFrame`: 입력 열 `date, open, high, low, close, volume`. 출력은 날짜 인덱스(중복 날짜는 마지막 것, 오름차순)에 열 `open, high, low, close, volume, halt, ret, bad`.
    - `halt`: 거래량 0이거나 시가·고가·저가·종가 중 0 이하(기존 `prepare_frame`과 같은 규칙)
    - `ret`: 종가 / 직전 행 종가 − 1. 첫 행, 그리고 자기 행이나 직전 행이 `halt`이면 NaN
    - `bad`: `abs(ret) > BAD_RETURN` (NaN은 False)
  - `load_all(codes, cache, *, min_rows=60) -> tuple[dict[str, pd.DataFrame], list[str]]`: `backtest.data.CandleCache`에서 읽어 `prepare`한 프레임과, 없거나 짧아 뺀 코드 목록
  - `truncate(raw_or_frames: dict[str, pd.DataFrame], end) -> dict`: 각 프레임을 `end` 이하 행만 남긴다(행이 없어지면 그 코드는 뺀다). `prepare` 결과에 적용해도 값이 바뀌지 않는다(뒤 행에 의존하는 열이 없다)
- Produces (`months.py`):
  - `@dataclass(frozen=True) Period(signal_day: pd.Timestamp, trade_day: pd.Timestamp)`
  - `periods(calendar: pd.DatetimeIndex) -> list[Period]`: 달마다 마지막 거래일이 신호일, 달력에서 그다음 거래일이 교체일. 다음 거래일이 없는 마지막 달은 넣지 않는다
  - `in_window(all_periods, start, end) -> list[Period]`: `start <= trade_day <= end`
  - `month_rows(frame, signal_day) -> pd.DataFrame`: 신호일과 같은 연·월이고 신호일 이하인 행
- Produces (`tests/bt_fw_helpers.py`):
  - `raw_from_closes(closes, start="2020-01-01", volume=1000) -> pd.DataFrame`: 영업일 달력, 시가=고가=저가=종가
  - `frame_from_closes(closes, start="2020-01-01") -> pd.DataFrame`: `prepare(raw_from_closes(...))`
  - `frame_from_returns(returns, start="2020-01-01", base=10_000.0) -> pd.DataFrame`: 수익률 누적 종가로 만든 프레임

- [ ] **Step 1: 실패하는 테스트 쓰기**

```python
# tests/test_bt_fw_frames.py — 테스트 이름과 단언
def test_prepare_returns_and_flags():
    # closes [100, 110, 0, 121, 200] (세 번째 행은 종가 0 → halt)
    # ret == [nan, 0.10, nan, nan, 200/121-1], halt == [F, F, T, F, F], bad == [F, F, F, F, T]

def test_prepare_drops_duplicate_dates_and_sorts(): ...
def test_truncate_does_not_change_earlier_rows():
    # prepare(raw 전체)의 앞 10행 == prepare(raw 앞 10행) (모든 열)
def test_load_all_skips_missing_and_short(tmp_path):
    # 캐시에 A(100행), B(10행) 저장, C 없음 → frames 키 {"A"}, skipped == ["B", "C"]
```

```python
# tests/test_bt_fw_months.py
def test_periods_use_last_trading_day_and_next_trading_day():
    cal = pd.bdate_range("2020-01-01", "2020-03-31")
    ps = periods(cal)
    assert [(p.signal_day.date().isoformat(), p.trade_day.date().isoformat()) for p in ps] == [
        ("2020-01-31", "2020-02-03"), ("2020-02-28", "2020-03-02")]   # 3월은 다음 거래일이 없어 빠진다

def test_in_window_filters_by_trade_day(): ...
def test_month_rows_stops_at_signal_day_and_month():
    # 신호일이 2020-02-28이면 2월 행만, 신호일 뒤 행 없음
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_bt_fw_frames.py tests/test_bt_fw_months.py -q` → FAIL
- [ ] **Step 3: 구현**
- [ ] **Step 4: 통과 확인** — 같은 명령 PASS, `pytest -q` 전체 통과
- [ ] **Step 5: 커밋** — `feat(backtest-forward): daily frames without look-ahead and the month calendar`

---

### Task 3: 후보 ① 신호 (MAX·IVOL·제외와 복귀)

**Files:**
- Create: `backtest/forward/lottery.py`
- Test: `tests/test_bt_fw_lottery.py`

**Interfaces:**
- Consumes: `frames.prepare` 결과 프레임, `months.month_rows`, `registry.LOTTERY`
- Produces:
  - `month_stats(frame, bench, signal_day, *, min_days=15) -> tuple[float, float] | None`: `(max_ret, ivol)`. None인 경우: 신호일 행이 없음, 신호일이 `halt`, 그달에 `bad` 행이 있음, 종목과 `bench` 모두 `ret`이 유효한 날이 `min_days` 미만
    - `max_ret`: 그달 유효한 `ret`의 최댓값
    - `ivol`: 유효한 날의 종목 `ret`을 같은 날 `bench` `ret`에 절편 포함 최소제곱 회귀한 잔차의 표준편차(`ddof=2`). `bench` `ret`의 분산이 0이면 종목 `ret`의 표준편차(`ddof=1`)
  - `composite(stats: dict[str, tuple[float, float]]) -> dict[str, float]`: MAX와 IVOL 각각의 백분위 순위(`rank(method="average") / n`)의 평균
  - `select(scores: dict[str, float], prev_excluded: set[str], order: list[str], *, exclude_pct, reentry_pct) -> tuple[list[str], set[str]]`: `(held, excluded)`
    - 정렬: 점수 내림차순, 같으면 `order`에서 앞선 코드가 먼저
    - `n_ex = floor(n * exclude_pct)`, `n_re = floor(n * reentry_pct)`
    - `excluded` = 앞 `n_ex`개 ∪ (`prev_excluded` ∩ 앞 `n_re`개). `held` = 나머지(`order` 순서)

- [ ] **Step 1: 실패하는 테스트 쓰기**

```python
def test_month_stats_matches_hand_calculation():
    # 종목 ret = 2*bench_ret + e, e는 +0.01/-0.01 교대 20일 → ivol == pytest.approx(std(e 잔차, ddof=2)), max_ret == max(ret)
def test_month_stats_ignores_days_after_signal_day():
    # 신호일 뒤 행을 바꿔도 결과가 같다
def test_month_stats_none_when_halted_on_signal_day(): ...
def test_month_stats_none_when_bad_return_in_month(): ...
def test_month_stats_none_when_fewer_than_min_days_overlap_with_bench():
    # 종목 20일, bench는 그중 10일만 → None
def test_month_stats_flat_bench_uses_plain_std(): ...
def test_composite_is_mean_of_percentile_ranks():
    # stats = {"A": (0.01, 0.01), "B": (0.02, 0.03), "C": (0.03, 0.02)} → {"A": 1/3, "B": (2/3+1)/2, "C": (1+2/3)/2}
def test_select_excludes_top_20_percent():
    # 점수 10개(0.1..1.0) → excluded == {최고 2개}, held 8개가 order 순서
def test_select_reentry_buffer_keeps_previously_excluded():
    # 이전에 제외된 종목이 이번에 3위(상위 30% 안) → 계속 제외, 4위면 복귀
def test_select_no_buffer_when_reentry_equals_exclude(): ...
def test_select_ties_broken_by_listing_order(): ...
def test_select_small_universe_excludes_nobody():
    # 종목 4개 → n_ex == 0 → excluded == set(), 빈 dict → ([], set())
```

- [ ] **Step 2: 실패 확인** — `pytest tests/test_bt_fw_lottery.py -q` → FAIL
- [ ] **Step 3: 구현**
- [ ] **Step 4: 통과 확인** — PASS, `pytest -q` 전체 통과
- [ ] **Step 5: 커밋** — `feat(backtest-forward): lottery-avoidance signal (MAX, IVOL, exclusion buffer)`

---

### Task 4: 후보 ② 신호 (10개월 평균 게이트)

**Files:**
- Create: `backtest/forward/gate.py`
- Test: `tests/test_bt_fw_gate.py`

**Interfaces:**
- Consumes: `months.Period`, KODEX 200 프레임
- Produces: `gate_states(bench: pd.DataFrame, all_periods: list[Period], *, months=10) -> dict[pd.Timestamp, bool]`: 신호일 → 다음 달 보유 여부(True=보유). 그 신호일까지의 월말 종가(신호일 포함) 최근 `months`개의 평균보다 신호일 종가가 낮으면 False. 월말 종가가 `months`개 미만이면 True

- [ ] **Step 1: 실패하는 테스트 쓰기**

```python
def test_gate_holds_until_ten_month_ends_exist(): ...        # 앞 9개 신호일은 모두 True
def test_gate_goes_to_cash_below_average_and_back():
    # 월말 종가 100이 10번, 그다음 90 → False, 그다음 130 → True
def test_gate_equal_to_average_holds(): ...                  # 종가 == 평균이면 True
def test_gate_ignores_data_after_signal_day(): ...
```

- [ ] **Step 2: 실패 확인** — `pytest tests/test_bt_fw_gate.py -q` → FAIL
- [ ] **Step 3: 구현**
- [ ] **Step 4: 통과 확인** — PASS, `pytest -q` 전체 통과
- [ ] **Step 5: 커밋** — `feat(backtest-forward): ten-month moving-average gate signal`

---

### Task 5: 월 단위 엔진

**Files:**
- Create: `backtest/forward/engine.py`
- Test: `tests/test_bt_fw_engine.py`

**Interfaces:**
- Consumes: `costs.CostModel`, 프레임
- Produces:
  - `@dataclass PortfolioResult(daily: pd.Series, turnover: pd.Series, cost: pd.Series)`: `daily`는 달력 날짜 인덱스의 일간 수익률, `turnover`·`cost`는 교체일 인덱스(가치 대비 비율)
  - `run_portfolio(frames, calendar: pd.DatetimeIndex, targets: dict[pd.Timestamp, dict[str, float]], cost: CostModel, *, start, end, etf_codes=frozenset()) -> PortfolioResult`: `targets`는 교체일 → 목표 비중(합이 1이면 전액 투자, 빈 dict이면 현금)
  - `monthly_returns(daily: pd.Series, trade_days: list[pd.Timestamp]) -> pd.Series`: 이웃한 교체일 쌍 `[t_k, t_{k+1})`의 일간 수익률을 복리로 묶은 값, 인덱스 `t_k`. 마지막 교체일 뒤 구간은 넣지 않는다

**알고리즘(시그니처와 테스트만으로 정해지지 않는 부분):** 가치 1.0 현금으로 시작한다. `start`~`end`의 달력 날짜 d마다:

1. **시가 단계(d가 `targets`의 키일 때만)**
   - 보유 종목 중 d에 행이 있고 `halt`가 아닌 것: `가치 *= 시가_d / 마지막 가격`, 마지막 가격 = 시가
   - `V = 현금 + 보유 가치 합`. d에 행이 없거나 `halt`인 보유 종목은 **묶인 종목**(사고팔지 않고 가치 유지)
   - 목표 종목 중 d에 행이 있고 `halt`가 아닌 것만 **거래 가능 목표**. `S = 목표 비중 합`, `W = 거래 가능 목표의 비중 합`
   - 종목 c의 목표 가치 = `(V − 묶인 가치 합) * S * w_c / W` (W가 0이면 모두 0). 목표에 없는 거래 가능 보유 종목의 목표 가치는 0
   - `delta_c = 목표 가치 − 현재 가치`. 비용 = `매수 합 * buy_rate() + Σ(매도액 * sell_rate(d, etf=c in etf_codes))`
   - `turnover[d] = max(매수 합, 매도 합) / V`, `cost[d] = 비용 / V`
   - delta를 적용한 뒤 모든 보유 가치와 현금에 `(V − 비용) / V`를 곱한다. 새로 산 종목의 마지막 가격 = 시가
2. **종가 단계(매일)**
   - 보유 종목 중 d에 행이 있고 `halt`가 아닌 것: `가치 *= 종가_d / 마지막 가격`, 마지막 가격 = 종가
   - 보유 종목의 프레임 마지막 날짜가 d보다 앞이면(일봉이 끊김): `현금 += 가치 * (1 − sell_rate(d, etf))`, 보유에서 뺀다
   - `daily[d] = V_종가 / 전날 V_종가 − 1` (첫날의 전날 값은 1.0)

- [ ] **Step 1: 실패하는 테스트 쓰기**

```python
def test_buy_and_hold_single_stock_pays_buy_cost_once():
    # 종가가 매일 +1%인 종목 1개, targets = {첫날: {"A": 1.0}}, CostModel() →
    # 첫날 daily == (1 - buy_rate) * (종가/시가) - 1, 이후 daily == 0.01, turnover[첫날] == 1.0
def test_equal_weight_rebalance_turnover_and_cost():
    # A는 두 배, B는 그대로 → 두 번째 교체일에 같은 비중으로 되돌릴 때 turnover == 매도액/V, cost == 매수*buy_rate + 매도*sell_rate
def test_move_to_cash_and_back():
    # targets = {t0: {"A": 1.0}, t1: {}, t2: {"A": 1.0}} → t1 이후 t2 전까지 daily == 0.0
def test_etf_sell_has_no_tax(): ...                           # etf_codes={"A"}일 때 매도 비용에 세금 없음
def test_halted_stock_is_frozen_and_others_fill_the_rest():
    # 교체일에 A가 halt → A 가치 유지, 나머지 목표가 (V − A 가치) 안에서 비율대로
def test_missing_row_for_held_stock_does_not_crash():          # Review Focus 1
    # 달력에는 있는데 A 행이 없는 날 → 그날 A 가치 그대로, daily는 다른 종목만 반영
def test_delisted_stock_is_sold_at_last_close():
    # A 프레임이 중간에 끝남 → 다음 달력 날짜에 현금이 A 가치 * (1 − sell_rate)만큼 늘고 보유에서 빠진다
def test_cost_multiplier_scales_costs(): ...
def test_monthly_returns_compound_between_trade_days():
    # daily 0.01이 5일, 교체일 [d0, d3] → 값 1개: 1.01**3 - 1 (인덱스 d0)
```

- [ ] **Step 2: 실패 확인** — `pytest tests/test_bt_fw_engine.py -q` → FAIL
- [ ] **Step 3: 구현** (위 알고리즘 그대로)
- [ ] **Step 4: 통과 확인** — PASS, `pytest -q` 전체 통과
- [ ] **Step 5: 커밋** — `feat(backtest-forward): monthly rebalancing engine with turnover and costs`

---

### Task 6: 통계

**Files:**
- Create: `backtest/forward/stats.py`
- Test: `tests/test_bt_fw_stats.py`

**Interfaces:**
- Consumes: `backtest.analysis.bootstrap.block_indices(n_days, block, rng)`, `registry`의 `DRAWS`·`SEED`
- Produces:
  - `@dataclass(frozen=True) Stat(point: float | None, lo: float | None, hi: float | None, p_one: float | None, se: float | None, n: int)`
  - `mean_stat(values, *, block, draws=DRAWS, seed=SEED) -> Stat`: 평균의 점추정, 재추출 평균들의 2.5·97.5 백분위, `p_one = mean(표본 <= 0)`, `se = std(표본, ddof=1)`. 빈 입력이면 모든 값 None, n=0
  - `max_drawdown(daily) -> float`: 일간 수익률 누적 가치의 고점 대비 최대 하락(양수 비율, 하락이 없으면 0.0)
  - `mdd_diff_stat(gate_daily, hold_daily, *, block, draws=DRAWS, seed=SEED) -> Stat`: 점추정 `max_drawdown(hold) − max_drawdown(gate)`. 두 계열을 **같은 위치**로 재추출한다. `p_one = mean(표본 <= 0)`
  - `@dataclass(frozen=True) Episode(peak_day, trough_day, end_day, depth: float)`
  - `drawdown_episodes(daily: pd.Series, threshold: float) -> list[Episode]`: 고점에서 `threshold` 이상 내려간 구간. 고점부터 고점을 회복한 날(또는 계열 끝)까지가 한 구간
  - `window_drawdown(daily: pd.Series, start, end) -> float`: `start`~`end` 구간만 잘라 구한 `max_drawdown`

- [ ] **Step 1: 실패하는 테스트 쓰기**

```python
def test_mean_stat_point_and_one_sided_p():
    # 전부 양수인 값 → p_one == 0.0, 전부 음수 → 1.0, point == 평균
def test_mean_stat_one_sided_p_on_skewed_sample_is_not_half_two_sided(): ...
def test_mean_stat_same_seed_same_result_and_uses_registry_defaults(): ...
def test_mean_stat_empty_input(): ...
def test_max_drawdown_known_series():
    # 일간 [0.10, -0.50, 0.20] → 0.5,  전부 양수 → 0.0
def test_mdd_diff_point_and_paired_resampling():
    # gate가 hold와 같으면 point == 0.0 이고 모든 표본이 0 → lo == hi == 0.0
def test_drawdown_episodes_split_on_recovery():
    # 가치 100→80→100→101→70→(끝) , threshold 0.15 → 구간 2개, depth [0.20, 0.3069...], 두 번째 end_day == 마지막 날
def test_drawdown_episodes_ignores_small_dips(): ...           # 10% 하락은 구간 아님
def test_window_drawdown_uses_only_the_window(): ...
```

- [ ] **Step 2: 실패 확인** — `pytest tests/test_bt_fw_stats.py -q` → FAIL
- [ ] **Step 3: 구현** (재추출 반복은 numpy 배열 연산으로. 20,000회 × 수천 일의 낙폭 계산이 느리면 Step 4에서 시간을 재고 보고한다)
- [ ] **Step 4: 통과 확인** — PASS, `pytest -q` 전체 통과
- [ ] **Step 5: 커밋** — `feat(backtest-forward): block-bootstrap statistics and drawdown episodes`

---

### Task 7: 필요 기간

**Files:**
- Create: `backtest/forward/power.py`
- Test: `tests/test_bt_fw_power.py`

**Interfaces:**
- Consumes: `stats.Stat`, `stats.Episode`
- Produces:
  - `EFFECTS_ANNUAL = (0.01, 0.02, 0.03, 0.05)`, `Z_ALPHA = 1.959964` (한쪽 2.5%), `Z_POWER = 0.841621` (검정력 80%)
  - `effective_sd(stat: Stat) -> float` = `stat.se * sqrt(stat.n)` (묶음 재추출 표준오차에서 되돌린 월 단위 표준편차)
  - `required_months(sd_monthly: float, effect_annual: float) -> int` = `ceil(((Z_ALPHA + Z_POWER) * sd_monthly / (effect_annual / 12)) ** 2)`
  - `required_table(stat: Stat) -> dict[float, int]`: `EFFECTS_ANNUAL`마다의 개월 수
  - `episodes_per_year(episodes: list, n_days: int) -> float` = `len(episodes) / (n_days / 252)`

- [ ] **Step 1: 실패하는 테스트 쓰기**

```python
def test_required_months_formula():
    # sd_monthly 0.01, effect_annual 0.03 → ceil(((1.959964+0.841621)*0.01/0.0025)**2) == 126
def test_required_months_falls_as_effect_grows(): ...
def test_effective_sd_inverts_standard_error(): ...            # Stat(se=0.002, n=100) → 0.02
def test_required_table_has_all_effect_sizes(): ...
def test_episodes_per_year(): ...                              # 3개, 2520일 → 0.3
```

- [ ] **Step 2: 실패 확인** — `pytest tests/test_bt_fw_power.py -q` → FAIL
- [ ] **Step 3: 구현**
- [ ] **Step 4: 통과 확인** — PASS, `pytest -q` 전체 통과
- [ ] **Step 5: 커밋** — `feat(backtest-forward): required-horizon estimate`

---

### Task 8: 후보별 평가

**Files:**
- Create: `backtest/forward/evaluate.py`
- Test: `tests/test_bt_fw_evaluate.py`

**Interfaces:**
- Consumes: Task 1~7의 모든 Produces
- Produces:
  - `lottery_targets(frames, bench, all_periods, order: list[str], *, reentry_pct) -> tuple[dict, dict, dict]`: `(tilt_targets, base_targets, log)`. 키는 교체일. 신호는 **자료의 첫 달부터** 계산해 제외 상태를 이어 간다(평가 구간은 수익률만 자른다). `base` = 그달 대상 종목 전체 같은 비중, `tilt` = `select`의 `held` 같은 비중. 대상이 0개인 달은 둘 다 `{}`. `log[교체일] = {"signal_day", "eligible": n, "excluded": [...]}`
  - `gate_targets(bench, all_periods) -> tuple[dict, dict]`: `(gate_targets, hold_targets)`. 보유이면 `{BENCHMARK: 1.0}`, 현금이면 `{}`. `hold`는 항상 `{BENCHMARK: 1.0}`
  - `@dataclass LotteryEval(diff: dict[float, Stat], monthly_diff: pd.Series, turnover_tilt: float, turnover_base: float, excluded_mean: float, yearly_diff: dict[int, float], vs_kodex_annual: float, n_months: int)`: `diff`의 키는 비용 배수, 값은 월 차이(회피 − 전체)의 `mean_stat(block=BLOCK_MONTHS)`. `monthly_diff`·`yearly_diff`·`vs_kodex_annual`은 배수 1 기준. `vs_kodex_annual` = (회피의 월 수익률 평균 − KODEX 200 계속 보유의 월 수익률 평균) × 12
  - `evaluate_lottery(frames, bench, calendar, order, *, start, end, reentry_pct) -> LotteryEval`
  - `@dataclass GateEval(mdd_gate: float, mdd_hold: float, mdd_diff: Stat, return_given_up_annual: float, vol_gate: float, vol_hold: float, switches: int, episodes: list[dict])`: `episodes`의 항목은 `{"peak_day", "end_day", "depth_hold", "depth_gate"}`(계속 보유 기준 구간, 게이트는 같은 구간의 `window_drawdown`). `mdd_diff`는 `mdd_diff_stat(block=BLOCK_DAYS)`. `switches`는 평가 구간 안에서 상태가 바뀐 횟수. 변동성은 일간 표준편차 × √252
  - `evaluate_gate(bench, calendar, *, start, end) -> GateEval`
  - 엔진 호출 시 KODEX 200은 `etf_codes={BENCHMARK}`

- [ ] **Step 1: 실패하는 테스트 쓰기**

```python
def test_lottery_targets_base_is_all_eligible_and_tilt_drops_top_fifth():
    # 조용한 종목 8개 + 급등락 종목 2개(같은 달에 +20%/-15% 하루씩), 24개월 →
    # 매 교체일 base 10개 각 0.1, tilt 8개 각 0.125, 급등락 2개는 tilt에 없다
def test_lottery_targets_state_carries_over_from_first_month(): ...   # 평가 구간 시작 전에 제외된 종목이 완충으로 계속 제외
def test_lottery_targets_month_with_no_eligible_stock_is_cash():       # Review Focus 2
def test_evaluate_lottery_positive_when_lottery_stocks_lose():
    # 급등락 종목이 다음 달에 꾸준히 내리도록 만든 합성 자료 → diff[1.0].point > 0, diff[2.0].point < diff[1.0].point
def test_evaluate_lottery_reports_turnover_and_yearly(): ...
def test_gate_targets_cash_when_below_average(): ...
def test_evaluate_gate_reduces_drawdown_in_long_decline():
    # 12개월 상승 뒤 12개월 하락(-40%) → mdd_gate < mdd_hold, mdd_diff.point > 0, switches >= 1, episodes 1개에 depth_gate < depth_hold
def test_evaluate_gate_no_switch_when_always_rising(): ...             # switches == 0, mdd_diff.point == 0
def test_signal_days_never_use_later_data():
    # end 뒤의 일봉을 바꿔도 evaluate_lottery·evaluate_gate 결과가 같다
```

- [ ] **Step 2: 실패 확인** — `pytest tests/test_bt_fw_evaluate.py -q` → FAIL
- [ ] **Step 3: 구현**
- [ ] **Step 4: 통과 확인** — PASS, `pytest -q` 전체 통과
- [ ] **Step 5: 커밋** — `feat(backtest-forward): per-candidate evaluation over one window`

---

### Task 9: 단계 명령과 보고서

**Files:**
- Create: `backtest/forward/run.py`, `backtest/forward/report.py`
- Test: `tests/test_bt_fw_run.py`, `tests/test_bt_fw_report.py`

**Interfaces:**
- Consumes: `backtest.data.CandleCache`·`download_candles`·`fetch_listing`, `backtest.analysis.run.load_listing(cache_dir, fetch, refresh=)`, `backtest.run.default_fetch_candles`, Task 1~8
- Produces:
  - `main(argv=None, *, fetch_listing=..., fetch_candles=...) -> int`. 인자: `--stage {train,rehearsal,power}`(필수), `--cache`(기본 `backtest/cache`), `--out`(기본 `backtest/results/forward`), `--refresh`, `--max-codes`
  - 단계별 동작과 출력 파일(`--out` 아래):

| 단계 | 구간 | 하는 일 | 출력 |
|---|---|---|---|
| `train` | 프레임을 `TRAIN_END`에서 자른 뒤(`frames.truncate`) 처음~`TRAIN_END` | ①을 `reentry_choices` 2개로 평가해 배수 1의 차이 평균이 큰 쪽을 고른다(같으면 0.30). ②를 평가한다 | `train.json` |
| `rehearsal` | `REHEARSAL_START`~마지막 교체일 전날 | `train.json`의 완충 폭으로 ①, 그리고 ②를 평가한다. `drop`: ①은 배수 1 차이 평균 ≤ 0, ②는 최대 낙폭 차이 ≤ 0 | `rehearsal.json` |
| `power` | 처음~마지막 교체일 전날 | ①의 `required_table`, ②의 큰 하락 수와 `episodes_per_year` | `power.json` |

  - 달력은 KODEX 200 프레임의 인덱스다. "처음"은 `months.periods`의 첫 교체일, "마지막 교체일"은 마지막 `Period`의 교체일이다. 종목 순서(`order`)는 상장 목록 순서다
  - 세 단계 모두 실행 뒤 `report.md`를 다시 쓴다(있는 JSON만으로). `rehearsal`·`power`는 `train.json`이 없으면 `먼저 --stage train 을 실행해야 한다`를 stderr에 쓰고 2를 돌려준다
  - KODEX 200 프레임이 없으면 `KODEX 200(069500) 일봉이 없다`를 쓰고 2를 돌려준다
  - 각 JSON에 공통으로 넣는 값: `stage`, `registry`(`fingerprint()`), `window`(시작·끝), `n_listed`, `n_frames`, `skipped`(코드 목록), `first_date`, `last_date`
  - `report.write_report(out_dir, payloads: dict[str, dict]) -> Path`: 첫 줄은 Global Constraints의 문구, 그다음 `## 한계`(설계서 10절 목록 전체), 그다음 있는 단계만 `## 학습`, `## 예행연습`, `## 필요 기간`. 예행연습 절에는 `이미 본 기간이라 통과해도 증거가 아니다`를 적는다. 필요 기간 절에는 효과 크기별 개월 수 표와 "5년(60개월) 이상이면 잠그기 전에 다시 정한다"를 적는다

- [ ] **Step 1: 실패하는 테스트 쓰기**

```python
# tests/test_bt_fw_run.py — 합성 종목 12개 + KODEX 200, 2014-08~2024-12 영업일, 가짜 fetch 주입(네이버 접속 없음)
def test_train_writes_selection_and_never_reads_after_train_end(tmp_path):
    # train 실행 → train.json에 reentry_pct ∈ {0.2, 0.3}, window 끝 == "2021-12-31"
    # 2022년 이후 일봉을 바꾼 캐시로 다시 실행해도 train.json의 수치가 같다
def test_rehearsal_and_power_require_train(tmp_path, capsys):        # Review Focus 5
    # train 없이 rehearsal → 반환 2, stderr에 "먼저 --stage train"
def test_rehearsal_uses_trained_buffer_and_sets_drop_flags(tmp_path): ...
def test_power_writes_required_months_table(tmp_path): ...            # 키 0.01, 0.02, 0.03, 0.05
def test_missing_or_short_candles_are_skipped_and_counted(tmp_path): # Review Focus 4
    # 12개 중 2개는 캐시에 없고 fetch도 None → 실행은 끝까지, skipped에 2개
def test_missing_benchmark_fails_clearly(tmp_path, capsys):           # 반환 2, "KODEX 200"
def test_full_sequence_writes_report(tmp_path):
    # train → rehearsal → power 뒤 report.md 존재

# tests/test_bt_fw_report.py
def test_report_first_line_and_limits_before_results(tmp_path):
    # 첫 줄이 고정 문구, "## 한계"의 위치 < "## 학습"의 위치
def test_report_only_includes_existing_stages(tmp_path): ...
def test_report_marks_rehearsal_as_already_seen(tmp_path): ...
```

- [ ] **Step 2: 실패 확인** — `pytest tests/test_bt_fw_run.py tests/test_bt_fw_report.py -q` → FAIL
- [ ] **Step 3: 구현**
- [ ] **Step 4: 통과 확인** — PASS, `pytest -q` 전체 통과
- [ ] **Step 5: 커밋** — `feat(backtest-forward): train/rehearsal/power stages and the report`

---

### Task 10: 실제 자료 실행과 기록 (코드 변경 없음)

**Files:**
- Modify: `PROGRESS.md` (새 절 `0-8. 전진 검증 1단계` 추가)

- [ ] **Step 1: 실제 실행** — 저장소 루트에서 차례로 실행한다(일봉을 새로 받으면 수 분 걸린다. 2분을 넘기면 백그라운드로).

```bash
python -m backtest.forward.run --stage train
python -m backtest.forward.run --stage rehearsal
python -m backtest.forward.run --stage power
```

Expected: 각 명령이 0으로 끝나고 `backtest/results/forward/report.md`가 생긴다. 소요 시간을 잰다.

- [ ] **Step 2: 결과 점검** — 보고서에서 다음을 확인하고 이상하면 원인을 찾는다(고치려면 사용자에게 먼저 알린다): 받은 종목 수와 건너뛴 수, ①의 월 회전율이 0~100% 범위, 대상 종목 수가 달마다 급변하지 않음, ②의 신호 전환 횟수, 큰 하락 구간이 알려진 시기(2020년 초, 2022년)와 맞음.
- [ ] **Step 3: 사용자에게 보고** — 학습에서 고른 완충 폭, 예행연습의 `drop` 여부, 효과 크기별 필요 개월 수, 큰 하락 빈도를 표로 보고한다. 한계와 "투자 권유 아님"을 같이 말한다. **판정일은 사용자가 정한다**(설계서 6절 4번). 필요 기간이 60개월 이상이면 그 사실을 먼저 말한다.
- [ ] **Step 4: `PROGRESS.md` 기록** — 도구 위치, 실행 명령, 실행일, 핵심 수치, 사용자 결정(판정일 또는 보류), 남은 일(2단계)을 적는다.
- [ ] **Step 5: 커밋** — `docs: record the forward-validation phase 1 run in PROGRESS.md`
- [ ] **Step 6: push·PR은 사용자 승인 뒤** — 승인하면 `git push -u origin feat/forward-validation` 후 PR(base `main`)을 만든다. PR 본문 끝에 `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

---

## 이 계획에 없는 것 (2단계 계획에서 다룬다)

`judge.py`, `lock.py`, `snapshot.py`, 등록 파일, 예약 워크플로, 비공개 자료 저장소 설정, GitHub 서버의 네이버 접속 시험, 중간 보고. 판정일이 정해진 뒤 따로 계획을 쓴다.
