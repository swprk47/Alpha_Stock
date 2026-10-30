# 종목 개요 탭 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 종목 상세(모바일 매수 시트, PC 오른쪽 패널)에 `[시세·매수 | 개요]` 탭을 두고, 네이버 증권이 주는 소개·기본 정보·ETF 보유 자산·비중·뉴스 헤드라인을 출처와 기준을 달아 그대로 보여 준다.

**Architecture:** 새 서버 모듈 `backend/overview.py`가 네이버 모바일 API를 호출·정제·캐시하고, 카드(소개·기본 정보·보유 자산·비중·뉴스)마다 `ok/empty/error`를 담은 한 응답을 만든다. `GET /api/stock/{code}/overview`(로그인 필요)가 이를 내보낸다. 프론트는 `// <overview-logic>` 순수 함수 구간(렌더·상태 판단)과 탭 상태 변수(DOM 밖)를 두고, 모바일 시트·PC 검색/추천 상세에 같은 탭과 개요 본문을 연결한다.

**Tech Stack:** FastAPI, requests, `concurrent.futures`, pytest(+TestClient), 단일 `frontend/index.html`(Tailwind CDN, 순수 JS), node 로 프론트 순수 함수 검사.

**Spec:** `docs/superpowers/specs/2026-10-30-company-overview-design.md` (시안: https://claude.ai/artifact/TBPCSkMaH1SackKv78u8oB)

## Global Constraints

- 프론트 분리·프레임워크·SQLite 금지, `strategy.py` 수정 금지. 프론트는 `frontend/index.html` 한 파일.
- 종목코드는 `schemas.CODE_PATTERN`(`^[0-9A-Z]{6}$`) 한 곳만 쓴다. 코드 형식 오류는 400, 미로그인은 401(`get_current_user`).
- **앱이 만든 문장·숫자 없음**: 합계·"나머지"를 더하거나 빼서 만들지 않는다. 네이버 값이 없으면 `—`/안내 문구, 값 추측 금지. 허용되는 변형은 spec §3.4에 적힌 것뿐(운용사 끝 `(ETF)` 제거, 엔티티·`<br>`·태그 정제, 날짜 형식, 고정 번역표, 상장일 `20021014`→`2002.10.14`).
- 화면 글자는 13px 이상, 터치 대상 44px 이상. 서버가 준 글자는 반드시 이스케이프해서 넣는다(`innerHTML`에 원문 금지).
- 뉴스 링크는 `https://n.news.naver.com/`로 시작할 때만. `target="_blank" rel="noopener noreferrer"`.
- 모든 네이버 호출 타임아웃 4초, 서버 전체 동시 호출 6개, 캐시는 성공만. TTL: integration 60초 / finance·annual 6시간 / etfAnalysis 1시간 / news 5분 / 업종 표 24시간.
- 비중 표시는 소수 둘째 자리(`NN.NN%`), 총보수는 `f"{x:g}"`로 반올림 없이 `%`만 붙인다("연" 금지).
- 한 단계 = 한 커밋. 커밋 전 `python -m pytest -q`와 프론트 문법검사(`node --check`) 통과. main 직접 수정·푸시 금지(브랜치 `feat/company-overview`).
- 새 UI 문구는 spec/시안의 문구를 그대로 쓴다(임의로 바꾸지 않는다).

## Review Focus

1. **우선주·소개 없는 종목**: 네이버는 404가 아니라 200 + `corporationSummary: null`을 준다 → `about`은 `error`가 아니라 `empty`여야 한다(Task 2).
2. **글자에 섞인 HTML**: ETF 설명의 `<br><br>`, 가짜 `<script>` 같은 값이 화면에서 글자(또는 줄바꿈)로만 보이고 실행되지 않는다(Task 2 서버 정제, Task 4 프론트 이스케이프).
3. **60초 자동 갱신**: PC 패널이 통째로 다시 그려져도 선택한 탭과 받아 둔 개요가 유지된다(Task 4·6).
4. **종목을 연달아 바꿈/탭 빠른 전환**: 늦게 도착한 이전 종목 응답이 현재 화면을 덮지 않는다(Task 4).
5. **비중이 "-"·문자열·이상값**: 보유 자산 비중이 `"-"`, `"34.19%"`, 숫자, 빈 값, `NaN`일 때 막대와 글자가 깨지지 않는다(Task 2·4).
6. **캐시 때문에 오래된 값을 새것처럼 표시**: 푸터 "HH:MM에 가져왔어요"가 응답에 쓴 값 중 가장 오래된 것의 시각이다(Task 1·2).

---

### Task 1: 네이버 호출·캐시·정제 도구 (`backend/overview.py` 바탕)

**Files:**
- Create: `backend/overview.py`
- Create: `tests/test_overview_core.py`

**Interfaces:**
- Produces (모두 `backend/overview.py`):
  - `class OverviewFetchError(Exception)`
  - `fetch_json(path: str) -> Any` — `NAVER_BASE + path`를 `market_data.HEADERS`로 GET, 타임아웃 4초, 동시 6개 `Semaphore`. 200이 아니거나 JSON이 아니면 `OverviewFetchError`.
  - `class TtlCache` — `get_or_load(key: tuple, ttl_seconds: float, loader: Callable[[], Any]) -> tuple[Any, float]` (값, 가져온 epoch). 성공만 캐시, 같은 키의 동시 호출은 한 번만 `loader`를 돌리고 나머지는 그 결과를 기다림. `loader`가 예외면 그대로 올리고 캐시하지 않음. 시각 주입을 위해 생성자 `TtlCache(clock: Callable[[], float] = time.time)`.
  - `clean_text(value: Any, max_len: int) -> str` — 문자열이 아니면 `""`, `html.unescape` 후 `<br>`류→`\n`, 그 밖의 `<…>` 태그 제거, 앞뒤 공백 제거, `max_len` 초과 시 잘라냄. 그 밖의 글자(이중 공백, "합니다.한국거래소")는 보존.
  - `strip_issuer_suffix(name: str) -> str` — 끝의 `(ETF)` 한 가지만 제거.
  - `format_weight(value: Any) -> float | None` — 숫자(int/float, bool·NaN·inf 제외)와 `"34.19%"`/`"34.19"` 문자열은 float, `"-"`·빈 값·그 밖은 None.
  - `format_news_time(raw: Any) -> str` — `"202610302159"` → `"10.30 21:59"`, 이상하면 `""`.
  - `safe_news_url(url: Any) -> str` — `https://n.news.naver.com/`로 시작할 때만 통과, 아니면 `""`.

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_overview_core.py`
  - `test_clean_text_unescapes_and_converts_br`: `clean_text("a&quot;b<br><br>c", 100) == 'a"b\n\nc'`
  - `test_clean_text_strips_other_tags_and_keeps_spacing`: `clean_text("<script>x</script>합니다.한국거래소  끝", 100)`에 `<`가 없고 `"합니다.한국거래소  끝"`(이중 공백 포함)이 남음
  - `test_clean_text_non_string_and_length`: `clean_text(None, 10) == ""`, `clean_text(5, 10) == ""`, `len(clean_text("가"*50, 10)) == 10`
  - `test_strip_issuer_suffix_only_trailing_etf`: `"삼성자산운용(ETF)"→"삼성자산운용"`, `"미래에셋자산운용"` 그대로, `"(ETF)운용"` 그대로
  - `test_format_weight_table`: `"34.19%"→34.19`, `"2.3"→2.3`, `66.12→66.12`, `"-"→None`, `""→None`, `None→None`, `True→None`, `float("nan")→None`, `"abc"→None`
  - `test_format_news_time`: `"202610302159"→"10.30 21:59"`, `"2026"→""`, `None→""`
  - `test_safe_news_url`: n.news.naver.com https 만 통과, `http://…`, `javascript:…`, 다른 호스트, 비문자열은 `""`
  - `test_cache_returns_cached_within_ttl_and_expires`: 가짜 시계로 TTL 안에서는 `loader` 1회, TTL 뒤 2회, 반환 epoch가 처음 가져온 시각
  - `test_cache_does_not_store_failures`: `loader`가 예외 → 예외 전파, 다음 호출에서 다시 `loader` 실행
  - `test_cache_dedupes_concurrent_loads`: 스레드 8개가 같은 키를 동시에 요청 → `loader` 1회(`Barrier`/`Event`로 겹치게)
  - `test_fetch_json_errors_become_overview_fetch_error`: `requests.get`을 monkeypatch해 5xx·`Timeout`·JSON 아닌 본문 각각에서 `OverviewFetchError`
  - `test_fetch_json_limits_concurrency_to_six`: 느린 가짜 `requests.get` 12개 동시 → 동시에 실행 중인 수 최대 6

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_overview_core.py -q` → `ModuleNotFoundError: overview`로 실패.

- [ ] **Step 3: 구현** — 위 시그니처대로 `backend/overview.py`를 만든다. 캐시는 키별 `threading.Lock`/진행 중 `Event`로 중복 호출을 막고, `fetch_json`의 세마포어는 모듈 전역 `threading.Semaphore(6)`, 상수 `NAVER_BASE = "https://m.stock.naver.com"`, `CALL_TIMEOUT = 4`, `MAX_CONCURRENT_CALLS = 6`을 모듈 위에 둔다. `HEADERS`는 `market_data.HEADERS`를 가져다 쓴다(복사 금지).

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/test_overview_core.py -q` → 전부 PASS.

- [ ] **Step 5: 커밋** — `git add backend/overview.py tests/test_overview_core.py && git commit -m "feat(overview): add Naver fetch, TTL cache and text sanitizers"`

---

### Task 2: 카드 만들기와 `get_overview` (`backend/overview.py` 확장)

**Files:**
- Modify: `backend/overview.py`
- Create: `tests/fixtures/overview/` (아래 실응답 발췌 JSON)
- Create: `tests/test_overview_cards.py`

**Interfaces:**
- Consumes: Task 1의 `fetch_json`, `TtlCache`, `clean_text`, `strip_issuer_suffix`, `format_weight`, `format_news_time`, `safe_news_url`, `OverviewFetchError`; `market_data.safe_security_type`.
- Produces (`backend/overview.py`):
  - 카드 모양(spec §3.3): 각 카드는 `{"status": "ok"|"empty"|"error", ...}`.
  - `build_about_stock(finance: dict | None) -> dict` — `finance["corporationSummary"]`의 `comment1~3`을 `clean_text(…, 400)`로 정제한 비지 않은 것만 `{"status":"ok","title":"회사 소개","paragraphs":[…]}`. `corporationSummary`가 null/없음이거나 문단이 하나도 없으면 `{"status":"empty","title":"회사 소개","paragraphs":[]}`.
  - `build_about_etf(etf: dict) -> dict` — `etfSummary`를 `clean_text(…, 3000)`; 문단은 `\n\n`으로 나눈 것(빈 줄 제외). 제목 `"이 ETF는"`. 비면 `empty`.
  - `build_facts_stock(integration: dict, industry_names: dict[str, str]) -> dict` — 항목 순서 고정: 업종(`industry_names.get(str(integration["industryCode"]))`, 없으면 `—`), 시가총액(`totalInfos` code `marketValue`, note `"현재 시세 기준"`), PER(`per`, note `f"{valueDesc} 실적 기준"`), PBR(`pbr`, 같음), 배당수익률(`dividendYieldRatio`, note `f"{valueDesc} 기준"`), 외인소진율(`foreignRate`, note `""`). 값은 `clean_text`한 네이버 문자열 그대로, 없으면 `"—"`. `valueDesc`가 없으면 note `""`. 항목은 `{"label","value","note"}`.
  - `build_facts_etf(etf: dict) -> dict` — 기초지수(`etfBaseIndex`), 운용사(`strip_issuer_suffix(clean_text(issuerName))`), 총보수(숫자면 `f"{x:g}%"`, 아니면 `—`), 상장일(`"20021014"`→`"2002.10.14"`, 이상하면 `—`).
  - `build_holdings(etf: dict) -> dict` — `etfTop10MajorConstituentAssets` → `{"status":"ok","items":[{"name","count","weight": float|None}]}` (`name`=`clean_text(itemName, 80)`, `count`=`clean_text(stockCount, 20)`, `weight`=`format_weight(etfWeight)`). 목록이 비면 `empty`. 이름이 빈 항목은 버림.
  - `build_weights(etf: dict) -> dict` — `{"status":"ok"|"empty","cards":[{"key":"sector"|"country"|"asset","title":"업종별 비중"|"국가별 비중"|"자산별 비중","total": float|None,"items":[{"label","weight":float}]}]}`. **순서 업종→국가→자산.** 업종은 첫 항목 코드가 `UNCLASSIFIED`가 아닐 때만, 국가는 첫 항목이 `KR`이 아닐 때만, 자산은 `EQUITY` 비중이 50 미만일 때만. 각 카드는 `weight > 0`인 앞 5개(응답 순서), `total`은 `...TotalWeight`(네이버 값, 없으면 None). 라벨은 spec §3.4 고정표로 한글, 표에 없으면 영어 원문. 보여줄 카드가 없으면 `empty`.
  - `build_news(news: list | None) -> dict` — 클러스터마다 첫 기사, 최대 5개: `{"title": clean_text(titleFull or title, 200), "office", "time": format_news_time(datetime), "url": safe_news_url(mobileNewsUrl), "more": max(total-1, 0)}`. 제목이 비거나 url이 `""`인 기사는 버림. 하나도 없으면 `empty`.
  - `SECTOR_LABELS`, `COUNTRY_LABELS`, `ASSET_LABELS: dict[str, str]` (spec §3.4 표 그대로).
  - `error_card(title: str = "") -> dict` → `{"status":"error"}`(+필요한 빈 필드).
  - `get_overview(code: str, cache: TtlCache | None = None, clock=time.time) -> dict` — 흐름: ① `integration`(TTL 60) 먼저. 성공하면 `kind = safe_security_type(integration["stockEndType"])`, 실패하면 `kind=""`이고 `about/facts/holdings/weights`는 `error`. ② 종류별 `ThreadPoolExecutor(max_workers=3)` 병렬: `stock`→`finance/annual`(TTL 6h)+업종 표(`/api/stocks/industry?page=1&pageSize=100`, TTL 24h, `groups[].no/name`→`{str(no): name}`)+`news`(TTL 5분, `/api/news/stock/{code}?pageSize=5&page=1`); `etf`→`etfAnalysis`(TTL 1h)+`news`; `etn`/`""`(integration 성공)→`news`만, `about`·`facts`는 `empty`(ETN 안내), `holdings`·`weights`는 `empty`. ③ 각 소스 실패는 그 소스에 속한 카드만 `error`(뉴스 실패는 `news`만). 소스 JSON이 예상 모양이 아니면 `error_card`이고 `print(f"Overview parse error {code} {source}: {e}")`. 응답: `{"success": True, "code", "kind", "fetched_at": "%Y-%m-%d %H:%M:%S"(성공한 소스들 중 가장 오래된 가져온 epoch), "source_url", "about","facts","holdings","weights","news"}`; 성공한 소스가 없으면 `fetched_at`은 `""`. `source_url`은 아래 Step 6에서 확인한 주소 템플릿(확인 못 하면 `""`).

- [ ] **Step 1: 실응답 발췌 fixture 만들기** — `tests/fixtures/overview/`에 아래를 저장한다(실제 GET 한 번으로 받아 필요한 키만 남기고 각 파일 20KB 이하). 네트워크는 이 단계에서만 쓰고 테스트는 파일만 읽는다.
  - `integration_005930.json`(`stockEndType`,`industryCode`,`totalInfos` 중 marketValue/per/pbr/dividendYieldRatio/foreignRate), `integration_069500.json`(etf)
  - `finance_005930.json`(`corporationSummary` 3문장), `finance_005935.json`(우선주: `corporationSummary: null`)
  - `etf_069500.json`(국내: 비중 "34.19%", sector IT 66.12…, country KR), `etf_360750.json`(해외: 비중 "-", `<br><br>` 설명, sector+country US 94.73), `etf_153130.json`(채권: sector UNCLASSIFIED 99.91, asset BOND 62.65/CASH 37.26, 긴 설명)
  - `industry.json`(`{"groups":[{"no":278,"name":"반도체와반도체장비"},…]}` 발췌), `news_005930.json`(클러스터 5개, `total>1` 포함 1개)

- [ ] **Step 2: 실패하는 테스트 작성** — `tests/test_overview_cards.py`(`overview.fetch_json`을 fixture 로 대체하는 `fake_fetch(routes)` 헬퍼, 호출 경로 기록)
  - `test_stock_about_has_three_paragraphs_verbatim`: 005930 → `paragraphs[1]`이 `"DX 부문은 TV, 냉장고, 스마트폰을, DS 부문은 DRAM, NAND Flash 등의 반도체를, SDC는 OLED 패널을, Harman은 전장부품 및 오디오 제품을 생산·판매하고 있음."`
  - `test_preferred_share_null_summary_is_empty_not_error`: 005935 → `about.status == "empty"` (Review Focus 1)
  - `test_stock_facts_order_values_and_notes`: 항목 라벨 순서 `["업종","시가총액","PER","PBR","배당수익률","외인소진율"]`, 업종 `"반도체와반도체장비"`, 시총 note `"현재 시세 기준"`, PER note `"2026.06. 실적 기준"`, 배당수익률 note `"2025.12. 기준"`
  - `test_unknown_industry_code_shows_dash`
  - `test_etf_domestic`: 069500 → 운용사 `"삼성자산운용"`(접미사 제거), 총보수 `"0.15%"`, 상장일 `"2002.10.14"`, 보유 자산 10개·첫 `weight == 34.19`, weights 카드 순서 `["sector"]`(국가 KR이라 숨김, 자산 EQUITY≥50이라 숨김), 업종 라벨 `["IT","산업재","금융","경기소비재","커뮤니케이션"]`와 `total == 99.05`, **업종 값을 합산한 필드가 응답 어디에도 없음**
  - `test_etf_overseas_names_only_and_sector_above_country`: 360750 → 보유 자산 `weight is None` 전부, `count == "348"`(첫 항목), weights 카드 키 순서 `["sector","country"]`, 총보수 `"0.0068%"`, 설명 문단에 `<br>`·`<` 없음 (Review Focus 2·5)
  - `test_etf_bond_hides_sector_and_shows_asset`: 153130 → 카드 키 `["asset"]`, 라벨 `["채권","현금"]`
  - `test_unknown_codes_keep_raw_label`: 표에 없는 업종 코드(예: `"SPACE"`)는 영어 원문 그대로
  - `test_news_dedup_more_and_link_whitelist`: `total=4` 클러스터 → `more == 3`, 허용되지 않는 URL 기사는 응답에서 빠짐, 시간 `"10.30 21:59"` 형식, 최대 5개
  - `test_etn_and_unknown_kind_only_try_news`: integration `stockEndType:"etn"` → `finance/annual`·`etfAnalysis` 호출 없음, `about.status == "empty"`, `news` 호출됨
  - `test_integration_failure_marks_cards_error_but_news_still_loads`: integration 예외 → `kind == ""`, about/facts/holdings/weights `error`, `news` `ok`
  - `test_one_source_failure_is_isolated`: 005930에서 `finance/annual`만 예외 → `about.status == "error"`, `facts`/`news` 그대로 `ok`
  - `test_all_fail_returns_all_cards_error`: 전부 예외 → HTTP-level 예외 없이 모든 카드 `error`, `fetched_at == ""`
  - `test_malformed_source_is_error_not_guess`: `etfSummary`가 리스트인 모양 등 → 해당 카드 `error`(값을 채우지 않음)
  - `test_fetched_at_is_the_oldest_source_time`: 소스마다 다른 가짜 시각을 주고 가장 오래된 것이 `fetched_at`
  - `test_cache_ttls_applied_per_source`: 가짜 시계로 60초/6시간/1시간/5분/24시간 경계에서 호출 횟수 확인(구성: 각 TTL 직전 재호출 없음, 직후 재호출)

- [ ] **Step 3: 실패 확인** — `python -m pytest tests/test_overview_cards.py -q` → import/속성 오류로 실패.

- [ ] **Step 4: 구현** — 위 시그니처대로 `backend/overview.py`에 추가. 모든 `build_*`는 순수 함수(네트워크·시계 없음)이고 입력을 방어적으로 읽는다(`isinstance` 확인, 예외는 `get_overview`가 카드 단위로 잡아 `error_card`).

- [ ] **Step 5: 통과 확인** — `python -m pytest tests/test_overview_cards.py tests/test_overview_core.py -q` → 전부 PASS.

- [ ] **Step 6: `source_url` 확인** — 실제로 `curl -s -o /dev/null -w "%{http_code}" https://m.stock.naver.com/domestic/stock/005930/total`와 ETF(`069500`) 두 주소가 200인지 확인해, 둘 다 200이면 템플릿 `SOURCE_URL = "https://m.stock.naver.com/domestic/stock/{code}/total"`로 고정. 하나라도 아니면 `SOURCE_URL = ""`(화면은 링크 없이 "출처: 네이버 증권"만). 결과를 커밋 메시지에 적는다. 테스트 `test_source_url_is_empty_or_naver_https`: `source_url`이 `""`이거나 `https://m.stock.naver.com/`로 시작.

- [ ] **Step 7: 커밋** — `git add backend/overview.py tests/test_overview_cards.py tests/fixtures/overview && git commit -m "feat(overview): build stock/ETF overview cards from Naver responses"`

---

### Task 3: 엔드포인트와 로그인 (`backend/server.py`)

**Files:**
- Modify: `backend/server.py` (`stock_detail_api` 아래에 추가)
- Create: `tests/test_overview_api.py`

**Interfaces:**
- Consumes: `overview.get_overview(code) -> dict`, `schemas.CODE_PATTERN`, `get_current_user`.
- Produces: `GET /api/stock/{code}/overview` → 200 `get_overview` 결과, 400 코드 형식 오류, 401 미로그인. 함수 이름 `stock_overview_api(code: str, user: dict = Depends(get_current_user)) -> dict`.

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_overview_api.py`(`conftest.client`/`login` 사용, `server.get_overview`를 monkeypatch)
  - `test_requires_login_401`: 로그인 없이 호출 → 401, 네이버 호출(가짜 `get_overview`) 없음
  - `test_bad_code_400`: `"abc"`, `"005930X"`, 소문자 `"0183j0"` → 400이고 `get_overview` 호출 없음; 신형 코드 `"0183J0"`은 통과
  - `test_returns_overview_payload`: 가짜 응답을 그대로 200 JSON으로 돌려줌(`success`, `kind`, 카드 키 5개)
  - `test_existing_stock_detail_stays_public`: `/api/stock/005930`은 로그인 없이 지금처럼 동작(회귀)
  - `test_route_is_not_shadowed_by_stock_detail`: `/api/stock/005930/overview`가 상세(`/api/stock/{code}`)로 잡히지 않음

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_overview_api.py -q` → 404/ImportError로 FAIL.

- [ ] **Step 3: 구현** — `server.py`에 `from overview import get_overview` 추가, 위 라우트를 `stock_detail_api` 아래에 등록. 코드 검증은 `stock_detail_api`와 같은 방식(`re.fullmatch(CODE_PATTERN, code)` → 400, 같은 한국어 메시지).

- [ ] **Step 4: 전체 통과** — `python -m pytest -q` → 기존 테스트 포함 전부 PASS.

- [ ] **Step 5: 커밋** — `git add backend/server.py tests/test_overview_api.py && git commit -m "feat(api): add login-required /api/stock/{code}/overview"`

---

### Task 4: 프론트 순수 로직 `// <overview-logic>`

**Files:**
- Modify: `frontend/index.html` (프론트 `// <logo-logic>` 근처, `// <overview-logic>` … `// </overview-logic>` 구간 신설)
- Create: `tests/test_frontend_overview_logic.py`

**Interfaces:**
- Consumes: 서버 응답 모양(Task 2). 기존 `securityTagHtml` 등은 쓰지 않는다(구간은 독립).
- Produces (구간 안, 전역 함수·상수):
  - `OVERVIEW_TTL_MS = 300000`
  - `ovEsc(text: any) -> string` — `&<>"'`를 이스케이프, 문자열이 아니면 `''`.
  - `ovShouldFetch(entry: {data, fetchedAt, hasError}|undefined, now: number, force: boolean) -> boolean` — 없으면 true, `force && entry.hasError`이면 true, `now - fetchedAt >= OVERVIEW_TTL_MS`이면 true, 아니면 false.
  - `ovNextTab(current: 'trade'|'overview', requested: any) -> 'trade'|'overview'` — 모르는 값이면 `'trade'`.
  - `ovAllFailed(data) -> boolean` — 모든 카드(`about,facts,holdings,weights,news`)가 `error`이거나 `data`가 없음.
  - `ovBarWidth(weight: any) -> number` — 0~100 사이 숫자, 숫자가 아니면 0.
  - `ovWeightText(weight: any) -> string` — 숫자면 `toFixed(2)+'%'`, 아니면 `''`.
  - `ovBodyHtml(view: {status: 'loading'|'ready'|'failed', data}, kind: string, opts: {aboutOpen: boolean, layout: 'one-col'|'two-col'}) -> string` — 개요 본문 전체 HTML(시안의 카드 순서: 소개 → 기본 정보 → 보유 자산 → 비중 카드들 → 뉴스 → 푸터). `loading`은 카드마다 `sk` 스켈레톤, `failed`는 전체 실패 안내 + "다시 시도" 버튼(`onclick="retryOverview()"`), `ready`는 카드별로 `ok`면 내용, `empty`면 spec/시안의 빈 문구, `error`면 그 카드에만 안내 + "다시 시도". 모든 서버 문자열은 `ovEsc`를 거친다.
  - `ovTabsHtml(active: 'trade'|'overview') -> string` — `role="tablist"`, 탭 2개(`시세·매수`,`개요`), `aria-selected`, `tabindex`, `onclick="selectOverviewTab('trade'|'overview')"`, 기존 탭 클래스(`min-h-[40px] rounded-[9px]`, 선택 `bg-[#f5f5f7] text-[#111]`)를 재사용.
  - `ovAboutHtml(card, expanded: boolean) -> string` — ETF 설명(`card.title === '이 ETF는'`)의 글자 수가 200자를 넘고 `expanded`가 false이면 본문에 4줄 제한(`-webkit-line-clamp:4`)을 걸고 `더보기` 버튼(`onclick="toggleOverviewAbout()"`, `min-h-[44px]`)을 붙인다. 펼치면 전체와 `접기`. 200자 이하이거나 주식 소개는 접지 않는다. 접힌 글자도 원문 그대로이고 줄 수만 제한한다(시안의 채권 ETF).
  - 그 밖의 카드 보조 `ovFactsHtml(card)`, `ovHoldingsHtml(card)`, `ovWeightsHtml(card)`, `ovNewsHtml(card)`, `ovFooterHtml(data, kind)` (모두 순수).

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_frontend_overview_logic.py`(`_section('overview-logic')`를 node 로 평가, 기존 `test_frontend_market_logic.py` 방식)
  - `test_esc_escapes_markup`: `ovEsc('<script>alert(1)</script>&"\'')`에 `<`가 없고 `&lt;script&gt;` 포함; `ovEsc(null) === ''`
  - `test_body_never_emits_raw_server_markup`: 소개 문단·뉴스 제목·보유 자산 이름에 `<img src=x onerror=alert(1)>`를 넣은 데이터로 `ovBodyHtml`을 돌려 결과에 `<img`가 없고 `&lt;img`가 있음 (Review Focus 2)
  - `test_loading_shows_skeletons_and_failed_shows_retry`: `loading`에 `sk` 클래스, `failed`에 `다시 시도`·`retryOverview()`
  - `test_card_states`: 같은 응답에서 `news.status:'error'`면 뉴스 카드에만 `뉴스를 불러오지 못했어요.`와 다시 시도 버튼, 소개·기본 정보는 그대로 나옴; `about.status:'empty'`(주식)에 `이 종목은 네이버 증권에 회사 소개가 없어요. 우선주, 신규 상장, 스팩 종목에서 그럴 수 있어요.`; ETN/종류 불명(kind `etn`)에 `이 종목의 개요 정보는 아직 제공하지 않아요. 시세·매수 탭은 그대로 쓸 수 있어요.`
  - `test_all_failed_collapses_to_one_message`: 모든 카드 `error` → `종목 정보를 불러오지 못했어요`가 한 번, 카드 제목은 없음; `ovAllFailed` 참/거짓 경계
  - `test_weights_hide_nonnumeric_and_clamp`: 비중 `null`/`'-'`/`NaN`/`-5`/`250`일 때 `ovBarWidth`가 0/0/0/0/100, 보유 자산 비중이 전부 `null`이면 막대(`track`) 없이 이름·수량만, 문구 `이 ETF는 비중을 제공하지 않아서 이름과 보유 수량만 보여요.` (Review Focus 5)
  - `test_weights_cards_use_titles_and_network_total`: `total`이 있으면 `네이버 합계 99.05%`, 없으면 합계 문구 없음; 앱이 합계를 계산하지 않음(가중치 값 두 개를 줘도 그 합이 화면에 나오지 않음)
  - `test_news_more_link_and_attrs`: `more:3`이면 `외 3건`, 링크에 `target="_blank"`와 `rel="noopener noreferrer"`, 터치 대상 `min-h-[44px]`
  - `test_footer_text`: `출처: 네이버 증권`, `fetched_at`의 `HH:MM` + `에 가져왔어요`, `정보 제공용이며 투자 권유가 아니에요`; ETF만 `구성 비중의 기준일은 제공되지 않아요.`; `source_url`이 있으면 링크, 없으면 글자만
  - `test_tabs_html_reuses_existing_tab_look`: `role="tablist"`, 선택 탭 `aria-selected="true"`, 클래스 `bg-[#f5f5f7]`, 개요·시세·매수 문구
  - `test_long_etf_about_is_clamped_with_more_button`: 550자 ETF 설명 + `expanded=false` → `-webkit-line-clamp:4`와 `더보기`, 전체 원문이 DOM에 그대로 있음(자르지 않음); `expanded=true` → clamp 없음, `접기`; 100자 설명·주식 소개(긴 것도)에는 버튼 없음
  - `test_next_tab_and_should_fetch`: `ovNextTab('trade','overview')`, `ovNextTab('trade','x')`==`'trade'`; `ovShouldFetch(undefined, 0, false)` true, 5분 안 false, 5분 뒤 true, `hasError`+`force` true (Review Focus 3·4)
  - `test_no_font_below_13px_or_touch_below_44px_in_section`: 구간의 텍스트 크기 클래스가 `text-[13px]`·`text-sm` 이상이고 `text-xs`·`text-[11px]`·`text-[12px]` 없음, 버튼에 `min-h-[44px]`

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_frontend_overview_logic.py -q` → `overview-logic 구간이 없습니다`로 FAIL.

- [ ] **Step 3: 구현** — `frontend/index.html`에 구간을 추가한다(파일은 CRLF 작업본이니 Edit 도구로 편집). 비중 색은 spec §4.3: 구성종목 막대는 `#0a84ff` 한 색, 업종·국가·자산 막대는 `['#0a84ff','#ffb340','#30d158','#64d2ff','#ff7aa2']` 순서이고 범례 점과 같은 색. 막대 폭은 `ovBarWidth`.

- [ ] **Step 4: 통과 확인과 문법검사** — `python -m pytest tests/test_frontend_overview_logic.py -q` PASS, 이어서 CLAUDE.md의 프론트 문법검사(`node --check`) 통과.

- [ ] **Step 5: 커밋** — `git add frontend/index.html tests/test_frontend_overview_logic.py && git commit -m "feat(frontend): add overview-logic section (tabs, cards, escaping)"`

---

### Task 5: 모바일 매수 시트에 탭과 개요 연결

**Files:**
- Modify: `frontend/index.html` — `#buyModal` 마크업(차트·AI 진단·매수 패널을 `#buyTradeBody`로 감싸고 `#buyOverviewBody`와 `#buyTabs`를 추가), `openCustomBuyModal`, `closeBuyModal`, 상태 변수·탭 함수
- Create: `tests/test_frontend_overview_sheet.py`

**Interfaces:**
- Consumes: Task 4의 `ovTabsHtml`, `ovBodyHtml`, `ovNextTab`, `ovShouldFetch`, `ovAllFailed`; 기존 `api()`, `buySheetItem`, `closeBuyModal`.
- Produces (전역, `// <overview-state>` 구간 또는 `// <overview-logic>` 바로 아래 비순수 구간):
  - `let overviewTab = 'trade'`, `let overviewData = {}` (`{[code]: {data, fetchedAt, hasError}}`), `let overviewReq = 0`, `let overviewAboutOpen = false`(ETF 설명 펼침; 종목·탭이 바뀌면 false), `toggleOverviewAbout()`(값을 뒤집고 시트·패널을 다시 그림)
  - `selectOverviewTab(tab)` — `overviewTab = ovNextTab(overviewTab, tab)`, 모바일 시트와 PC 패널을 같은 상태로 다시 그림, 시트 스크롤 맨 위, 개요이면 `loadOverview`.
  - `async loadOverview(code, force = false)` — `ovShouldFetch`가 true일 때만 `api('/api/stock/'+code+'/overview')`; 요청마다 `++overviewReq`로 번호를 잡고 **번호가 어긋나면 결과를 버림**(종목 전환·빠른 탭 전환); `ApiError` 401이면 캐시를 비우고(로그인 창은 `api()`가 이미 띄움) 실패 문구를 남기지 않음; 그 밖의 예외는 `failed`.
  - `retryOverview()` — 현재 종목에 `loadOverview(code, true)`.
  - `applyBuyTab()` — 모바일 시트에서 탭 표시, `#buyTradeBody`/`#buyOverviewBody` 보이기·감추기, 제목 `종목 매수`↔`종목 정보`, 부제 `시드머니 맞춤 매수 시뮬레이션`↔`이 종목이 어떤 종목인지 살펴봐요`.

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_frontend_overview_sheet.py`(기존 `test_frontend_buy_sheet.py`·`test_frontend_holding_info.py`의 `_func`/`_section` 방식)
  - `test_sheet_markup_has_tabs_between_header_card_and_body`: `id="buyTabs"`가 `id="buyStockPrice"` 뒤, `id="buyTradeBody"` 앞; 차트(`buyModalChartWrap`)·`gradeCard`·`buySheetPanel`이 `buyTradeBody` 안에 있고 `buyOverviewBody`는 그 밖
  - `test_opening_always_starts_on_trade_tab`: `openCustomBuyModal` 본문에 `overviewTab = 'trade'`와 `applyBuyTab()`이 포함되고 열 때 스크롤이 0
  - `test_tab_switch_updates_title_and_resets_scroll`: `applyBuyTab`·`selectOverviewTab` 본문이 `buyModalTitle`·`buyModalSubtitle`·`scrollTop = 0`을 건드림, 제목 문구 정확히 `종목 정보`/`종목 매수`
  - `test_load_overview_uses_api_helper_and_ignores_stale_responses`: `loadOverview`가 `api('/api/stock/${code}/overview')`를 쓰고 `overviewReq` 비교로 늦은 응답을 버림; 401 분기에서 `overviewData`를 삭제 (Review Focus 4)
  - `test_overview_state_lives_outside_the_dom`: `overviewTab`·`overviewData`가 모듈 최상위 `let`이고 `renderDetailPane`이 이 값을 다시 읽는지(함수 본문에 `overviewTab` 참조)
  - `test_close_sheet_keeps_nothing_stale`: `closeBuyModal`이 탭을 `trade`로 되돌리고 진행 중 요청 번호를 올림
  - `test_close_button_and_retry_hit_targets`: 개요 본문의 "다시 시도"·"더보기"류 버튼에 `min-h-[44px]`
  - node 동작 테스트: `ovShouldFetch`·`loadOverview` 요청 번호 로직을 `api`를 가짜로 바꿔 평가 — 종목 A 요청이 늦게 끝나도 종목 B 화면 상태를 덮지 않음, 5분 안에는 두 번째 호출이 `api`를 부르지 않음

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_frontend_overview_sheet.py -q` → FAIL.

- [ ] **Step 3: 구현** — 마크업: `#buyModal` 패널에서 종목 정보 카드 다음에 `<div id="buyTabs">`를 두고, 차트 래퍼·`gradeCard`·`buySheetPanel`을 `<div id="buyTradeBody" class="flex flex-col gap-2.5">`로 감싸고 그 뒤에 `<div id="buyOverviewBody" class="hidden flex flex-col gap-2.5">`를 둔다. `selectOverviewTab`/`applyBuyTab`은 `ovTabsHtml`·`ovBodyHtml`로 그린다. `openCustomBuyModal` 시작부에서 `overviewTab = 'trade'`, `closeBuyModal`에서 탭 초기화·`++overviewReq`. 스윙 추천 모바일(`openBuyModal` → `openCustomBuyModal`)과 보유 종목 알약(`selectSearchResult`)이 같은 시트를 쓰므로 추가 연결은 필요 없다.

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/test_frontend_overview_sheet.py tests/test_frontend_buy_sheet.py tests/test_frontend_holding_info.py -q` PASS, `node --check`.

- [ ] **Step 5: 커밋** — `git add frontend/index.html tests/test_frontend_overview_sheet.py && git commit -m "feat(frontend): add overview tab to the mobile buy sheet"`

---

### Task 6: PC 검색·추천 상세에 탭과 개요 연결 + 실화면 확인

**Files:**
- Modify: `frontend/index.html` — `searchDetailHtml`, `recDetailHtml`, `renderDetailPane`(차트 그리기 조건), `selectSearchResult`/`closeSearchStock`/추천 선택 시 탭 초기화
- Create: `tests/test_frontend_overview_pc.py`

**Interfaces:**
- Consumes: Task 4·5의 `ovTabsHtml`, `ovBodyHtml`, `overviewTab`, `overviewData`, `selectOverviewTab`, `loadOverview`.
- Produces: `overviewPaneBody(code, kind) -> string`(비순수 소형 래퍼: 현재 `overviewData[code]`와 로딩 여부로 `ovBodyHtml` 호출) — `searchDetailHtml`·`recDetailHtml`이 헤더 다음에 `ovTabsHtml(overviewTab)`를 넣고, `overviewTab === 'overview'`이면 기존 본문(차트·지표 카드·AI·매수) 대신 `overviewPaneBody`를 반환한다. PC 보유 상세(`holdingDetailHtml`)는 건드리지 않는다.

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_frontend_overview_pc.py`
  - `test_search_and_rec_detail_have_tabs_after_header_and_before_body`: 두 함수 본문에서 `ovTabsHtml(` 위치가 헤더(`<h2`) 뒤·차트(`pcChartPanel`) 앞
  - `test_overview_replaces_body_only_when_selected`: 두 함수가 `overviewTab === 'overview'`일 때 차트·AI·매수 패널을 만들지 않고 `overviewPaneBody`를 씀; 기본 `trade`면 기존 출력과 같음(회귀: 기존 `test_frontend_pc_layout.py` 통과)
  - `test_holding_detail_has_no_tabs`: `holdingDetailHtml` 본문에 `ovTabsHtml`·`overviewTab`이 없음
  - `test_render_detail_pane_draws_chart_only_on_trade_tab`: `renderDetailPane`에서 `drawPcChart`가 `overviewTab`이 `trade`일 때만 불림(개요 탭에서 없는 캔버스를 그리지 않음)
  - `test_tab_selection_resets_when_selection_changes`: `selectSearchResult` 시작과 추천 카드 선택·`closeSearchStock`에서 `overviewTab`을 `trade`로 되돌림; 같은 종목의 60초 갱신 재그림에서는 되돌리지 않음(`renderDetailPane` 본문에 초기화 없음) (Review Focus 3)
  - `test_pc_overview_two_column_layout`: 개요 본문 래퍼가 `lg:` 두 열 그리드(왼쪽 소개·기본 정보·업종, 오른쪽 보유 자산·뉴스)이며 모바일은 한 열

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_frontend_overview_pc.py -q` → FAIL.

- [ ] **Step 3: 구현** — `ovBodyHtml`이 모바일 한 열용이라면 PC에서는 같은 카드들을 `lg:grid lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]` 래퍼 안에 놓는다(카드 HTML은 재사용하고 컬럼 배치는 호출 쪽에서 옵션 `layout: 'two-col'`로). `searchDetailHtml`/`recDetailHtml`은 헤더 블록과 본문 블록으로 나눠 탭을 사이에 둔다.

- [ ] **Step 4: 통과 확인** — `python -m pytest -q` 전체 PASS, `node --check`.

- [ ] **Step 5: 실화면 확인(Playwright)** — 서버를 켜고(`ALLOW_DEV_LOGIN=true`, 테스트 계정 `zz_ov`) 모바일 375·360, PC 1280에서: 삼성전자(주식) · 우선주 005935(소개 없음) · KODEX 200(국내 ETF) · TIGER 미국S&P500 360750(해외, 업종이 국가 위) · KODEX 단기채권 153130(채권: 긴 설명이 4줄로 접히고 `더보기`로 펼쳐지는지) · 스윙 추천 종목 · 보유 종목의 "종목 정보" 알약으로 열기. 각각 탭 전환, 개요 표시, 60초 갱신(`renderPortfolio()` 호출)으로 탭이 유지되는지, 로그아웃 후 개요 탭을 열면 로그인 창이 뜨는지 확인한다. 네이버 차단은 `overview.fetch_json`을 실패시키는 임시 환경변수 없이 **서버를 껐다 켜지 않고** `fetch`를 가로채 실패 응답으로 바꾸는 방식으로 흉내 내서 부분 실패·전체 실패 화면을 본다. 테스트 계정(`zz_` 접두)만 만들고 확인 뒤 지운다(`swprk` 계정 파일은 절대 열거나 지우지 않는다). 모바일 시트는 첫 화면에서 가격 머리가 계속 보이는지 본다.

- [ ] **Step 6: 커밋** — `git add frontend/index.html tests/test_frontend_overview_pc.py && git commit -m "feat(frontend): add overview tab to PC search and recommendation detail"`

---

### Task 7: PROGRESS.md 기록과 PR 준비

**Files:**
- Modify: `PROGRESS.md`(CRLF 유지) — 종목 개요 항목(구현 내용, 확인한 네이버 응답과 날짜, 한계: ETN·기준일·약관 위험)과 기존 "종목 개요 탭(미착수)" 항목 정리

- [ ] **Step 1:** 기존 미착수 항목(`종목 개요 탭(사용자 요청 2026-10-28, 미착수)`)을 완료 기록으로 바꾸고 spec §8의 한계를 그대로 옮긴다. 줄바꿈은 `\r\n`.
- [ ] **Step 2: 전체 검증** — `python -m pytest -q` 전체 통과, `node --check`.
- [ ] **Step 3: 커밋** — `git add PROGRESS.md && git commit -m "docs: record the company overview tab in PROGRESS.md"`
- [ ] **Step 4:** push/PR/CI/머지는 **사용자가 말할 때만**. 사용자에게 "직접 확인하실 것" 표(무엇을·어디서·정상이면·주의)로 보고한다.

---

## Self-Review

- **Spec 커버리지**: §1(출처·탭·진입점·기본 정보) Task 2·5·6, §2(응답) Task 2 fixture, §3.1–3.5(엔드포인트·호출·응답·정제·캐시) Task 1–3, §4.1–4.4(탭·상태·렌더·진입점) Task 4–6, §6(테스트) 각 Task, §7(순서) Task 1–7, §8(위험) Task 7 PROGRESS, D1 Task 3(401), D2 Task 2 Step 6. PC 보유 상세 제외는 Task 6 회귀 테스트가 지킨다.
- **타입 일관성**: 카드 키(`about/facts/holdings/weights/news`), `status` 값, `weights.cards[].key`, `news.items[].more`, `overviewTab`('trade'|'overview'), `overviewData[code] = {data, fetchedAt, hasError}`를 Task 2·4·5·6에서 같은 이름으로 썼다.
- **비례**: 코드 본문은 시그니처·테스트 이름·단언 위주로 두었다.
- **알려진 미확인**: ETN 응답, 구성 비중 기준일, 약관 원문, `source_url` 주소(Task 2 Step 6에서 확인).
