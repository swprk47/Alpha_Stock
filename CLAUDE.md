# Alpha Stock — Claude Code 작업 지침

국내 주식 모의투자·스윙 추천 PWA. 사용자가 추천을 보고 **실제 개인계좌 투자에 참고**하므로 시세·계산 정확성이 최우선이다.

## 스택
- 백엔드: FastAPI / Python (`backend/`), 테스트 `tests/` (pytest)
- 프론트: 단일 HTML `frontend/index.html`(~84KB) + `manifest.json` + `sw.js`. 프론트 분리·프레임워크 도입 금지
- 저장: 사용자별 JSON(`data/users/*.json`). SQLite 도입 금지
- 리포: github.com/swprk47/Alpha_Stock (기준 main 67f1950)

## 작업 원칙 (반드시 지킬 것)
1. **main 직접 수정 금지.** 브랜치 → PR. 현재 브랜치 `feat/auth-and-order-validation` (Draft PR #1, base main)
2. **사용자가 "진행해"라고 한 단계만 코드를 작성한다.** 계획·논의 요청에는 코드를 쓰지 않는다
3. 한 단계 = 한 커밋(백엔드+프론트+테스트 포함). 끝나면 `pytest -q`와 프론트 문법검사 통과를 확인하고 결과를 보고
4. 사용자가 push 완료만 알리면 바로 다음 단계를 시작하지 말고 **시작 여부를 먼저 확인**
5. 전략(strategy.py) 변경은 이번 범위에서 제외
6. 답변은 한국어. 모르는 것·확인 못 한 것은 추측하지 말고 "확인 못 함"이라고 말한다

## 프론트 문법검사
```bash
python3 - <<'EOF'
import re
s=open('frontend/index.html',encoding='utf-8').read()
open('/tmp/x.js','w').write(re.search(r'<script>\n(.*)</script>\n</body>',s,re.S).group(1))
EOF
node --check /tmp/x.js
```
(템플릿 리터럴에 `${x:g}` 같은 Python 포맷을 쓰지 말 것 — main에 있던 버그를 이미 고쳤다)

## 로컬 실행
```bash
pip install -r requirements-dev.txt
cp .env.example .env     # SESSION_SECRET: python -c "import secrets;print(secrets.token_urlsafe(48))"
# 개발 시 ALLOW_DEV_LOGIN=true, COOKIE_SECURE=false
set -a && source .env && set +a
cd backend && uvicorn server:app --port 8000
pytest -q                # 저장소 루트
```
로컬 uvicorn은 HTTP/1.1이 정상. HTTP/3는 앱이 아니라 배포 앞단(Caddy 등) 문제 → PR-C 문서.

## 핵심 설계 (이미 구현됨, 깨지 말 것)
- 인증: HttpOnly JWT 쿠키 `alpha_session`. 계좌 API는 쿠키로 사용자를 식별, 미로그인 401. 요청에 `user_id` 없음
- 요청 스키마 `extra=forbid`: `user_id`/`price`/`name`/`logo_url` 보내면 422
- **체결가는 서버 실시간 시세만.** 시세 실패/0원이면 503. 클라 price 필드 없음
- 종목코드 규칙은 `schemas.CODE_PATTERN = ^[0-9A-Z]{6}$` 한 곳(예: `0183J0`). 소문자 거부
- 소수점 판별: `backend/fractional.py` + `backend/data/fractional/miraeasset.json`(328종목, 기준일 2026-10-01). 목록에 있으면 소수점 가능, **없거나 목록 파일이 없으면 정수만**. ETF 불가. 네이버 호출 없음
- 개발용 닉네임 로그인 `/api/auth/dev-login`은 `ALLOW_DEV_LOGIN=true`일 때만(아니면 404)
- 프론트: `api()` 공통 헬퍼(credentials same-origin, 401→로그인 모달, 422/503/429 메시지). 서버 세션(`/api/me`)만 신뢰. localStorage 사용자 저장·JWT 디코딩·게스트 계정 없음
- `GET /api/recommendations?refresh=true`: 로그인 필요 + 60초 제한(429)
- `sw.js`는 fetch 핸들러가 없어 `/api/*`를 캐시하지 않는다
- 소수점 목록 갱신: `python scripts/import_fractional.py <xlsx> --broker miraeasset --date YYYY-MM-DD` (헤더 없는 엑셀, A열 `A005930`, B열 종목명)

## 샌드박스/푸시 주의
Claude Code가 로컬 git 인증을 가지고 있으면 직접 push 가능. 단 main 직접 push 금지.

자세한 진행 상태·결정사항은 `PROGRESS.md` 참고.
