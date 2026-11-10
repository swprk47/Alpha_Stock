# 스윙 추천 규칙 검증 분석 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PR #30 백테스트 위에 요소별 예측력 검정, 추천 선택 효과, 계좌 곡선과 단순 보유 비교, 3종목 상관, 거래 재추출 위험 분포를 얹은 분석 보고서를 만든다.

**Architecture:** `backtest/analysis/` 새 패키지. 날짜별 합계 통계(`day_stats`)에 블록 부트스트랩을 거는 공용 모듈(`bootstrap`)을 바탕으로, 후보-날짜 패널(`panel`)에서 요소 검정(`factors`)과 선택 효과(`selection`)를, 거래 목록에서 계좌 곡선(`equity`)·상관(`correlation`)·위험 분포(`risk`)를 계산하고 `report`/`run`이 묶는다. 앱 코드와 `strategy.py`는 import만 하고 수정하지 않는다.

**Tech Stack:** Python, numpy, pandas, pytest (새 의존성 없음 — scipy 없이 구현)

**Spec:** `docs/superpowers/specs/2026-11-03-backtest-analysis-design.md`

## Global Constraints

- 브랜치 `feat/backtest-analysis`. **`strategy.py`와 `backend/` 수정 금지**(import만). `main`·PR #30 브랜치에 직접 커밋 금지.
- 새 외부 의존성 금지(numpy·pandas만). SQLite·프론트 변경 없음.
- 일봉은 다시 받지 않는다(`backtest/cache/` 재사용). 상장 목록만 첫 실행에서 한 번 받아 `backtest/cache/listing.json`에 저장.
- 결과(`backtest/results/`)와 캐시는 커밋하지 않는다(`.gitignore`에 이미 있음). `backend/data/users/`는 절대 열거나 커밋하지 않는다.
- 학습 기간 2014-08 ~ 2021-12-31, 검증 2022-01-01 ~. 블록 길이 5, 재추출 5,000회, 시드는 인자(기본 `20261103`).
- 기본 결과값은 `entry_mode="next_open"`, `slippage_pct=0.1`. 종가 진입은 확인용.
- 요소 구간·유의 기준(구간당 최소 200건, Holm, 학습·검증 동시 통과, 연도 3분의 2 방향 일치)은 spec 4.3~4.5-1의 값을 그대로 쓴다.
- 한 작업 = 한 커밋(테스트 포함). 끝나면 `pytest -q` 전체 통과. 커밋 메시지 끝에 `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- 테스트는 `tests/test_bt_an_<모듈>.py`, 도우미는 기존 `tests/bt_helpers.py`(`make_frame`, `trending_rows`, `make_trade`, `listing`)를 재사용.
- 보고서 표현: 두 조건 모두 통과한 요소만 "유의", 나머지는 "근거 부족"(효과 없음이라고 단정하지 않음). 수치에는 표본 수와 95% 구간.

## Review Focus

1. **미래 정보 누수:** 날짜 t의 요소값은 t까지의 일봉만 쓴다(t 이후 데이터를 바꿔도 불변). 진입이 다음날 시가라도 요소는 t 기준.
2. **구간 경계 누수:** 분위수 경계는 학습 기간 데이터로만 계산해 검증 기간에 그대로 적용한다(검증 데이터를 바꿔도 경계 불변).
3. **빈 입력·희소 입력:** 거래 0건 구간, 추천 3개 미만인 날, 통과 종목 없는 예산 구간에서 예외 없이 "표본 없음/판정 불가"로 나온다.
4. **미완결 거래:** 데이터 끝에서 보유 기간을 못 채운 신호(`simulate_trade`가 `None`)는 0%로 세지 않고 표본에서 뺀다.
5. **상수·퇴화 입력:** 값이 전부 같은 요소나 손익이 전부 같은 표본은 순위상관이 NaN → "판정 불가"이며 유의로 나오지 않는다.

---

### Task 1: 블록 부트스트랩 (`backtest/analysis/bootstrap.py`)

**Files:**
- Create: `backtest/analysis/__init__.py`, `backtest/analysis/bootstrap.py`
- Test: `tests/test_bt_an_bootstrap.py`

**Interfaces:**
- Produces:
  - `BLOCK = 5`, `DRAWS = 5000`, `DEFAULT_SEED = 20261103`
  - `block_indices(n_days: int, block: int, rng: np.random.Generator) -> np.ndarray` — 길이 `n_days`, 연속 `block`개 구간(시작은 `0..n_days-block` 균등)을 이어 붙이고 `n_days`로 자른다. `n_days < block`이면 `block = n_days`.
  - `@dataclass(frozen=True) BootResult: point: float|None, lo: float|None, hi: float|None, p: float|None, n_days: int, draws: int`
  - `bootstrap_sums(day_stats: np.ndarray, stat_fn: Callable[[np.ndarray], float], *, block=BLOCK, draws=DRAWS, seed=DEFAULT_SEED) -> BootResult` — `day_stats`는 날짜별 합계 행렬(n_days x k). 점추정 = `stat_fn(day_stats.sum(0))`, 재추출마다 `stat_fn(day_stats[idx].sum(0))`. 95% 구간은 2.5/97.5 백분위, `p` = `min(1, 2*min(share(<=0), share(>=0)))`(NaN 표본은 제외). 날짜 0개이거나 점추정이 NaN이면 `BootResult(None, None, None, None, n_days, 0)`.

- [ ] **Step 1: 실패하는 테스트 작성** — `test_block_indices_length_and_consecutive`(길이=n_days, 5개씩 묶음 내부는 +1씩 증가), `test_block_indices_short_series_uses_whole_series`(n_days=3, block=5 → 길이 3), `test_bootstrap_same_seed_same_result`, `test_bootstrap_ci_contains_true_mean`(평균 2.0인 일별 값 → 구간이 2.0 포함, p < 0.05), `test_bootstrap_p_large_when_mean_zero`(평균 0 근방 → p > 0.2), `test_bootstrap_empty_returns_none`.
- [ ] **Step 2:** `pytest tests/test_bt_an_bootstrap.py -q` → Expected: FAIL(모듈 없음)
- [ ] **Step 3: 구현** — 위 시그니처. 재추출은 `np.random.default_rng(seed)` 하나로 순차 생성.
- [ ] **Step 4:** 같은 명령 → Expected: 6 passed
- [ ] **Step 5: 커밋** `feat(backtest-analysis): block bootstrap over per-day sums`

---

### Task 2: 요소 계산 (`backtest/analysis/features.py`)

**Files:**
- Create: `backtest/analysis/features.py`
- Test: `tests/test_bt_an_features.py`

**Interfaces:**
- Consumes: `strategy.calculate_technical_indicators(df)`(ma5, ma20, vol_ma5, rsi14, bb_upper, bb_lower 컬럼), 프레임의 `open/high/low/close/volume`.
- Produces:
  - `FEATURE_COLUMNS = ("gap20", "ma_gap", "rsi", "vol_ratio", "pctb", "atr_pct")`
  - `compute_features(frame: pd.DataFrame) -> pd.DataFrame` — 프레임 인덱스(날짜)와 같은 인덱스, 컬럼은 `FEATURE_COLUMNS`. 정의: `gap20=(close-ma20)/ma20`, `ma_gap=(ma5-ma20)/ma20`, `rsi=rsi14`, `vol_ratio=volume/(vol_ma5+1)`(vol_ma5가 0 이하면 1.0, 앱과 동일), `pctb=(close-bb_lower)/(bb_upper-bb_lower)`(분모 0이면 NaN), `atr_pct=참범위 14일 단순평균/close`(참범위 = max(high-low, |high-prev_close|, |low-prev_close|)). 지표 계산이 불가능한 앞부분(25행 미만)은 전부 NaN.

- [ ] **Step 1: 실패하는 테스트 작성** — `test_features_match_app_on_last_60_window`(`trending_rows(120)` 프레임에서 임의 날짜 t의 `compute_features(frame).loc[t]`가, 앱 방식(`frame.loc[:t].tail(60)`에 `calculate_technical_indicators` 적용 후 마지막 행)으로 계산한 gap20·ma_gap·rsi·vol_ratio·pctb와 `pytest.approx`로 일치), `test_features_do_not_use_future_rows`(t 이후 행의 close를 바꿔도 `loc[t]` 불변 — Review Focus 1), `test_atr_pct_hand_computed`(고가·저가·종가를 손으로 정한 15행에서 마지막 날 atr_pct 값 일치), `test_short_frame_all_nan`(20행 → 전부 NaN), `test_pctb_nan_when_band_zero`(변동 없는 프레임).
- [ ] **Step 2:** 실행 → Expected: FAIL
- [ ] **Step 3: 구현** `compute_features`. 요소는 소수(비율) 단위로 저장하고 구간 경계도 같은 단위를 쓴다(Task 4).
- [ ] **Step 4:** 실행 → Expected: 5 passed
- [ ] **Step 5: 커밋** `feat(backtest-analysis): per-day factor computation matching the app's indicators`

---

### Task 3: 후보-날짜 패널 (`backtest/analysis/panel.py`)

**Files:**
- Create: `backtest/analysis/panel.py`
- Test: `tests/test_bt_an_panel.py`

**Interfaces:**
- Consumes: `backtest.signals.DayResult/Signal`, `backtest.simulate.simulate_trade`, `backtest.analysis.features.compute_features`.
- Produces:
  - `TRAIN_END = pd.Timestamp("2021-12-31")`
  - `build_panel(pools: dict, frames: dict, features: dict, entry_mode: str, *, bucket: int, slippage_pct: float = 0.1, passes: dict | None = None, top_n: int = 3) -> pd.DataFrame` — `pools`는 `{날짜: [코드...]}`, `features`는 `{코드: compute_features(frame)}`, `passes`는 `{날짜: [Signal...]}`(정렬된 통과 목록, 없으면 모든 행 `passed=False`). 행마다 컬럼: `date, code, bucket, net_return_pct, gap20, ma_gap, rsi, vol_ratio, pctb, atr_pct, passed(bool), picked(bool: 통과 목록 앞 top_n), score(float, 통과 아니면 NaN), period("train"|"test")`. `simulate_trade`가 `None`인 행은 뺀다. 날짜순·풀 순서로 정렬된 DataFrame.
  - `pools_from_days(days) -> dict`, `passes_from_days(days) -> dict` — `DayResult` 목록에서 위 입력을 만든다.

- [ ] **Step 1: 실패하는 테스트 작성** — `test_panel_has_one_row_per_pool_candidate_day`(2종목·여러 날 합성 프레임, 풀 밖 종목은 없음), `test_panel_drops_unfinished_trades`(마지막 5일 신호는 행 없음, 0%로 들어가지 않음 — Review Focus 4), `test_panel_flags_passed_and_picked`(통과 4개 중 앞 3개만 picked, 점수는 통과에만 값), `test_panel_period_split_at_train_end`, `test_panel_net_return_matches_simulate_trade`(한 행의 값이 `simulate_trade(..., slippage_pct=0.1)`와 같음), `test_panel_empty_pool_returns_empty_frame_with_columns`.
- [ ] **Step 2:** 실행 → Expected: FAIL
- [ ] **Step 3: 구현.** 요소값은 `features[code].loc[date]`(신호일 t 기준). 거래는 신호일 t, `entry_mode`로 `simulate_trade` 호출.
- [ ] **Step 4:** 실행 → Expected: 6 passed
- [ ] **Step 5: 커밋** `feat(backtest-analysis): candidate-day panel with simulated outcomes`

---

### Task 4: 요소 검정 (`backtest/analysis/factors.py`)

**Files:**
- Create: `backtest/analysis/factors.py`
- Test: `tests/test_bt_an_factors.py`

**Interfaces:**
- Consumes: Task 1 `bootstrap_sums`, Task 3 패널(컬럼 위 참조), Task 2 `FEATURE_COLUMNS`.
- Produces:
  - `MIN_BIN = 200`, `FACTOR_BINS`: 요소별 구간 정의. 고정 경계 — `gap20: [0, 0.03, 0.06]`, `rsi: [30, 45, 60, 70]`, `pctb: [0, 0.5, 1]`, `score: [70, 80]`(60~69/70~79/80+). 학습 분위수 — `ma_gap`(4분위), `vol_ratio`(5분위), `atr_pct`(3분위).
  - `train_edges(panel: pd.DataFrame) -> dict[str, list[float]]` — 위 정의에서 분위수 요소의 경계를 **학습 기간 행만**으로 계산해 고정 경계와 합친 딕셔너리.
  - `assign_bins(values: pd.Series, edges: list[float]) -> pd.Series` — `np.digitize` 규칙으로 0..len(edges) 정수 구간(NaN은 NaN).
  - `merge_small_bins(counts: list[int], min_n: int = MIN_BIN) -> list[int]` — 각 원래 구간이 속하는 병합 구간 번호. 규칙: 구간이 둘 이상이고 `min_n` 미만인 구간이 있으면 가장 작은 구간을 인접 구간 중 건수가 적은 쪽(동률이면 왼쪽)에 합치고 반복.
  - `@dataclass(frozen=True) FactorResult: name, period, n, rho(BootResult), table(list[dict(label, n, mean, ...)])`
  - `rank_corr_test(panel: pd.DataFrame, column: str, *, seed=DEFAULT_SEED) -> BootResult` — 대상은 `column`과 `net_return_pct`가 모두 있는 행(`score`는 `passed` 행만). 두 열을 전체 표본에서 순위(평균순위)로 바꾸고 날짜별로 `(n, Σx, Σy, Σxy, Σx², Σy²)`를 모아 재추출 합계로 피어슨 상관을 계산. 분산 0이면 NaN → `BootResult(None...)`.
  - `holm(pvals: dict[str, float|None]) -> dict[str, float|None]` — Holm 보정 p값(단조 보정, 1로 상한). None은 그대로 None, 비교 개수에서 제외.
  - `judge(train: BootResult, test: BootResult, yearly_signs: dict[int, int], holm_p: float|None) -> str` — 반환 `"유의"` / `"근거 부족"` / `"불안정"` / `"판정 불가"`. 규칙: 학습 `holm_p`가 None이거나 어느 쪽 `point`가 None → "판정 불가". 학습 `holm_p < 0.05`, 검증 `point`와 학습 `point` 부호 같고 검증 95% 구간이 0을 포함하지 않으면 통과. 통과했지만 연도별 부호 중 학습 방향과 같은 연도가 전체의 2/3 미만이면 "불안정", 통과 못 하면 "근거 부족".
  - `yearly_signs(panel: pd.DataFrame, column: str) -> dict[int, int]` — 연도별 표본 순위상관의 부호(+1/-1/0).
  - `bin_table(panel, column, edges) -> list[dict]` — 병합 후 구간 라벨, 건수, 평균 순손익.

- [ ] **Step 1: 실패하는 테스트 작성** — `test_train_edges_use_only_train_rows`(검증 행 값을 극단으로 바꿔도 경계 불변 — Review Focus 2), `test_assign_bins_boundaries`, `test_merge_small_bins_rule`(예: counts [50, 300, 400] → 첫 구간이 둘째에 합쳐짐; [300, 50, 40, 500] 규칙대로), `test_rank_corr_detects_planted_relation`(요소가 클수록 손익이 오르게 만든 합성 패널 → point>0, 95% 구간이 0을 안 넘음), `test_rank_corr_independent_not_significant`(독립 난수 → Holm 후 유의 판정 거의 없음: 시드 20개 반복 시 "유의" 0~1건), `test_rank_corr_constant_column_is_none`(Review Focus 5), `test_holm_known_values`(p=[0.01,0.04,0.03] → 0.03, 0.06, 0.06), `test_judge_passes_only_when_train_and_test_agree`, `test_judge_train_only_is_insufficient`, `test_judge_marks_unstable_when_years_disagree`, `test_score_factor_uses_passed_rows_only`.
- [ ] **Step 2:** 실행 → Expected: FAIL
- [ ] **Step 3: 구현.** 날짜별 합계는 `groupby(date)`로 한 번에. 순위는 `Series.rank(method="average")`.
- [ ] **Step 4:** 실행 → Expected: 11 passed
- [ ] **Step 5: 커밋** `feat(backtest-analysis): factor rank-correlation tests with Holm and train/test judgement`

---

### Task 5: 추천 선택 효과 (`backtest/analysis/selection.py`)

**Files:**
- Create: `backtest/analysis/selection.py`
- Test: `tests/test_bt_an_selection.py`

**Interfaces:**
- Consumes: Task 3 패널(`picked`, `net_return_pct`, `date`), Task 1.
- Produces: `selection_effect(panel: pd.DataFrame, *, seed=DEFAULT_SEED) -> BootResult` — 통계 = `Σ(picked 행 손익)/n_picked − Σ(전체 후보 행 손익)/n_pool`(날짜별 합계 4열로 재추출). picked가 하나도 없으면 None 결과.

- [ ] **Step 1: 실패하는 테스트 작성** — `test_selection_effect_positive_when_picks_beat_pool`(picked 행 손익을 +2로 심음 → point>0, 구간이 0 초과), `test_selection_effect_zero_when_picks_random`(픽이 무작위 → 구간이 0 포함), `test_selection_effect_none_without_picks`.
- [ ] **Step 2:** 실행 → Expected: FAIL
- [ ] **Step 3: 구현**
- [ ] **Step 4:** 실행 → Expected: 3 passed
- [ ] **Step 5: 커밋** `feat(backtest-analysis): pick-versus-pool selection effect with CI`

---

### Task 6: 계좌 곡선과 단순 보유 비교 (`backtest/analysis/equity.py`)

**Files:**
- Create: `backtest/analysis/equity.py`
- Test: `tests/test_bt_an_equity.py`

**Interfaces:**
- Consumes: `backtest.simulate.Trade`(entry_date, exit_date, entry_price, exit_price, net_return_pct, entry_mode), 프레임(`close`, `open`), Task 1.
- Produces:
  - `trade_daily_factors(trade: Trade, frame: pd.DataFrame) -> pd.Series` — 진입일 다음 거래일부터(종가 진입이면 진입일 다음 날부터, 다음날 시가 진입이면 진입일 당일부터) 청산일까지 날짜별 증가율 `1+r`. 중간 날은 종가/전일종가, 첫 날은 종가/`entry_price`(진입일 이전 기준가는 `entry_price`), 청산일은 `exit_price`/전일종가에 비용 인자 `C = (1+net/100)/(exit_price/entry_price)`를 곱한다. **전체 곱 = `1 + net_return_pct/100` 이 정확히 성립**해야 한다. 청산일이 진입 다음 날이면 한 날에 모두 적용.
  - `portfolio_daily(trades: list, frames: dict, dates: list) -> pd.DataFrame` — `dates` 전체에 대해 컬럼 `ret`(그날 보유 포지션들의 단순평균 일간 수익률, 없으면 0), `invested`(bool). 보유 판단 = 그 날짜에 위 `trade_daily_factors`가 값을 갖는 포지션.
  - `perf(ret: pd.Series, invested: pd.Series | None = None) -> dict` — `ann_return`(`(Π(1+ret))^(252/n)−1`), `max_drawdown`(누적 곡선 고점 대비 최저), `sharpe`(`mean/std*sqrt(252)`, 무위험수익률 0, 분산 0이면 None), `exposure`(invested 비율, 없으면 None), `n_days`.
  - `benchmark_returns(bench: pd.DataFrame, dates) -> pd.Series` — 벤치 종가 일간 수익률(`dates` 정렬, 없는 날 0).
  - `matched_benchmark(bench_ret: pd.Series, invested: pd.Series) -> pd.Series` — 투자한 날만 벤치 수익률, 나머지 0.
  - `information_ratio(ret: pd.Series, bench_ret: pd.Series) -> float | None` — `mean(ret−bench)/std(ret−bench)*sqrt(252)`.
  - `excess_ci(ret, other, *, seed=DEFAULT_SEED) -> BootResult` — 일간 초과수익 평균(×252 연환산은 보고서에서)의 블록 부트스트랩.
  - `cost_drag(trades: list) -> dict` — `gross_mean_pct`(`(exit_price/entry_price−1)*100` 평균), `net_mean_pct`, `drag_pct`(차이).

- [ ] **Step 1: 실패하는 테스트 작성** — `test_trade_factors_product_equals_net_return`(`simulate_trade`로 만든 target·stop·expire 거래 각 1건에서 곱 == `1+net/100`, 종가·다음날 시가 진입 모두), `test_portfolio_equal_weight_of_open_positions`(두 포지션이 겹치는 날 수익률 = 단순평균), `test_portfolio_cash_day_is_zero_and_not_invested`, `test_perf_known_values`(일정한 일간 수익률에서 연환산·낙폭 0·샤프 None 또는 큰 값 대신 손으로 계산한 값), `test_max_drawdown_from_peak`(+10%, −20%, +5% 열 → 낙폭 −20%), `test_matched_benchmark_zero_on_cash_days`, `test_information_ratio_none_when_identical`, `test_cost_drag_positive`(수수료·세금이 있으므로 gross > net), `test_equity_empty_trades`(거래 0건 → 빈 곡선 예외 없음, 연환산 None).
- [ ] **Step 2:** 실행 → Expected: FAIL
- [ ] **Step 3: 구현.** 빈 거래·빈 날짜는 예외 없이 `perf`가 None을 담은 dict를 돌려준다.
- [ ] **Step 4:** 실행 → Expected: 9 passed
- [ ] **Step 5: 커밋** `feat(backtest-analysis): account equity curve, buy-and-hold comparison and cost drag`

---

### Task 7: 추천 3종목 상관 (`backtest/analysis/correlation.py`)

**Files:**
- Create: `backtest/analysis/correlation.py`
- Test: `tests/test_bt_an_correlation.py`

**Interfaces:**
- Consumes: `DayResult`(date, pool, signals), 프레임(`close`), `Trade`, Task 1.
- Produces:
  - `pair_corr_mean(frames: dict, codes: list, date, *, window=60) -> float | None` — `date`까지 최근 `window`일 일간 수익률의 쌍별 상관 평균. 종목이 2개 미만이거나 공통 일수가 20 미만이면 None.
  - `picks_vs_random(days: list, frames: dict, *, repeats=20, seed=DEFAULT_SEED) -> dict` — `picks_mean`(정확히 3개 추천한 날들의 평균 쌍별 상관), `random_mean`(같은 날들의 풀에서 3개를 무작위 `repeats`회 뽑은 평균), `n_days`, `n_skipped`(추천 3개 미만인 날 수).
  - `all_stop_vs_independent(trades: list) -> dict` — 정확히 3건이 있는 신호일만 대상. `p_stop`(전체 손절 비율), `observed`(3건 모두 stop인 날 비율), `expected`(`p_stop**3`), `diff`(BootResult: 날짜별 `(all_stop − p_stop^3)`의 평균), `n_days`.
  - `terciles_by_corr(days, frames, trades) -> list[dict]` — 3종목 평균 상관 3분위(낮음/중간/높음)별로 `n_days`, `mean_ret`, `std_ret`(날짜별 3종목 평균 손익의 표준편차), `lowest5_mean`(하위 5% 평균). 표본이 3분위로 나눌 만큼 없으면 빈 리스트.

- [ ] **Step 1: 실패하는 테스트 작성** — `test_pair_corr_perfectly_correlated_series_is_one`, `test_pair_corr_none_with_too_few_common_days`, `test_picks_vs_random_skips_days_with_fewer_than_three_picks`(n_skipped 일치 — Review Focus 3), `test_all_stop_expected_is_cube_of_stop_rate`, `test_all_stop_excess_when_stops_cluster`(같은 날 3건이 함께 손절되게 심으면 observed > expected, diff.point > 0), `test_terciles_empty_when_too_few_days`.
- [ ] **Step 2:** 실행 → Expected: FAIL
- [ ] **Step 3: 구현**
- [ ] **Step 4:** 실행 → Expected: 6 passed
- [ ] **Step 5: 커밋** `feat(backtest-analysis): correlation among the three picks and clustered-stop check`

---

### Task 8: 거래 재추출 위험 분포 (`backtest/analysis/risk.py`)

**Files:**
- Create: `backtest/analysis/risk.py`
- Test: `tests/test_bt_an_risk.py`

**Interfaces:**
- Consumes: Task 1 `block_indices`, Task 6 `portfolio_daily`의 `ret`/`invested`.
- Produces:
  - `HORIZONS = (21, 63, 252, 756)`, `PATHS = 5000`
  - `simulate_paths(daily_ret: np.ndarray, horizon: int, *, paths=PATHS, block=BLOCK, seed=DEFAULT_SEED) -> np.ndarray` — (paths x horizon) 일간 수익률 행렬. 각 경로는 `block_indices(len(daily_ret), block, rng)`로 시계열을 블록 재추출해 앞 `horizon`개(필요하면 이어 붙여 채움)를 쓴다.
  - `risk_summary(path_returns: np.ndarray) -> dict` — `prob_profit`(최종 누적수익>0 비율), `p5`(최종 누적수익 5퍼센타일), `cvar5`(하위 5% 평균), `mdd_median`, `mdd_p95`(최대 낙폭 분포의 95퍼센타일 = 가장 나쁜 쪽), `prob_mdd_20`(낙폭이 20% 이상인 경로 비율). 일간 수익률이 비어 있으면 값은 None.
  - `risk_by_horizon(daily_ret, *, horizons=HORIZONS, seed=...) -> dict[int, dict]`
  - `by_regime(daily: pd.DataFrame, bench: pd.DataFrame, ...) -> dict[str, np.ndarray]` — 신호일 벤치 종가가 20일선 이상이면 "up", 아니면 "down"으로 날짜를 나눠 각각의 일간 수익률 배열(날짜순). 20봉 미만인 날은 뺀다.
  - `calibration(train_ret: np.ndarray, test_ret: np.ndarray, *, horizon=21, paths=PATHS, seed=...) -> dict` — 학습 일간 수익률만으로 `horizon`일 누적수익 분포의 `p5`를 구하고, 검증 기간의 모든 연속 `horizon`일 구간(중첩) 누적수익 중 `p5`보다 나쁜 비율 `exceed_rate`를 센다. 기대값 0.05. 비율의 95% 구간은 `block=horizon`인 블록 부트스트랩(`bootstrap_sums`로 구간별 지시변수 합계). 검증 구간이 `horizon`보다 짧으면 None.

- [ ] **Step 1: 실패하는 테스트 작성** — `test_simulate_paths_shape_and_seed`, `test_risk_summary_known_distribution`(모든 경로가 +10% 한 번뿐인 경우 prob_profit=1, p5=0.1 등 손으로 계산한 값), `test_risk_summary_losing_series_has_low_prob_profit`(매일 −0.1%인 입력 → prob_profit=0), `test_mdd_p95_not_less_than_median`, `test_by_regime_splits_by_ma20_state`, `test_calibration_iid_returns_exceed_rate_near_five_percent`(동일 분포 난수로 학습·검증 각 2,000일 → exceed_rate가 0.02~0.10 사이, 기대값 0.05를 구간이 포함), `test_calibration_flags_regime_shift`(검증을 훨씬 나쁜 분포로 → exceed_rate가 0.2보다 큼), `test_risk_empty_input_returns_none_values`(Review Focus 3).
- [ ] **Step 2:** 실행 → Expected: FAIL
- [ ] **Step 3: 구현.** 누적수익은 `np.cumprod(1+r, axis=1)`, 낙폭은 누적 곡선의 고점 대비.
- [ ] **Step 4:** 실행 → Expected: 8 passed
- [ ] **Step 5: 커밋** `feat(backtest-analysis): resampled risk distribution with regime split and calibration check`

---

### Task 9: 보고서와 실행 (`backtest/analysis/report.py`, `run.py`)

**Files:**
- Create: `backtest/analysis/report.py`, `backtest/analysis/run.py`
- Test: `tests/test_bt_an_run.py`

**Interfaces:**
- Consumes: Tasks 1~8, 기존 `backtest.data`(`CandleCache`, `load_frames`, `fetch_listing`, `Listing`), `backtest.signals`(`generate_signals`, `trading_dates`), `backtest.simulate.simulate_picks`, `backtest.pool.select_pool`, `backtest.run`(`DEFAULT_BUCKETS`, `_executor`, `_generate_days`).
- Produces:
  - `AnalysisConfig`: `buckets=(100_000, 200_000, 500_000)`, `workers=1`, `out_dir`, `cache_dir=Path("backtest/cache")`, `max_codes=None`, `benchmark_code="069500"`, `seed=DEFAULT_SEED`, `refresh_listing=False`, `full_pool=True`(확인용 전체 풀 분석 포함 여부).
  - `load_listing(cache_dir, fetch, *, refresh=False) -> list[Listing]` — `listing.json`이 있으면 읽고, 없거나 `refresh`이면 `fetch()`로 받아 저장.
  - `run_analysis(cfg, *, fetch_listing=default_fetch_listing) -> dict` — 캐시된 프레임에서 예산 구간 x (다음날 시가·종가) 시나리오마다: ① 본 분석(후보 30) 패널 → 요소 검정(학습·검증, Holm, 연도 부호, 판정) + 선택 효과 ② `full_pool`이면 `select_pool(limit=len(listings))` 풀로 패널을 만들어 같은 요소 검정(확인용, 점수 요소 제외) ③ `simulate_picks(top_n=3)` 거래로 계좌 곡선·단순 보유 3종·정보비율·초과수익 CI·비용 드래그·종가-시가 차이·시장 상태별 요약(기존 `by_market_state`) ④ 상관(picks_vs_random, all_stop, terciles) ⑤ 위험 분포(기간별, 시장 상태별, 보정 점검). 결과는 JSON 직렬화 가능한 dict.
  - `write_analysis_report(out_dir, results)` — `analysis_report.md`와 `analysis.json`. 마크다운은 **한계 목록을 맨 앞**에 두고(spec 8), "미래를 맞히는 것이 아니라 과거 분포를 가정한 범위"를 첫머리에, 이어 요소별 결과(판정·학습/검증 rho·구간·건수·구간표·연도별 부호), 선택 효과, 계좌 곡선 비교, 상관, 위험 분포·보정 점검, 기준선 대비 차이를 쓴다. 표본이 없으면 "표본 없음".
  - `main(argv=None, *, fetch_listing=...) -> int` — `python -m backtest.analysis.run [--buckets ...] [--workers N] [--out DIR] [--cache DIR] [--max-codes N] [--seed N] [--refresh-listing] [--no-full-pool]`.

- [ ] **Step 1: 실패하는 테스트 작성** — 합성 종목 3~4개(각 `trending_rows(400)`에 약간의 변형)와 주입한 `fetch_listing`으로: `test_load_listing_saves_then_reuses`(두 번째 호출은 fetch 안 부름), `test_run_analysis_end_to_end_on_synthetic_data`(예외 없이 끝나고 결과 dict에 요소별 판정·계좌 곡선·위험 분포 키가 있음), `test_report_puts_limits_before_results`(`## 한계` 위치가 `## 요소별` 앞), `test_report_never_calls_insufficient_evidence_ineffective`(보고서에 "효과 없음" 문자열이 없음), `test_report_handles_scenario_without_trades`(거래 0건 구간 → "표본 없음"), `test_cli_writes_report_files`(`main`이 `analysis_report.md`, `analysis.json` 생성), `test_run_does_not_fetch_candles`(일봉 fetch가 호출되지 않음 — 일봉은 캐시만 사용).
- [ ] **Step 2:** 실행 → Expected: FAIL
- [ ] **Step 3: 구현.** 병렬 신호 생성은 기존 `backtest.run`의 `_executor`/`_generate_days`를 재사용(워커 수 인자). 로깅은 진행 상황만 `print`.
- [ ] **Step 4:** 실행 → Expected: 7 passed. 이어서 전체 `pytest -q` → Expected: 기존 1214개 + 신규 전부 통과.
- [ ] **Step 5: 커밋** `feat(backtest-analysis): run the analysis and write the report`

---

### Task 10: 실제 데이터 실행과 기록

**Files:**
- Modify: `PROGRESS.md`(분석 층 추가 한 단락과 실행 방법)
- 커밋 제외: `backtest/results/<날짜>/analysis_report.md`, `analysis.json`

- [ ] **Step 1: 시험 실행** — `python -m backtest.analysis.run --max-codes 20 --out <임시 폴더>` → Expected: 종료 코드 0, `analysis_report.md` 생성.
- [ ] **Step 2: 전체 실행**(로컬 캐시 300종목, 시간은 실측 후 기록) — `python -m backtest.analysis.run --workers <코어 수> --out backtest/results/<날짜>` → Expected: 보고서 생성. 전체 풀 확인 분석의 소요 시간을 `PROGRESS.md`에 기록(spec 10 열린 항목).
- [ ] **Step 3: 보고서 검증** — 한계가 맨 앞에 있는지, 구간 건수가 200 이상 또는 병합 표시인지, 기준선(`backtest/results/2026-11-02/report.md`)과 거래 수·기대 손익 차이를 확인해 보고서와 `PROGRESS.md`에 적는다. 이상한 수치(전부 유의 등)는 원인 조사 후에야 결론으로 쓴다.
- [ ] **Step 4: 커밋** `docs: record the analysis layer and how to run it in PROGRESS.md` (결과 파일은 `git status`로 제외 확인)

---

## 실행 후 사용자에게 알릴 것

- 요소별 판정 표(유의/근거 부족/불안정/판정 불가)와 한계를 함께. 결과가 "근거 부족"뿐이어도 그대로 말한다.
- `strategy.py`를 고치자는 제안은 별도 설계·승인 단계이며 이 계획의 범위 밖이다.
