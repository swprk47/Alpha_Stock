# 스윙 추천 개선 후보 검증 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사전 등록한 개선 후보 8개를 학습 기간에서 선별하고 검증 기간에서 딱 한 번 평가해 합격/유망/불합격을 내는 `backtest/improve/` 도구를 만든다.

**Architecture:** 후보 레지스트리, 슬롯 제한 계좌(K=2), 날짜 블록 부트스트랩 통계(한쪽 p), 후보 평가, 학습 선별·판정, 단계 잠금, 보고서/CLI로 나눈다. 기존 `backtest/`와 `backtest/analysis/`는 수정하지 않고 재사용한다. 앱 코드는 import만 한다.

**Tech Stack:** Python, numpy, pandas, pytest (새 의존성 없음 — z 값은 stdlib `statistics.NormalDist`)

**Spec:** `docs/superpowers/specs/2026-11-03-backtest-improve-design.md` (3차본, 커밋 4e519ef)

## Global Constraints

- 브랜치 `feat/backtest-improve`. **`backend/`(특히 `strategy.py`)와 기존 `backtest/*.py`, `backtest/analysis/*.py` 수정 금지**(import만). `main`·PR 브랜치에 직접 커밋 금지.
- 새 외부 의존성 금지(numpy·pandas만). SQLite·프론트 변경 없음.
- 일봉은 다시 받지 않는다(`backtest/cache/` 재사용). `backend/data/users/`는 열거나 커밋하지 않는다.
- 결과 폴더 `backtest/results/improve/`는 커밋하지 않는다. **`selection.json`은 사용자 승인 뒤에만** 저장소에 커밋한다.
- 고정값: 예산 200,000원, 진입 `next_open`, 슬리피지 0.1%, 슬롯 K=2, 추천 상위 3, 블록 20거래일, 판정 통계 재추출 20,000회, 시드 20261103, `alpha_adj = 0.05 / N`, 학습 끝 `TRAIN_END`=2021-12-31(`backtest.analysis.panel.TRAIN_END`), 연환산 252.
- 후보 8개(F1, E1~E3, S1~S4)와 판정 규칙은 설계서 4·6절 그대로. 시험 도중 후보·규칙 변경 금지. 판정 라벨은 합격/유망/불합격만 쓰고 "효과 없음"은 쓰지 않는다.
- **검증 단계 실행(Task 10)은 한 번만.** Task 9(학습 실행) 뒤에는 사용자에게 선별 결과를 보여주고 승인을 받은 다음에만 진행한다.
- 한 작업 = 한 커밋(테스트 포함). 끝나면 `pytest -q` 전체 통과. 커밋 메시지 끝에 `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- 테스트는 `tests/test_bt_im_<모듈>.py`, 도우미는 `tests/bt_helpers.py`(`make_frame`, `trending_rows`, `make_trade`, `listing`, `make_raw`)를 재사용.

## Review Focus

1. **미래 정보 누수:** S1~S4 순위와 F1 조건은 날짜 t까지의 일봉만 쓴다(t 이후 행을 바꿔도 t의 결과 불변).
2. **학습/검증 오염:** 학습은 원시 일봉을 `TRAIN_END`에서 자른 뒤 `prepare_frame`을 다시 적용한 프레임만 쓰고, `TRAIN_END` 이후 데이터를 바꿔도 `selection.json`이 동일하다. test 단계는 코드·데이터·설정 해시가 다르면 거부한다.
3. **슬롯 규칙:** 청산일이 d 이하이면 슬롯이 비고, 같은 종목 열린 거래가 있으면 건너뛰며, `simulate_trade`가 None이면 슬롯을 쓰지 않고 다음 순위로 넘어간다. 동시 보유가 K를 넘지 않는다.
4. **통계 산술:** 한쪽 p는 `mean(표본 <= 0)`, 유의는 점추정 > 0 이고 p ≤ 0.05/N, 로그성장 초과는 산술 평균과 다르다, MDE는 후보별 자기 SE를 쓴다.
5. **퇴화 입력:** 후보가 하나도 선별되지 않음(N=0), 거래 0건 후보, 분산 0인 통계, 기준선 거래 0건에서 예외 없이 "후보 없음/판정 불가"로 끝난다.

---

### Task 1: 후보 레지스트리 (`backtest/improve/candidates.py`)

**Files:**
- Create: `backtest/improve/__init__.py`, `backtest/improve/candidates.py`
- Test: `tests/test_bt_im_candidates.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) Candidate: name: str; direction: str  # "filter"|"exit"|"signal"|"baseline"; pre_exposed: bool`
  - `REGISTRY: tuple[Candidate, ...]` = F1, E1, E2, E3, S1, S2, S3, S4 (이 순서). 사전 노출(`pre_exposed=True`): F1, E1, E2, E3, S4. S1~S3은 False.
  - `BASELINE = Candidate("BASE", "baseline", False)`
  - `DIRECTIONS = ("filter", "exit", "signal")`
  - `by_name(name) -> Candidate` (없으면 `KeyError`)
  - `exit_kwargs(candidate) -> dict` — `simulate_trade` 인자: E1 `{"stop_ratio": 0.95}`, E2 `{"stop_ratio": 0.95, "target_ratio": 1.10, "hold_days": 10}`, E3 `{"stop_ratio": 0.93, "target_ratio": 1.15, "hold_days": 20}`, 그 밖은 `{}`.
  - `@dataclass(frozen=True) Combo: signal: "Candidate | None"; filter: "Candidate | None"; exit: "Candidate | None"`, 속성 `name`(예: `COMBO(S1+F1+E2)`, 없는 방향은 생략), `pre_exposed`(구성 요소 중 하나라도 True), `exit_kwargs()`.
  - `registry_fingerprint() -> str` — 레지스트리(이름·방향·exit 인자·pre_exposed)의 sha256 16진수.

- [ ] **Step 1: 실패하는 테스트 작성** — `test_registry_matches_the_design_document`(이름 순서 `["F1","E1","E2","E3","S1","S2","S3","S4"]`, 방향, `pre_exposed` 집합이 {F1,E1,E2,E3,S4}), `test_exit_kwargs_values`(E1~E3 정확한 값, 나머지 `{}`), `test_by_name_unknown_raises`, `test_combo_name_and_exposure`(`Combo(S1, F1, E2).name == "COMBO(S1+F1+E2)"`, `pre_exposed True`; S1만으로 만든 Combo는 False), `test_fingerprint_changes_when_a_parameter_changes`(`exit_kwargs`가 만드는 값이 바뀌면 지문이 바뀐다는 것을 확인하려고 레지스트리 지문 함수가 인자 표를 포함하는지: 함수 내부 표를 monkeypatch해 다른 값으로 바꾸면 지문이 달라짐).
- [ ] **Step 2:** `pytest tests/test_bt_im_candidates.py -q` → Expected: FAIL(모듈 없음)
- [ ] **Step 3: 구현** — 위 시그니처. 인자 표는 모듈 상수 `_EXIT_TABLE`로 두고 `exit_kwargs`와 `registry_fingerprint`가 같은 표를 쓴다.
- [ ] **Step 4:** 같은 명령 → Expected: 5 passed
- [ ] **Step 5: 커밋** `feat(backtest-improve): pre-registered candidate registry`

---

### Task 2: 부트스트랩 통계 (`backtest/improve/stats.py`)

**Files:**
- Create: `backtest/improve/stats.py`
- Test: `tests/test_bt_im_stats.py`

**Interfaces:**
- Consumes: `backtest.analysis.bootstrap.block_indices(n_days, block, rng)`.
- Produces:
  - 상수 `BLOCK = 20`, `DRAWS = 20_000`, `SEED = 20261103`, `ANNUAL = 252`
  - `@dataclass(frozen=True) Stat: point: float|None, lo: float|None, hi: float|None, p_one: float|None, se: float|None, n_days: int, draws: int` — `p_one`은 한쪽 p(`mean(표본 <= 0)`, 유한 표본만), `se`는 표본 표준편차.
  - `bootstrap_stat(day_stats: np.ndarray, stat_fn, *, block=BLOCK, draws=DRAWS, seed=SEED) -> Stat` — 날짜별 합계 행렬(n_days x k)을 블록 재추출해 `stat_fn(열별 합계)`의 분포를 만든다. 날짜 0개이거나 점추정이 비유한이면 모든 값이 None인 `Stat`.
  - `mean_stat(values, **kw) -> Stat` — 일간 값 배열의 평균(`[값, 1]`의 비율).
  - `ratio_stat(sum_values, counts, **kw) -> Stat` — `Σ값 / Σ건수`(거래당 평균).
  - `log_growth_excess(ret, other, **kw) -> Stat` — 일간 `log1p(ret) - log1p(other)`의 평균 x 252(`other`가 None이면 현금 0). `ret`, `other`는 같은 길이의 배열/Series.
  - `significant(stat: Stat, alpha_adj: float) -> bool` — `point is not None and point > 0 and p_one <= alpha_adj`.
  - `near_threshold(stat, alpha_adj) -> bool` — `p_one`이 문턱의 ±20% 안.
  - `mde(se_train: float, train_days: int, test_days: int, n: int, *, alpha=0.05, power=0.80) -> float | None` — `(z_{1-alpha/n} + z_power) * se_train * sqrt(train_days / test_days)`(`NormalDist().inv_cdf`). `se_train`이 None이거나 일수/ n이 0이면 None.

- [ ] **Step 1: 실패하는 테스트 작성** — `test_same_seed_same_result`, `test_one_sided_p_is_direct_not_half_of_two_sided`(비대칭 표본: 점추정 > 0 이지만 `mean(표본>=0)`가 `mean(표본<=0)`보다 작아지도록 만든 stat_fn으로 `p_one`이 `mean(표본<=0)`과 정확히 같음을 확인), `test_ci_and_se_for_known_mean`(평균 2, 표준편차 1인 400일 → 구간이 점추정을 포함하고 `se` ≈ 1/sqrt(400) 근처 0.03~0.08), `test_log_growth_excess_differs_from_arithmetic`(일간 ±5%/∓5% 번갈아 vs 일정 0%: 산술 평균 차이는 0 근처지만 로그 차이는 음수), `test_log_growth_cash_when_other_is_none`, `test_significant_requires_positive_point_and_small_p`(점추정 음수이고 p가 작으면 False), `test_near_threshold`, `test_mde_known_value`(se=1, train_days=test_days, n=1 → `1.6449 + 0.8416`에 근접; n=4면 더 큼), `test_mde_none_for_missing_se`, `test_block_is_20_and_draws_20000_by_default`(기본 인자 값), `test_empty_returns_none_stat`.
- [ ] **Step 2:** 실행 → Expected: FAIL
- [ ] **Step 3: 구현.** 재추출은 `np.random.default_rng(seed)` 하나를 순차 사용하고 `block_indices`를 재사용.
- [ ] **Step 4:** 실행 → Expected: 11 passed
- [ ] **Step 5: 커밋** `feat(backtest-improve): block-bootstrap statistics with a direct one-sided p`

---

### Task 3: 슬롯 제한 계좌 (`backtest/improve/slots.py`)

**Files:**
- Create: `backtest/improve/slots.py`
- Test: `tests/test_bt_im_slots.py`

**Interfaces:**
- Consumes: `backtest.signals.DayResult/daily_picks`, `backtest.simulate.simulate_trade/Trade`, `backtest.analysis.equity.trade_daily_factors`.
- Produces:
  - `K = 2`, `PICKS = 3`
  - `run_slots(days: list, frames: dict, entry_mode: str, *, bucket: int, k: int = K, slippage_pct: float = 0.1, top_n: int = PICKS, **exit_kwargs) -> list[Trade]` — 날짜순으로 `daily_picks(day, top_n)`를 순위 순서로 훑는다. 건너뛰는 조건: ① 같은 종목의 수락된 거래 중 `exit_date > d`가 있음, ② `exit_date > d`인 수락된 거래가 이미 k개. `simulate_trade`가 None이면 슬롯을 쓰지 않고 다음 순위로. 수락하면 거래 목록에 추가.
  - `slot_account(trades: list, frames: dict, dates: list, k: int = K) -> pd.DataFrame` — `dates` 전체를 인덱스로 컬럼 `ret`(그날 열린 포지션들의 `trade_daily_factors - 1` 합 / k, 없으면 0)와 `open`(그날 열린 포지션 수).
  - `utilisation(account: pd.DataFrame, k: int = K) -> dict` — `{"exposure": 보유 포지션이 있는 날 비율, "avg_slots": (open / k)의 평균}`.

- [ ] **Step 1: 실패하는 테스트 작성** — 합성 프레임(`make_frame(trending_rows(120))` 여러 코드), `Signal`/`DayResult` 직접 구성:
  `test_slot_cap_never_exceeded`(매일 3개 추천·보유 10일 후보에서 어느 날도 열린 포지션이 k를 넘지 않음), `test_skips_when_slots_are_full_then_resumes_after_exit`, `test_same_code_open_trade_is_skipped`, `test_reentry_allowed_when_exit_date_is_not_after_signal_day`(청산일 == d인 같은 종목 신호는 수락됨, `simulate_picks`의 `<=` 경계와 다름을 확인하려고 두 함수 결과를 비교), `test_none_trade_does_not_consume_a_slot`(데이터 끝 근처 신호는 None이라 다음 순위가 수락됨), `test_rank_order_is_respected`(슬롯이 하나만 비면 순위 1이 수락), `test_account_return_is_sum_over_k`(열린 포지션 1개일 때 `ret == (factor-1)/2`, 2개일 때 두 값의 합 / 2), `test_empty_slots_are_cash`, `test_utilisation_values`, `test_empty_days_returns_empty_trades_and_zero_account`.
- [ ] **Step 2:** 실행 → Expected: FAIL
- [ ] **Step 3: 구현**
- [ ] **Step 4:** 실행 → Expected: 10 passed
- [ ] **Step 5: 커밋** `feat(backtest-improve): slot-limited account`

---

### Task 4: 순위·필터 (`backtest/improve/ranking.py`)

**Files:**
- Create: `backtest/improve/ranking.py`
- Test: `tests/test_bt_im_ranking.py`

**Interfaces:**
- Consumes: `backtest.signals.DayResult/Signal/RAW_COLUMNS`, `backtest.analysis.features.compute_features`, `backtest.improve.candidates`.
- Produces:
  - `rank_signals(candidate: Candidate, base_days: list, frames: dict, features: dict, bench: pd.DataFrame, bucket: int) -> list[DayResult]` — S1~S4: 각 `DayResult(date, pool, signals)`에서 `pool`은 그대로 두고 `signals`를 설계서 4절 규칙으로 새로 만든다(`Signal(code, date, 0, 0.0, bucket)`, 순위 순서로 정렬, 통과가 3개 미만이면 그만큼). 제외 조건: 종목 프레임에 해당 날짜 행이 없음, 그 행이 `halt`나 `vol_break`, 필요한 비교 행의 종가가 0 이하이거나 `halt`, NaN. 동률은 풀 순서(안정 정렬).
    - S1: 키 = 종목의 `close_t/close_{t-20}-1` − 벤치의 같은 20행 수익률(각자 자기 프레임 행 기준), 큰 순.
    - S2: 조건 종가_t ≥ 직전 20행(t-20..t-1)의 `halt` 제외 고가 최댓값(남은 행 15개 미만이면 제외), 통과 종목을 `features[code]["vol_ratio"]` 큰 순.
    - S3: 조건 `ma60` 존재(앱 지표와 같이 `halt` 포함 계산, `calculate_technical_indicators` 사용)이고 종가_t ≥ ma60, 키 = 5일 수익률(`close_t/close_{t-5}-1`, t-5행 양수 종가·비`halt`), 낮은 순.
    - S4: 키 = `features[code]["atr_pct"]`(NaN 제외), 낮은 순.
  - `apply_filter(candidate: Candidate, days: list, bench: pd.DataFrame) -> list[DayResult]` — F1: 그날 벤치 종가 ≥ 20일 단순이동평균(벤치에 날짜 행이 없거나 20봉 미만이면 불충족)이 아니면 `signals=[]`(풀 유지). 다른 후보면 입력을 그대로 돌려준다.
  - `candidate_days(spec, base_days, frames, features, bench, bucket) -> list[DayResult]` — `spec`이 `Candidate`면 방향에 맞게(신호면 `rank_signals`, 필터면 `apply_filter`, 청산/기준선이면 `base_days` 그대로), `Combo`면 신호(없으면 `base_days`) → 필터 순으로 적용.
  - `rank_of` 같은 부가 구조 없이 `Signal.score`는 항상 0이다.

- [ ] **Step 1: 실패하는 테스트 작성** — 작은 손계산 프레임: `test_s1_orders_by_relative_strength`(코드 3개의 20일 수익률을 손으로 정하고 KODEX 수익률을 빼서 순서 확인), `test_s2_requires_breakout_and_orders_by_volume_ratio`, `test_s3_requires_close_above_ma60_and_orders_lowest_5day_return_first`, `test_s4_orders_lowest_atr_first`, `test_rankers_do_not_use_future_rows`(t 이후 행의 값을 바꿔도 t의 `signals`가 동일, 4개 후보 모두 — Review Focus 1), `test_excludes_halt_vol_break_missing_rows_and_nonpositive_closes`, `test_fewer_than_three_pass_returns_only_those`, `test_ties_keep_pool_order`, `test_score_is_zero_for_all_signals`, `test_f1_keeps_signals_only_when_benchmark_above_ma20`, `test_f1_blocks_when_benchmark_row_missing_or_under_20_bars`, `test_pool_is_unchanged_by_ranking_and_filter`, `test_candidate_days_combo_applies_signal_then_filter`.
- [ ] **Step 2:** 실행 → Expected: FAIL
- [ ] **Step 3: 구현.** 종목별 종가·고가 배열은 필요할 때만 `frame.index.get_loc(date)`로 오프셋을 잡는다(자기 프레임 행 기준).
- [ ] **Step 4:** 실행 → Expected: 13 passed
- [ ] **Step 5: 커밋** `feat(backtest-improve): rank-based signals S1-S4 and the F1 market filter`

---

### Task 5: 후보 평가 (`backtest/improve/evaluate.py`)

**Files:**
- Create: `backtest/improve/evaluate.py`
- Test: `tests/test_bt_im_evaluate.py`

**Interfaces:**
- Consumes: Task 2 `stats`, Task 3 `slots`, `backtest.analysis.equity.benchmark_returns/perf`, `backtest.simulate.Trade`.
- Produces:
  - `@dataclass(frozen=True) Window: signal_start: pd.Timestamp; signal_end: pd.Timestamp; dates: list`  (계좌 창의 모든 거래일, 오름차순; `signal_start`/`signal_end`는 거래 신호일 범위, 포함)
  - `evaluate(days: list, frames: dict, bench: pd.DataFrame, window: Window, *, exit_kwargs: dict, bucket: int = 200_000, k: int = 2, slippage_pct: float = 0.1, seed=SEED, draws=DRAWS) -> Evaluation`
  - `@dataclass Evaluation` — `trades: list`, `ret: pd.Series`(계좌 일간 수익률, 인덱스 = `window.dates`), `open: pd.Series`, `n_trades: int`, `trade_mean: Stat`(①: 신호일별 `[순손익 합, 거래 수]`, 행은 `window.dates` 전체, 거래 없는 날 0행), `vs_kodex: Stat`(②: `log_growth_excess(ret, kodex_ret)`), `vs_cash: Stat`(④: `log_growth_excess(ret, None)`), `kodex_ret: pd.Series`, `avg_hold_days`, `exposure`, `avg_slots`, `trade_kodex_excess_mean`(참고: 거래당 순손익 − 같은 구간 KODEX 수익률의 평균, 벤치에 날짜가 없는 거래는 제외), `perf: dict`(`equity.perf` 결과).
    - 거래 목록은 `run_slots(days_in_signal_range, ...)`가 만든다: `days`에서 `signal_start <= date <= signal_end`인 날만 쓴다.
    - KODEX 일간 수익률은 `benchmark_returns(bench, window.dates)`.
  - `vs_baseline(ret: pd.Series, baseline_ret: pd.Series, *, seed, draws) -> Stat` — ③: `log_growth_excess(ret, baseline_ret)`.

- [ ] **Step 1: 실패하는 테스트 작성** — `test_trades_are_limited_to_the_signal_window`, `test_rows_include_days_without_trades_as_zero`(`trade_mean.n_days == len(window.dates)`), `test_trade_mean_uses_signal_day_sums`, `test_vs_kodex_positive_when_account_beats_benchmark_every_day` (거래가 없을 때 account=0 대 하락하는 벤치 → 양수), `test_vs_cash_is_log_growth_of_account`, `test_trade_kodex_excess_matches_manual`(한 거래의 KODEX 구간 수익률을 손으로 계산), `test_avg_hold_days_and_utilisation`, `test_vs_baseline_zero_for_identical_accounts`(점추정 0), `test_no_trades_gives_zero_account_and_none_trade_mean`(거래 0건 → `n_trades == 0`, `trade_mean.point is None`, `ret`은 전부 0 — Review Focus 5), `test_account_window_includes_exit_costs_of_late_trades`(신호가 `signal_end` 직전인 거래의 청산일이 창 안에 있고 그 청산일 비용이 `ret`에 반영됨).
- [ ] **Step 2:** 실행 → Expected: FAIL
- [ ] **Step 3: 구현.** 계좌 창은 `window.dates` 전체(인덱스)이고 `slot_account(trades, frames, window.dates)`로 만든다.
- [ ] **Step 4:** 실행 → Expected: 10 passed
- [ ] **Step 5: 커밋** `feat(backtest-improve): evaluate one candidate on a window`

---

### Task 6: 학습 선별과 판정 (`backtest/improve/select.py`, `judge.py`)

**Files:**
- Create: `backtest/improve/select.py`, `backtest/improve/judge.py`
- Test: `tests/test_bt_im_select.py`, `tests/test_bt_im_judge.py`

**Interfaces:**
- Consumes: Task 1 `REGISTRY/DIRECTIONS/Combo/BASELINE`, Task 2 `Stat/mde/significant`, Task 5 `Evaluation/vs_baseline`.
- Produces (`select.py`):
  - `@dataclass Selection: chosen: dict  # 방향 -> 후보 이름|None; folded: dict  # 방향 -> 사유; combo: "Combo | None"; finalists: list  # 검증 대상 Candidate/Combo (N개); n: int`
  - `select_train(evals: dict[str, Evaluation], baseline: Evaluation) -> Selection` — `evals`는 후보 이름 → 학습 `Evaluation`. 방향마다 `vs_kodex.point`(선별 지표)가 가장 높은 후보(동률이면 레지스트리 순서)를 뽑고, **그 지표가 기준선 `vs_kodex.point` 이하이거나 그 후보의 `trade_mean.point`가 기준선 `trade_mean.point` 이하이면 접는다**(점추정이 None이면 접는다). 뽑힌 방향이 둘 이상이면 `Combo`를 만든다(조합의 학습 평가는 호출하는 쪽이 `combo_eval`로 넘긴다).
  - `decide_combo(selection: Selection, combo_eval: Evaluation | None, evals: dict) -> Selection` — 조합의 `vs_kodex.point`가 뽑힌 단일 후보들의 최댓값을 넘고 `trade_mean.point`가 단일들의 최댓값 이상일 때만 `finalists`에 조합을 추가한다. 아니면 조합은 버린다. `n = len(finalists)`.
  - `train_mde(evals: dict, baseline: Evaluation, finalists, test_days: int, train_days: int) -> dict` — 후보마다 `{"trade_mean": mde(자기 se), "trade_vs_baseline_needed": mde − 기준선 trade_mean.point, "vs_kodex": mde(자기 vs_kodex.se)}`; 각 se는 `Stat.se`(학습), 후보의 학습 평가가 없으면(조합) 그 조합의 학습 평가를 쓴다.
- Produces (`judge.py`):
  - `@dataclass(frozen=True) Verdict: label: str  # "합격"|"유망"|"불합격"; flags: dict`
  - `judge_candidate(trade_mean: Stat, vs_kodex: Stat, vs_baseline_stat: Stat, vs_cash: Stat, n: int, *, pre_exposed: bool, dividend_sensitive: bool = False) -> Verdict` — `alpha_adj = 0.05 / n`. 합격: `significant(trade_mean)` and `significant(vs_kodex)`. 유망(합격 아님): `significant(vs_baseline_stat)` and `trade_mean.point > 0` and `vs_cash.point > 0`. 아니면 불합격. `flags`에 `alpha_adj`, 각 `p_one`, `near_threshold`, `pre_exposed`, `dividend_sensitive`.
  - `no_candidates_verdict() -> str` = `"개선 후보 없음"`.

- [ ] **Step 1: 실패하는 테스트 작성** — `select`: `test_picks_best_per_direction_by_vs_kodex`, `test_folds_direction_when_not_better_than_baseline`, `test_folds_when_absolute_trade_mean_does_not_improve`(vs_kodex는 좋지만 절대 평균이 기준선 이하 → 접힘), `test_market_timing_candidate_is_selected_not_erased`(F1 합성 평가: vs_kodex는 크고 거래당 KODEX 대비 초과는 기준선과 같음 → 선별됨), `test_ties_follow_registry_order`, `test_combo_only_when_two_or_more_directions`, `test_combo_included_only_if_it_beats_every_single`, `test_n_counts_finalists_without_duplicates`, `test_no_survivors_gives_empty_finalists_and_n_zero`(Review Focus 5), `test_mde_uses_each_candidates_own_se`, `test_mde_reports_zero_basis_and_baseline_relative_need`. `judge`: `test_pass_needs_both_trade_mean_and_vs_kodex`, `test_pass_uses_bonferroni_threshold`(n=4면 p_one 0.02는 실패, n=1이면 통과), `test_negative_point_is_never_significant`, `test_promising_requires_positive_trade_mean_and_cash_edge`, `test_candidate_worse_than_cash_is_not_promising`(vs_baseline는 유의하지만 `vs_cash.point < 0`), `test_near_threshold_flag_does_not_change_label`, `test_flags_carry_pre_exposed_and_dividend_sensitivity`, `test_no_candidates_verdict_text`. (Stat은 손으로 만든 `Stat(...)` 값 사용.)
- [ ] **Step 2:** 실행 → Expected: FAIL
- [ ] **Step 3: 구현**
- [ ] **Step 4:** 실행 → Expected: select 11 + judge 8 = 19 passed
- [ ] **Step 5: 커밋** `feat(backtest-improve): training selection and verdict rules`

---

### Task 7: 단계 잠금 (`backtest/improve/lock.py`)

**Files:**
- Create: `backtest/improve/lock.py`
- Test: `tests/test_bt_im_lock.py`

**Interfaces:**
- Produces:
  - `OUT_DIR = Path("backtest/results/improve")`
  - `file_hash(path) -> str`, `tree_hash(paths: list) -> str`(정렬된 경로의 내용 해시를 합친 sha256)
  - `code_hashes(repo_root=".") -> dict` — `backtest/improve/*.py`, `backtest/*.py`, `backtest/analysis/*.py`, `backend/strategy.py`, `backend/fees.py`, `backend/orders.py`의 파일별 sha256.
  - `data_snapshot(cache_dir, codes) -> dict` — `{"listing_hash", "candle_hash"(코드별 CSV 내용 해시를 정렬해 합친 sha256), "n_frames", "first_date", "last_date"}`; 호출하는 쪽이 `n_frames/first_date/last_date`를 넘기거나 계산한다(시그니처는 `data_snapshot(cache_dir, codes, *, n_frames, first_date, last_date)`).
  - `git_state() -> dict` — `{"commit": str|None, "dirty": bool|None}`(`git`이 없거나 저장소가 아니면 None).
  - `build_selection_payload(selection, mde, config, snapshot, code, registry_fp, train_table, test_end) -> dict`
  - `write_selection(out_dir, payload)`, `read_selection(out_dir) -> dict`
  - `check_train_allowed(out_dir)` — `test_result.json`이 있으면 `StageError`.
  - `check_test_allowed(out_dir, current: dict, *, allow_rerun: bool) -> list[str]` — `selection.json`이 없으면 `StageError`; `test_result.json`이 있고 `allow_rerun`이 아니면 `StageError`; `current`(코드 해시·데이터 스냅샷·설정·레지스트리 지문)와 `selection.json`이 다르면 어긋난 항목 이름 목록을 돌려주고 `allow_rerun`이 아니면 `StageError`.
  - `write_test_result(out_dir, payload, *, selection_hash, rerun: bool, mismatches: list)`.
  - `class StageError(RuntimeError)`

- [ ] **Step 1: 실패하는 테스트 작성** (`tmp_path` 사용) — `test_hashes_change_with_content`, `test_test_refused_without_selection`, `test_second_test_refused_without_allow_rerun`, `test_train_refused_after_test_result_exists`, `test_test_refused_when_code_hash_differs`, `test_test_refused_when_candle_content_hash_differs`(CSV 한 글자 변경), `test_test_refused_when_config_or_registry_differs`, `test_allow_rerun_passes_but_records_mismatches_and_rerun_flag`, `test_test_result_records_selection_hash`, `test_data_snapshot_is_order_independent`, `test_git_state_returns_none_values_outside_a_repo`(임시 폴더에서 호출 시 None).
- [ ] **Step 2:** 실행 → Expected: FAIL
- [ ] **Step 3: 구현** — `subprocess`로 `git rev-parse HEAD`, `git status --porcelain`; 실패하면 None.
- [ ] **Step 4:** 실행 → Expected: 11 passed
- [ ] **Step 5: 커밋** `feat(backtest-improve): stage lock with code and data hashes`

---

### Task 8: 보고서와 CLI (`backtest/improve/report.py`, `run.py`)

**Files:**
- Create: `backtest/improve/report.py`, `backtest/improve/run.py`
- Test: `tests/test_bt_im_run.py`

**Interfaces:**
- Consumes: Tasks 1~7, 기존 `backtest.data`(`CandleCache`, `prepare_frame`, `Listing`), `backtest.analysis.run.load_listing`, `backtest.analysis.features.compute_features`, `backtest.signals`(`generate_signals`, `trading_dates`), `backtest.run`(`_executor`, `_generate_days`), `backtest.analysis.panel.TRAIN_END`.
- Produces:
  - `load_frames_cut(codes, cache, end=None, *, min_rows=60) -> (frames, skipped)` — `cache.load(code)`로 읽은 **원시** 일봉을 `end`(포함) 이하로 자른 뒤 `prepare_frame`을 적용한다(`end=None`이면 자르지 않음). 행이 `min_rows` 미만이면 skipped.
  - `@dataclass ImproveConfig: stage: str; out_dir: Path = OUT_DIR; cache_dir: Path = Path("backtest/cache"); workers: int = 1; max_codes: int|None = None; benchmark_code: str = "069500"; bucket: int = 200_000; k: int = 2; slippage_pct: float = 0.1; seed: int = SEED; draws: int = DRAWS; allow_rerun: bool = False; confirm_buckets: tuple = (100_000, 500_000)`
  - `train_windows(frames_cut) -> Window` — 절단된 프레임 합집합 거래일의 warmup(`trading_dates`의 60개 뒤)부터 마지막 날까지.
  - `test_windows(frames_full) -> (Window, test_end)` — `test_end` = 합집합 달력의 마지막 날에서 20거래일 앞, 신호 범위 `[2022-01-01, test_end]`, 계좌 창은 `2022-01-01 이후 첫 거래일 ~ 합집합 마지막 거래일`.
  - `run_train(cfg, *, fetch_listing=...) -> dict` — 학습 프레임(절단 후 준비) → 기준선 신호(`generate_signals`/병렬) → 후보 8개 학습 평가 → 조합 평가 → `select_train`·`decide_combo`·`train_mde` → `selection.json` 쓰기 → 결과 dict.
  - `run_test(cfg, ...) -> dict` — `check_test_allowed` → 전체 프레임으로 검증 창의 기준선 신호 생성 → 잠긴 후보 + 기준선 평가 → ①~④·③ 계산 → `judge_candidate` → 확인용(10만·50만 구간의 거래당 순손익, 연도별) → 분배금 민감도(② 로그성장 초과에서 연 2%p/252를 일간으로 뺀 뒤 합격이 유지되는가) → `test_result.json`·`improve_report.md` 쓰기.
  - `write_improve_report(out_dir, train, test|None)` — 첫 줄 "이 보고서는 투자 권유가 아니며, 이 결과만으로 실계좌 규칙을 바꾸면 안 된다", 한계(설계서 9절)가 결과보다 앞, `rerun`/데이터 변경 배너, 학습 표·MDE·검증 표·참고용·사전 노출 표시, 판정 라벨은 합격/유망/불합격(+"개선 후보 없음"), "효과 없음"이라는 표현 금지.
  - `main(argv=None, *, fetch_listing=...) -> int` — `--stage {train,test}`(필수), `--workers`, `--out`, `--cache`, `--max-codes`, `--allow-rerun`, `--draws`(테스트용), `--seed`.

- [ ] **Step 1: 실패하는 테스트 작성** — 합성 종목 5개(`trending_rows` 변형, 일부는 가격 상승 패턴이 달라지도록 스케일·시작일, 2020~2023 걸치는 700행 이상, 벤치 `069500` 포함)로 `tests/test_bt_an_run.py`와 같은 방식(`_seed_cache`, `listing`, 일봉 다운로드 금지 monkeypatch):
  `test_load_frames_cut_truncates_raw_before_preparing`(절단 뒤 `prepare_frame`이 적용돼 마지막 날짜가 `end` 이하이며, `end` 이후 행을 바꿔도 같은 프레임), `test_train_does_not_depend_on_data_after_train_end`(캐시의 `TRAIN_END` 이후 행을 바꾼 뒤 `run_train`을 새 폴더에 돌려 `selection.json`의 후보·N·학습 값이 동일 — Review Focus 2), `test_train_then_test_end_to_end_on_synthetic_data`(`run_train` → `run_test` 완주, 결과 파일 3개 존재), `test_test_refuses_without_selection`, `test_second_test_refused_and_allow_rerun_adds_banner`, `test_test_refuses_after_candle_change`, `test_report_first_line_and_limits_come_first`, `test_report_never_says_no_effect`, `test_report_marks_pre_exposed_candidates`, `test_report_handles_no_candidates`(모든 방향이 접히도록 만든 합성 데이터에서 "개선 후보 없음"으로 test 단계도 정상 종료하거나 N=0이면 test는 기준선만 기록), `test_no_candle_download`, `test_cli_requires_stage_and_writes_files`, `test_test_window_ends_20_trading_days_before_the_last_date`.
- [ ] **Step 2:** 실행 → Expected: FAIL
- [ ] **Step 3: 구현.** 병렬 신호 생성은 `backtest.run._executor/_generate_days`를 재사용(학습과 검증에서 각각 프레임·날짜가 다름). 로깅은 진행 상황만.
- [ ] **Step 4:** 실행 → Expected: 13 passed. 이어서 전체 `pytest -q` → Expected: 기존 1,297개 + 신규 전부 통과.
- [ ] **Step 5: 커밋** `feat(backtest-improve): train/test stages and the report`

---

### Task 9: 학습 단계 실제 실행 (검증은 아직 하지 않는다)

**Files:**
- Modify: `PROGRESS.md`(개선 후보 검증 도구 한 단락과 실행 방법, 소요 시간)
- 커밋 제외: `backtest/results/improve/*`

- [ ] **Step 1: 시험 실행** — `python -m backtest.improve.run --stage train --max-codes 20 --out <임시 폴더> --draws 500` → Expected: 종료 코드 0, `selection.json` 생성(임시 폴더).
- [ ] **Step 2: 실제 학습 실행** — `python -m backtest.improve.run --stage train --workers 8` → Expected: `backtest/results/improve/selection.json`과 학습 표가 생성. 소요 시간을 `PROGRESS.md`에 기록(설계서 11절 열린 항목).
- [ ] **Step 3: 확인** — 학습 표에서 거래 수가 0인 후보, 비정상적으로 큰 값, 접힌 방향과 사유, N, 후보별 MDE(①, ②)를 점검한다. 이상하면 원인을 조사하고(검증 단계는 건드리지 않음) 코드 문제면 TDD로 고친 뒤 학습을 다시 돌린다.
- [ ] **Step 4: 커밋** `docs: record the improvement-validation tool and the training run in PROGRESS.md`
- [ ] **Step 5: 멈춤 — 사용자 확인.** 선별 결과(후보, 접힌 방향, N, MDE, 사전 노출 표시)를 사용자에게 보여주고 검증 단계 실행과 `selection.json` 커밋 여부를 묻는다. **승인 전에는 Task 10을 시작하지 않는다.**

---

### Task 10: 검증 단계 실행 (사용자 승인 뒤, 한 번만)

- [ ] **Step 1:** 승인을 받으면 `selection.json`을 저장소에 커밋한다(`docs/superpowers/improve-selection.json`로 복사해 커밋; 결과 폴더의 원본은 그대로 둔다).
- [ ] **Step 2:** `python -m backtest.improve.run --stage test --workers 8` → Expected: `test_result.json`, `improve_report.md` 생성. `--allow-rerun` 없이 두 번째 실행이 거부되는지 확인한다.
- [ ] **Step 3: 결과 보고** — 판정(합격/유망/불합격/개선 후보 없음), 사전 노출·분배금 민감도 표시, 시장 노출과 ④, ② MDE를 한계와 함께 사용자에게 설명한다. 합격이어도 앱 반영 제안이 아니며 `strategy.py` 변경은 별도 설계와 승인이 필요하다.
- [ ] **Step 4(필요 시): 최종 검토** — 브랜치 전체를 Opus 리뷰어로 한 번 검토한다(검증 결과를 본 뒤 코드를 고치면 결과 신뢰도가 하락하므로, 수정은 보고서 표현·표시 오류에 한정하고 통계 로직을 바꾸지 않는다. 바꿨다면 보고서에 명시한다).
