# Alpha Stock

국내 주식 모의투자 · 스윙 추천 PWA. 백엔드 FastAPI(Python), 프론트엔드 단일 HTML(`frontend/index.html`).

> 추천을 실제 투자에 참고하는 용도이므로 **체결가는 항상 서버 실시간 시세**만 사용합니다.

## 로컬 실행

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt        # 운영은 requirements.txt

cp .env.example .env
# SESSION_SECRET 생성 (32자 이상 필수) 후 .env 에 붙여넣기
python -c "import secrets;print(secrets.token_urlsafe(48))"

set -a && source .env && set +a            # 환경변수 로드
cd backend && uvicorn server:app --reload --port 8000
# 브라우저: http://localhost:8000
```

### 환경변수

| 이름 | 설명 | 기본 |
|---|---|---|
| `SESSION_SECRET` | 세션 JWT 서명 키. **필수, 32자 이상** | - |
| `COOKIE_SECURE` | 로컬 http 개발은 `false`, 운영(HTTPS)은 `true` | `true` |
| `ALLOW_DEV_LOGIN` | 개발용 닉네임 로그인 허용. **운영은 반드시 `false`** | `false` |
| `GOOGLE_CLIENT_ID` | Google 로그인용 (연동 예정) | 빈 값 |
| `ALLOWED_ORIGINS` | 프론트를 다른 출처에서 띄울 때만 (쉼표 구분) | 빈 값 |
| `DATA_DIR` | 사용자 계좌 JSON 저장 위치 | `./data` |
| `BUY_FEE_RATE` / `SELL_FEE_RATE` / `SELL_TAX_RATE` | 수수료·세율 | 0.015% / 0.015% / 0.18% |

> 증권거래세율은 연도별로 바뀝니다. 2026년 적용 세율은 아직 검증하지 않았습니다(`config.py` TODO).

## 테스트

```bash
pytest -q          # 저장소 루트에서
```

## 보안 변경점 (PR-A)

- 인증: HttpOnly JWT 쿠키(`alpha_session`). 계좌 API는 모두 쿠키로 사용자를 식별하며, 미로그인 시 401. 요청에 `user_id`를 받지 않으므로 다른 사용자 계좌에 접근할 수 없습니다.
- 주문 검증: 체결가는 서버가 조회한 실시간 시세. 시세 조회 실패/0원이면 503. 소수점 불가 종목, 과다 매도, 목표가>체결가>손절가 위반은 400.
- 요청 스키마 `extra=forbid`: `user_id`, `price`, `name`, `logo_url` 등을 보내면 422.
- 저장소: 사용자별 Lock, 임시 파일 작성 후 `os.replace`(원자적 저장), 파일명은 sha256.
- `GET /api/recommendations?refresh=true`는 로그인 필요 + 60초 간격 제한(429).
- 개발용 닉네임 로그인(`/api/auth/dev-login`)은 `ALLOW_DEV_LOGIN=true`일 때만 동작(꺼져 있으면 404).
- 프론트: 브라우저의 JWT 직접 디코딩·`localStorage` 사용자 저장·게스트 자동 계좌 제거. 세션은 서버(`/api/me`)만 신뢰.

## API 변경 요약

| 엔드포인트 | 변경 |
|---|---|
| `POST /api/auth/dev-login {nickname}` | 신규(개발 전용) |
| `POST /api/auth/logout` · `GET /api/me` · `GET /api/health` | 신규 |
| `POST /api/auth/google` | 501 스텁 (Google 연동은 PR-A 마지막 단계) |
| `POST /api/buy {code, quantity, target_price?, stop_loss_price?, max_hold_days?}` | `user_id`·`price`·`name`·`logo_url` 제거. 목표/손절 미지정 시 +6.5% / -3% |
| `POST /api/sell {code, quantity?}` | `quantity` 생략 시 전량. `price` 제거 |
| `POST /api/portfolio/budget {budget}` | query → JSON body |
| `POST /api/reset` · `GET /api/portfolio` | `user_id` 제거 |

기존 `data/users/*.json`(테스트 데이터)은 호환되지 않으며 삭제해도 됩니다.

## 로드맵

- PR-A 마무리: Google ID 토큰 서버 검증, `/api/config`
- PR-B `feat/cash-ledger`: 입출금 원장
- PR-C `chore/deploy`: Dockerfile·배포 문서(HTTPS, 영구 디스크)
