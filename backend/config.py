"""
config.py
환경변수 기반 설정. 값은 .env 또는 호스팅 환경변수로 주입한다.
"""
import os


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# 저장소
DATA_DIR = os.getenv("DATA_DIR", os.path.join(BASE_DIR, "data"))

# 세션 / 인증
SESSION_SECRET = os.getenv("SESSION_SECRET", "")
SESSION_COOKIE_NAME = "alpha_session"
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", str(7 * 24 * 3600)))
COOKIE_SECURE = _bool("COOKIE_SECURE", True)          # 로컬 http 개발 시 false
ALLOW_DEV_LOGIN = _bool("ALLOW_DEV_LOGIN", False)      # 운영에서는 반드시 false
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")   # Google 로그인은 PR-A 마지막 단계

# CORS: 쉼표 구분. 비어 있으면 동일 출처만(미들웨어 미적용)
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]

# 계좌 / 주문
DEFAULT_INITIAL_BALANCE = int(os.getenv("DEFAULT_INITIAL_BALANCE", "100000"))
MIN_BUDGET = 10_000
MAX_BUDGET = 100_000_000
MAX_ORDER_QUANTITY = 100_000
MIN_FRACTION_STEP = 0.0001

# 수수료 / 세금 (세율은 연도별 세법에 따라 변경 → 환경변수로 조정)
BUY_FEE_RATE = float(os.getenv("BUY_FEE_RATE", "0.00015"))
SELL_FEE_RATE = float(os.getenv("SELL_FEE_RATE", "0.00015"))
# TODO: 2026년 증권거래세율 확인 후 기본값 갱신 (현재 기존 코드 값 유지)
SELL_TAX_RATE = float(os.getenv("SELL_TAX_RATE", "0.0018"))

# 추천 강제 갱신 최소 간격(초)
REFRESH_MIN_INTERVAL = int(os.getenv("REFRESH_MIN_INTERVAL", "60"))


def validate_runtime() -> None:
    """서버 시작 시 필수 설정 확인."""
    if len(SESSION_SECRET) < 32:
        raise RuntimeError("SESSION_SECRET 환경변수(32자 이상)가 필요합니다.")
