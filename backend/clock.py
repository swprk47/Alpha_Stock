"""화면·기록에 보이는 시각은 서버 PC 의 시간대와 상관없이 한국 표준시(KST)로 통일한다.

한국은 서머타임이 없어 UTC+9 고정 오프셋으로 충분하다(zoneinfo 는 Windows 에서 tzdata 패키지가 따로 필요).
"""
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
KST = timezone(timedelta(hours=9))
_FORMAT = "%Y-%m-%d %H:%M:%S"


def now_kst() -> datetime:
    return datetime.now(KST)


def today_kst():
    return now_kst().date()


def fmt_kst(timestamp: float) -> str:
    """epoch 초 → 'YYYY-MM-DD HH:MM:SS'(KST)."""
    return datetime.fromtimestamp(timestamp, KST).strftime(_FORMAT)


def now_str() -> str:
    return now_kst().strftime(_FORMAT)
