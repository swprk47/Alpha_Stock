"""
auth.py
세션 인증: 서버가 서명한 HttpOnly JWT 쿠키로 사용자 식별.
- 개발용 닉네임 로그인은 ALLOW_DEV_LOGIN=true 일 때만 동작 (운영 비활성)
- Google ID 토큰 검증 로그인은 PR-A 마지막 단계에서 추가
"""
import hashlib
import time

import jwt
from fastapi import HTTPException, Request, Response

import config

ALGO = "HS256"


def create_session_token(sub: str, name: str) -> str:
    now = int(time.time())
    payload = {"sub": sub, "name": name, "iat": now, "exp": now + config.SESSION_TTL_SECONDS}
    return jwt.encode(payload, config.SESSION_SECRET, algorithm=ALGO)


def decode_session_token(token: str) -> dict:
    return jwt.decode(token, config.SESSION_SECRET, algorithms=[ALGO], options={"require": ["sub", "exp"]})


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        config.SESSION_COOKIE_NAME, token,
        max_age=config.SESSION_TTL_SECONDS, httponly=True,
        secure=config.COOKIE_SECURE, samesite="lax", path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(config.SESSION_COOKIE_NAME, path="/")


def dev_user_id(nickname: str) -> str:
    """개발 로그인 사용자 ID. 'dev:' 접두사로 Google 사용자와 네임스페이스 분리."""
    return "dev:" + hashlib.sha256(nickname.strip().lower().encode()).hexdigest()[:16]


def get_current_user(request: Request) -> dict:
    """FastAPI Depends: 유효한 세션이 없으면 401."""
    token = request.cookies.get(config.SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    try:
        claims = decode_session_token(token)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="세션이 만료되었거나 올바르지 않습니다.")
    if claims["sub"].startswith("dev:") and not config.ALLOW_DEV_LOGIN:
        raise HTTPException(status_code=401, detail="개발용 로그인이 비활성화되었습니다.")
    return {"user_id": claims["sub"], "name": claims.get("name", "투자자")}
