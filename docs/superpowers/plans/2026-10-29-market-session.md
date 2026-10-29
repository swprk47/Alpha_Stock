# 장 상태 태그·장 시간 안내·장 마감 중 주문 정책 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 종목별 장 상태 태그(프리마켓·정규장·애프터마켓·장 마감), 태그를 누르면 뜨는 NXT/KRX 탭 "장 시간 안내" 팝업, 정규장이 아닐 때의 주문 확인창 경고, 사용자별 서버 강제 설정 "장 마감 중 거래"를 만든다.

**Architecture:** 서버가 네이버 시세 응답(`marketStatus`·`marketSessionType`·`overMarketPriceInfo`)에서 순수 함수 하나로 상태를 판단해 `market_state`를 응답에 붙이고, 주문은 주문 시점의 시세 상태와 사용자 설정으로 서버가 거절한다. 프론트는 새 순수 함수 구간 `// <market-logic>`이 태그·경고 문구·팝업 막대 계산을 맡고, 화면(태그 4곳·팝업·확인창·내 메뉴)은 그 결과만 그린다. 시계로 장 상태를 추측하지 않는다(시계는 팝업의 현재 시각 V 표시에만 쓴다).

**Tech Stack:** FastAPI/pydantic(`extra=forbid`), 사용자별 JSON 저장(`data/users/*.json`), 단일 `frontend/index.html`(Tailwind, 순수 함수는 node로 테스트), pytest.

**Spec:** `docs/superpowers/specs/2026-10-29-market-session-design.md` (시안: 디자인 캔버스 "시세 실패 표시 시안" 아래 두 줄)

## Global Constraints

- 브랜치 `feat/market-status`, 단독 PR, 커밋은 작업별. main 직접 push 금지, `strategy.py` 변경 금지, SQLite·프론트 분리·프레임워크 금지.
- 상태 값은 `"regular" | "pre" | "after" | "closed" | "unknown"`. 규칙: `OPEN`+`regularMarket` → regular, `OPEN`+`afterMarket` → after, `OPEN`+`preMarket` → pre(**가정**: 이름은 관측 전), `CLOSE` → closed, 그 밖·누락·이상한 값 → unknown. 모르는 값은 추측하지 않는다.
- 응답 모양: `market_state: {"state": "<위 값>", "nxt_listed": bool}`, `nxt_listed`는 시세 응답에 `overMarketPriceInfo`가 있는지.
- 설정: `settings.allow_closed_trading`, 기본 `true`, 키가 없는 옛 사용자 파일도 `true`로 읽는다. 요청 스키마는 `extra=forbid`.
- 주문 거절: 상태가 `pre|after|closed`이고 설정이 꺼져 있으면 **409**, 메시지 "장 마감 중에는 주문하지 않도록 설정돼 있어요. 내 메뉴에서 바꿀 수 있어요.". `regular`·`unknown`은 항상 허용. 매도 미리보기는 막지 않는다. 체결가 결정은 지금 그대로.
- 태그 글자: 프리마켓 / 정규장 / 애프터마켓 / 장 마감. 색: 하늘 `#64d2ff` / 초록 `#30d158` / 보라 `#bf5af2` / 회색 `#8e8e93`. 팝업 제목 "장 시간 안내", 탭 "NXT 넥스트레이드"·"KRX 한국거래소"(NXT는 `nxt_listed`일 때만), 기본 탭 KRX.
- 시간표 상수 `MARKET_HOURS`(기준일 `2026.10.29`, 팝업 문구 "2026.10.29 확인 · 시간은 바뀔 수 있어요."): NXT 프리마켓 08:00–08:50 / 정규장(메인마켓) 09:00:30–15:20 / 애프터마켓 15:40–20:00, 쉬는 시간 08:50–09:00·15:20–15:40. KRX 정규장 09:00–15:30만, 범례 맨 아래 "그 밖의 시간(장전·장후 시간외, 프리·애프터마켓)은 확인 중이에요". 막대 축 08:00–20:00, 현재 시각은 `Asia/Seoul`.
- 확인창 경고 문구(정규장은 경고 없음): pre "프리마켓이에요. 체결가는 전 거래일 종가로 정해져요." / after "애프터마켓이에요. 체결가는 정규장 종가 N원으로 정해져요." / closed "장 마감이에요. 마지막 정규장 종가로 체결돼요." / unknown "장 상태를 확인하지 못했어요. 체결가는 주문 시점 시세로 정해져요."
- 프론트 글자는 13px 미만 금지(`tests/test_frontend_foundation.py`가 검사). `\r\n`이 섞인 파일(`frontend/index.html`, 일부 테스트)은 줄 끝을 유지한다.
- 이 순서가 스펙 9절과 다르다: **팝업을 태그보다 먼저** 만든다(중간 커밋에서 태그를 눌러도 오류가 없게).

## Review Focus

1. 시세 응답에 `marketStatus`만 있고 세션 값이 없거나 숫자·객체 같은 이상한 값 → `unknown`이어야 한다 (Task 1).
2. 설정 키가 없는 **옛 사용자 파일**은 "허용"으로 읽혀야 한다 (Task 2).
3. 차단 설정에서 **매도(부분·전량)** 도 정규장이 아니면 막혀야 하고, **매도 미리보기**는 막히지 않아야 한다 (Task 2).
4. 시간표 밖(08:00 전·20:00 후·주말)이거나 `closed`일 때 **V를 그리지 않아야** 하고, 양 끝(08:00·20:00) 근처에서 글자가 팝업 밖으로 나가지 않아야 한다 (Task 3).
5. 팝업이 매수 시트 위에 떠 있을 때 **Esc는 팝업만** 닫아야 하고 시트는 남아야 한다 (Task 3).
6. `unknown` 상태에서 주문이 막히지 않고 확인창에는 경고가 나와야 한다 (Task 2·5).

---

### Task 1: 서버 — 장 상태 판단과 응답 필드

**Files:**
- Modify: `backend/market_data.py` (`get_realtime_stock_info`, `get_stock_detail_with_chart`, 새 함수들)
- Modify: `backend/server.py` (`get_portfolio` 보유 종목, `_compute_bucket`)
- Test: `tests/test_market_session.py` (새 파일)

**Interfaces:**
- Produces (`market_data.py`):
  - `UNKNOWN_MARKET_STATE: dict` = `{"state": "unknown", "nxt_listed": False}`
  - `market_session(status, session_type) -> str` (Global Constraints의 규칙)
  - `market_state_of(basic: dict) -> dict` — 네이버 `/basic` 응답 dict에서 `marketStatus`·`marketSessionType`·`overMarketPriceInfo`를 읽어 `{"state", "nxt_listed"}`를 만든다(`overMarketPriceInfo`가 dict면 `nxt_listed` true).
  - `attach_market_state(recs: list, quote_provider) -> list` — 각 추천 dict 복사본에 `market_state` 추가(`quote_provider(code)`가 None이거나 예외면 `UNKNOWN_MARKET_STATE`), 원본 항목의 다른 키는 그대로.
  - 시세 dict(`get_realtime_stock_info` 반환)에 `market_state`, 상세(`get_stock_detail_with_chart` 반환)에 `market_state`.
- 다음 작업이 기대하는 것: 시세·상세·보유·추천 항목 모두 `market_state` 키를 가진다(없는 쪽이 없다).

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_market_session.py`
  - `test_market_session_table`: parametrize 표 — `("OPEN","regularMarket")→"regular"`, `("OPEN","afterMarket")→"after"`, `("OPEN","preMarket")→"pre"`, `("CLOSE","afterMarket")→"closed"`, `("CLOSE","regularMarket")→"closed"`, `("CLOSE",None)→"closed"`; 이상한 값 전부 `"unknown"`: `(None,None)`, `("OPEN",None)`, `("OPEN","weird")`, `("open","regularMarket")`, `(1,"regularMarket")`, `(["OPEN"],{})`, `("","")`.
  - `test_state_of_reads_nxt_listing`: `market_state_of({"marketStatus":"CLOSE","marketSessionType":"afterMarket","overMarketPriceInfo":{"overPrice":"230,000"}}) == {"state":"closed","nxt_listed":True}`; `overMarketPriceInfo` 없음/`None`/문자열이면 `nxt_listed False`; `{}`이면 `UNKNOWN_MARKET_STATE`와 같다.
  - `test_realtime_info_carries_market_state`: `requests.get`을 가짜로 바꾸고(`tests/test_change_amount.py`의 `_fake_get` 방식) `/basic` 응답에 위 세션 값을 넣어 `get_realtime_stock_info("005930")["market_state"]`를 확인. 세션 필드가 없는 응답이면 `unknown`.
  - `test_stock_detail_includes_market_state`(상세에 키가 있고, 시세 dict에 키가 없어도 `UNKNOWN_MARKET_STATE`).
  - `test_attach_market_state_per_code`: 공급 함수가 코드별로 다른 상태를 주고, 하나는 `None`·하나는 예외 → 결과 순서와 다른 키 보존, 실패한 둘은 unknown.
  - `test_compute_bucket_attaches_market_state`: `tests/test_change_amount.py::test_compute_bucket_passes_candidate_amounts_to_the_recommendations`와 같은 방식으로 `server._compute_bucket`을 돌리고 `server.get_realtime_stock_info`를 가짜로 바꿔 각 추천에 `market_state`가 있음을 확인.
  - `test_portfolio_holdings_carry_market_state(client)`: `tests/conftest.py`의 `client`로 매수 뒤 `client.quotes["005930"]["market_state"] = {"state":"after","nxt_listed":True}` → `/api/portfolio`의 보유 종목 `market_state.state == "after"`; 시세 실패(quotes에서 삭제)면 `unknown`.
- [ ] **Step 2: 실패 확인** — Run: `python -m pytest -q tests/test_market_session.py` → 새 이름이 없어 FAIL(전부 AttributeError/KeyError).
- [ ] **Step 3: 구현** — `market_session`은 정확히 일치하는 문자열 값만 해석하고 나머지는 `"unknown"`. `get_realtime_stock_info` 반환 dict에 `"market_state": market_state_of(data)`. 상세는 `info.get("market_state", UNKNOWN_MARKET_STATE)`. `server.get_portfolio`는 종목 시세 루프에서 `state_map[code] = info.get("market_state", UNKNOWN_MARKET_STATE)`를 모으고 `h["market_state"] = state_map.get(h["code"], UNKNOWN_MARKET_STATE)`. `_compute_bucket`은 `attach_diagnosis(...)` 결과를 `attach_market_state(..., get_realtime_stock_info)`로 한 번 더 감싼다(`strategy.py` 불변).
- [ ] **Step 4: 통과 확인** — Run: `python -m pytest -q tests/test_market_session.py` → PASS. 이어서 전체 `python -m pytest -q` → 전부 통과(기존 `test_change_amount.py` 등 포함).
- [ ] **Step 5: Commit**
  ```bash
  git add backend/market_data.py backend/server.py tests/test_market_session.py
  git commit -m "feat(api): add a per-stock market_state derived from Naver's session fields"
  ```
  (커밋 메시지 끝에 `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`)

### Task 2: 서버 — 설정 저장·API와 주문 강제

**Files:**
- Modify: `backend/portfolio.py` (설정 읽기·쓰기), `backend/schemas.py` (`SetSettingsRequest`), `backend/orders.py` (정책 검사), `backend/server.py` (`/api/me`, `POST /api/settings`)
- Test: `tests/test_settings_api.py`, `tests/test_order_market_policy.py` (새 파일)

**Interfaces:**
- Consumes: Task 1의 시세 dict `quote["market_state"]["state"]`(없으면 unknown으로 본다).
- Produces:
  - `portfolio.DEFAULT_SETTINGS = {"allow_closed_trading": True}`
  - `MultiUserPortfolioManager.get_settings(user_id) -> dict` (저장값 위에 기본값을 덮어 항상 모든 키를 가진 dict)
  - `MultiUserPortfolioManager.set_setting(user_id, key: str, value) -> dict` (사용자 락 안에서 저장, 알 수 없는 `key`는 `OrderError`)
  - `schemas.SetSettingsRequest(_Strict)`: `allow_closed_trading: bool`
  - `orders.MARKET_BLOCK_MESSAGE: str` (Global Constraints의 문구), `orders.enforce_market_policy(mgr, user_id, quote: dict) -> None` (거절이면 `HTTPException(409, MARKET_BLOCK_MESSAGE)`)
  - `GET /api/me` 응답에 `settings`(dict), `POST /api/settings` → `{"success": True, "settings": {...}}`

- [ ] **Step 1: 실패하는 테스트 작성**
  - `tests/test_settings_api.py`: `test_default_is_allowed`(로그인 직후 `/api/me`의 `settings == {"allow_closed_trading": True}`), `test_old_user_file_without_settings_key_reads_as_allowed`(사용자 JSON에서 `settings` 키를 지운 뒤 `/api/me`가 `True`), `test_post_saves_and_survives_reload`(false로 저장 → `/api/me`에 반영, 새 `TestClient`가 아니라 같은 저장소를 다시 읽어도 유지), `test_reset_keeps_settings`(`/api/reset` 뒤에도 false 유지), `test_unknown_field_is_422`(`{"allow_closed_trading": false, "user_id": "x"}`와 `{"foo": 1}`), `test_non_bool_is_422`(`"nope"`), `test_requires_login_401`.
  - `tests/test_order_market_policy.py`: 매수·매도 각각, `client.quotes["005930"]["market_state"] = {"state": s, "nxt_listed": True}` 로 상태를 바꾸고 설정은 `POST /api/settings`로 바꾼다. parametrize `(state, allow, expected_status)`: 차단(false)에서 `pre/after/closed` → 409 + 본문 `detail == MARKET_BLOCK_MESSAGE`, `regular` → 200, `unknown` → 200, 상태 키 없음 → 200; 허용(true)에서는 모든 상태 200. 추가: `test_sell_partial_and_full_are_both_blocked`, `test_sell_preview_is_never_blocked`(차단+closed여도 `/api/sell/preview` 200), `test_blocked_order_changes_nothing`(409 뒤 현금·보유 불변), `test_order_still_503_when_quote_fails`(정책보다 시세 실패 503이 먼저).
- [ ] **Step 2: 실패 확인** — Run: `python -m pytest -q tests/test_settings_api.py tests/test_order_market_policy.py` → FAIL(엔드포인트·함수 없음).
- [ ] **Step 3: 구현** — `get_settings`는 `{**DEFAULT_SETTINGS, **data.get("settings", {})}`. 검증 순서는 매도 "미보유 400 → 시세 503 → **정책 409** → 소수 수량 400", 매수는 "시세 503 → 정책 409 → 체결". `enforce_market_policy`는 설정이 꺼져 있고 상태가 `pre|after|closed`일 때만 거절. `/api/me`는 `portfolio_mgr.get_settings(user_id)`를 `settings`로 내려준다.
- [ ] **Step 4: 통과 확인** — Run: 위 두 파일 → PASS, 이어서 전체 `python -m pytest -q` → 통과. `api()`의 `formatApiError`가 문자열 `detail`을 그대로 쓰므로 프론트 409 메시지 처리는 별도 코드가 필요 없다(Task 5 테스트가 확인).
- [ ] **Step 5: Commit**
  ```bash
  git add backend/portfolio.py backend/schemas.py backend/orders.py backend/server.py tests/test_settings_api.py tests/test_order_market_policy.py
  git commit -m "feat(api): per-user allow_closed_trading setting enforced on buy and sell"
  ```

### Task 3: 프론트 — 순수 함수 구간과 "장 시간 안내" 팝업

**Files:**
- Modify: `frontend/index.html` (새 `// <market-logic>` 구간을 `// </change-logic>` 뒤에, 팝업 마크업 `#marketHoursModal`을 `#tradeModal` 근처에, `openMarketHours`·`closeMarketHours`·`selectMarketTab`, 전역 keydown 핸들러)
- Test: `tests/test_frontend_market_logic.py`, `tests/test_frontend_market_popup.py` (새 파일, `tests/test_frontend_change_amount.py`의 `_section`·node 실행 방식 복사)

**Interfaces:**
- Produces (`// <market-logic>`, DOM 없음):
  - `MARKET_HOURS` 상수(Global Constraints 값), `MARKET_COLORS = {pre:'#64d2ff', regular:'#30d158', after:'#bf5af2', closed:'#8e8e93'}`
  - `sessionTag(ms) -> {label: string, tone: 'pre'|'regular'|'after'|'closed'} | null` (`ms`가 없거나 state가 unknown/모르는 값이면 null)
  - `availableTabs(ms) -> ['nxt','krx'] | ['krx']` (`ms.nxt_listed === true`일 때만 nxt 포함)
  - `kstClock(date: Date) -> {min: number, label: 'HH:MM', weekend: boolean}` (`Intl.DateTimeFormat` + `timeZone:'Asia/Seoul'`)
  - `hoursModel(tab: 'nxt'|'krx', ms, clock) -> {segments: [{key, name, text, left, width, color}], breaks: string, note: string, marker: null | {left, label, align: 'start'|'center'|'end'}, outside: boolean, stateLine: string}` (축 08:00–20:00 = 720분, `left = (from-480)/720*100`, `width = (to-from)/720*100`)
- Produces (DOM): `openMarketHours(state: string, nxtListed: boolean)`, `closeMarketHours()`, `selectMarketTab(key)`; 팝업 `role="dialog" aria-modal="true" aria-labelledby="marketHoursTitle"`, 탭 `role="tablist"`/`role="tab"` + `aria-selected`.
- Consumes: Task 1의 `market_state` 모양.

- [ ] **Step 1: 실패하는 테스트 작성**
  - `test_frontend_market_logic.py`(node): `test_session_tag_table`(regular→"정규장", pre→"프리마켓", after→"애프터마켓", closed→"장 마감", unknown/null/undefined/`{}`→null), `test_available_tabs`(`nxt_listed true`→`['nxt','krx']`, false/누락→`['krx']`), `test_hours_model_nxt_values`(세 구간의 `left/width`가 08:00 기준 비율과 같고 범례 텍스트가 "08:00 – 08:50"·"09:00:30 – 15:20"·"15:40 – 20:00", `breaks == "08:50–09:00 · 15:20–15:40"`), `test_hours_model_krx_only_regular_with_note`(구간 1개 "09:00 – 15:30", `note`가 "그 밖의 시간(장전·장후 시간외, 프리·애프터마켓)은 확인 중이에요"), `test_marker_position_and_label`(16:50 → 530분, `left ≈ 73.61`, `label "지금 16:50"`), `test_marker_edges_align`(08:05·19:55 근처에서 `align`이 `'start'`·`'end'`, 가운데는 `'center'`), `test_marker_hidden_outside_hours_weekend_and_closed`(07:59·20:01·주말·`ms.state == "closed"` 각각 `marker null`·`outside true`), `test_kst_clock_converts_from_utc`(`new Date('2026-10-29T07:50:00Z')` → `label "16:50"`, `weekend false`; 토요일 UTC → `weekend true`).
  - `test_frontend_market_popup.py`(소스 구조): `#marketHoursModal`에 `role="dialog"`·`aria-modal="true"`·`aria-labelledby="marketHoursTitle"`, 제목 "장 시간 안내", `role="tablist"`와 두 `role="tab"`, 설명 문구 "모의 주문은 정규장 종가로 체결돼요." 와 "2026.10.29 확인 · 시간은 바뀔 수 있어요.", V 아이콘은 `aria-hidden="true"` svg(`stroke-linecap="round"`). 전역 keydown 핸들러의 `dialogOpen` 목록에 `marketHoursModal`이 있고 Esc가 `closeMarketHours()`를 부르며 **시트는 닫지 않는다**(`closeBuyModal`이 `!dialogOpen`일 때만). 화살표 키가 탭을 바꾸고 Tab이 팝업 안에서 도는 코드(`trapMarketFocus`)가 `Tab` 핸들러에 연결.
- [ ] **Step 2: 실패 확인** — Run: `python -m pytest -q tests/test_frontend_market_logic.py tests/test_frontend_market_popup.py` → FAIL(구간·요소 없음).
- [ ] **Step 3: 구현** — 순수 함수는 위 시그니처대로, 시각 비교는 분 단위 정수. 팝업은 `#tradeModal`의 backdrop/panel 클래스(`dlg-backdrop`, `glass-modal`)를 재사용하고 초점 가둠·복귀는 `openTradeConfirm`/`closeTradeModal`/`trapTradeFocus`와 같은 패턴. `openMarketHours`는 `Date`를 `kstClock`으로 바꿔 `hoursModel`의 결과를 그린다(기본 탭 `krx`). 글자 13px 이상.
- [ ] **Step 4: 통과 확인** — Run: 위 두 파일 → PASS. 전체 `python -m pytest -q`와 프론트 문법검사(`CLAUDE.md`의 추출 후 `node --check`) 통과.
- [ ] **Step 5: Commit**
  ```bash
  git add frontend/index.html tests/test_frontend_market_logic.py tests/test_frontend_market_popup.py
  git commit -m "feat(ui): market-hours popup with NXT/KRX tabs and a current-time marker"
  ```

### Task 4: 프론트 — 종목 상세의 장 상태 태그

**Files:**
- Modify: `frontend/index.html` (`marketTagHtml`, 모바일 시트 제목줄 `#buyMarketTag`, `openCustomBuyModal`, `recDetailHtml`·`searchDetailHtml`·`holdingDetailHtml`의 칩 줄)
- Test: `tests/test_frontend_market_tag.py` (새 파일)

**Interfaces:**
- Consumes: Task 3의 `sessionTag(ms)`, `openMarketHours(state, nxtListed)`.
- Produces: `marketTagHtml(ms) -> string` — `sessionTag`가 null이면 `''`, 아니면 `<button type="button" aria-label="장 시간 안내 열기" onclick="openMarketHours('<state>', <true|false>)">● 라벨 ⓘ</button>` (색은 `MARKET_COLORS[tone]`, 글자 13px, 색과 글자를 함께).

- [ ] **Step 1: 실패하는 테스트 작성** — `test_frontend_market_tag.py`: `test_tag_html_per_state`(node로 4가지 상태의 HTML에 라벨·`aria-label="장 시간 안내 열기"`·`openMarketHours('after', true)` 형태·`MARKET_COLORS` 색이 들어 있음), `test_tag_html_empty_when_unknown`(unknown/없음 → `''`), `test_mobile_sheet_title_row_has_the_tag_slot`(`id="buyMarketTag"`가 `#buyModalTitle`과 같은 줄 안에 있고 `openCustomBuyModal`이 `marketTagHtml(stockItem.market_state)`로 채움), `test_pc_headers_use_the_tag`(`recDetailHtml`은 `item.market_state`, `searchDetailHtml`은 `stock.market_state`, `holdingDetailHtml`은 `h.market_state`로 `marketTagHtml(...)`를 칩 줄의 `securityTagHtml(...)` 뒤에 둔다), `test_list_rows_do_not_get_the_tag`(`renderRecommendations`·`renderHoldings`·`renderSearchResults`에는 `marketTagHtml`이 없다).
- [ ] **Step 2: 실패 확인** — Run: `python -m pytest -q tests/test_frontend_market_tag.py` → FAIL.
- [ ] **Step 3: 구현** — `marketTagHtml`은 `// <market-logic>`이 아니라 `securityTagHtml` 곁(`// <tag-logic>`)에 둘 수 있다(문자열 생성만, DOM 없음). `marketTagHtml`이 `sessionTag`·`MARKET_COLORS`(`// <market-logic>`)를 쓰므로 테스트의 node 실행은 `tag-logic`과 `market-logic` 두 구간을 함께 불러온다. 매수 시트 제목줄은 `종목 매수` 옆에 `<span id="buyMarketTag">`.
- [ ] **Step 4: 통과 확인** — Run: 이 파일 → PASS, 전체 pytest·문법검사 통과. 화면 확인(서버 켜고 Playwright 375·1280): 가짜 `market_state`를 `/api/stock`·`/api/portfolio` 응답에 주입해 4가지 태그가 모바일 시트 제목줄과 PC 헤더 세 곳에 보이고, 태그를 누르면 팝업이 열리는지, 이름 긴 ETF에서도 칩 줄이 겹치지 않는지.
- [ ] **Step 5: Commit**
  ```bash
  git add frontend/index.html tests/test_frontend_market_tag.py
  git commit -m "feat(ui): show the market-session tag on stock detail headers and the buy sheet"
  ```

### Task 5: 프론트 — 확인창 경고·내 메뉴 토글·주문 사전 차단

**Files:**
- Modify: `frontend/index.html` (`<trade-dialog>` 구간의 `buyConfirmCfg`·`sellConfirmCfg`·`tradeView`, `#tradeModal`의 `<p id="tradeWarn">`, `renderTradeDialog`, `executeInlineBuy`·`executeSell`, 내 메뉴 행, `loadSession`, 새 `toggleClosedTrading`)
- Modify (필요하면): `tests/test_frontend_trade_dialog.py` — cfg·view의 모양을 정확히 비교하는 단언이 `warn` 키 때문에 깨지면 그 단언만 고친다
- Test: `tests/test_frontend_market_warning.py` (새 파일)

**Interfaces:**
- Consumes: Task 4까지의 `market_state` 모양, Task 2의 `/api/me`·`/api/settings`.
- Produces (`// <market-logic>`에 추가): `marketWarning(ms, closePrice: number) -> string`(정규장이면 `''`, Global Constraints 표 그대로, after의 N은 `closePrice.toLocaleString()`), `orderBlock(ms, allowClosed: boolean) -> string | null`(`allowClosed === false`이고 state가 `pre|after|closed`이면 서버와 같은 차단 문구, 그 밖에는 null — unknown은 null).
- `buyConfirmCfg(name, qty, totals, warn = '')`, `sellConfirmCfg(name, qty, full, est, warn = '')` → cfg에 `warn`, `tradeView(cfg, phase, errMsg)` → 뷰에 `warn`(confirm 단계에서만 값, busy·error는 `''`).
- 전역 `userSettings = {allow_closed_trading: true}`(`loadSession`이 `/api/me`의 `settings`로 채움), `toggleClosedTrading()`(`POST /api/settings` 뒤 서버 응답으로 갱신, 낙관적 갱신 없음).

- [ ] **Step 1: 실패하는 테스트 작성** — `test_frontend_market_warning.py`: `test_warning_text_table`(regular→`''`, pre/after/closed/unknown→ Global Constraints 문구와 정확히 같고 after는 `종가 230,500원`), `test_order_block_table`(false+pre/after/closed → 차단 문구, false+regular/unknown/없음 → null, true+모든 상태 → null), `test_confirm_cfgs_carry_warn`(buy·sell cfg의 `warn`이 인자 그대로, 기본 `''`), `test_trade_view_shows_warn_only_while_confirming`(confirm만 값, busy·error는 `''`), `test_trade_modal_has_a_warn_slot_between_lead_and_summary`(`id="tradeWarn"`이 `tradeDesc`와 `tradeSummary` 사이), `test_execute_buy_and_sell_check_the_block_first`(`executeInlineBuy`·`executeSell`이 `openTradeConfirm` 전에 `orderBlock(`을 부르고 막히면 `showToast(..., 'error')`로 알린 뒤 return, 경고는 `marketWarning(item.market_state, item.current_price)`·`marketWarning(h.market_state, h.current_price)`로 만든다), `test_menu_row_and_toggle`(알림 설정 행 뒤에 `id="closedTradingBtn"`, 상태 글자 `id="closedTradingState"`가 허용/차단, `toggleClosedTrading`이 `api('/api/settings', {method:'POST', body:{allow_closed_trading: ...}})`를 부르고 `loadSession`이 `userSettings`를 `data.settings`로 채움), `test_api_409_message_reaches_the_dialog`(`formatApiError(409, {detail: "…"})`가 문자열 그대로 — node로 실행).
- [ ] **Step 2: 실패 확인** — Run: `python -m pytest -q tests/test_frontend_market_warning.py` → FAIL.
- [ ] **Step 3: 구현** — 경고 문구와 차단 판단은 위 두 순수 함수만 쓰고 다른 곳에 문구를 복사하지 않는다(차단 문구는 서버 상수와 같은 글자, 테스트가 소스에서 비교). 경고 줄은 시안(보라 배경 `rgba(191,90,242,.14)`, 굵은 상태 이름 + 문장). 메뉴 행은 알림 설정 행과 같은 모양, 상태 글자 허용(초록)/차단(주황).
- [ ] **Step 4: 통과 확인** — Run: 이 파일 → PASS, 전체 pytest·문법검사 통과. 화면 확인(375·1280, 가짜 상태 주입): 정규장은 경고 없음, 애프터마켓·장 마감·unknown·프리마켓 확인창 경고, 메뉴 토글을 차단으로 바꾼 뒤 정규장이 아닐 때 확인창 대신 안내 토스트, 서버를 직접 호출했을 때 409 안내가 확인창 오류 영역에 나오는지.
- [ ] **Step 5: Commit**
  ```bash
  git add frontend/index.html tests/test_frontend_market_warning.py tests/test_frontend_trade_dialog.py
  git commit -m "feat(ui): closed-market warning in order dialogs and a menu toggle for the setting"
  ```
  (`test_frontend_trade_dialog.py`를 고치지 않았으면 `git add`에서 뺀다)

### Task 6: 기록과 관측 체크리스트

**Files:**
- Modify: `PROGRESS.md` (CRLF, Python으로 줄 끝을 유지해 편집) — 새 "장 상태·장 시간 안내" 항목과 기존 "시세 개선 2단계" 후속 정리

- [ ] **Step 1: PROGRESS.md 편집** — 구현함(날짜·브랜치·커밋 해시·PR 전), 규칙 표, 설정·409, 시간표 출처와 기준일, **한계**(프리마켓 `preMarket`·문구는 관측 전 가정, KRX 장전·장후 시각 추후, ETF의 NXT 여부는 `overMarketPriceInfo` 유무로만 판단, 실제 정규장·프리마켓 응답은 다음 거래일 관측 전)를 적는다.
- [ ] **Step 2: 관측 체크리스트를 같은 항목 끝에 적는다** — 거래일 08:00–09:00(프리마켓: `marketStatus`·`marketSessionType`·`closePrice`가 전일 종가인지)과 09:00–15:30(정규장: `OPEN`+`regularMarket`), 15:30 이후(애프터마켓), 휴장일 값. 관측하면 Global Constraints의 가정을 사실로 바꾸고 `pre` 테스트의 "가정" 표시를 지운다.
- [ ] **Step 3: 확인** — Run: `python -m pytest -q` → 전체 통과, `git diff --stat`에 `PROGRESS.md`만 있다.
- [ ] **Step 4: Commit**
  ```bash
  git add PROGRESS.md
  git commit -m "docs: record the market-session tags, hours popup and closed-market setting in PROGRESS.md"
  ```
