"""
fractional.py
증권사별 소수점 거래 가능 종목 판별. 목록은 backend/data/fractional/<broker>.json
(scripts/import_fractional.py 로 생성, 버전관리 대상 정적 데이터).
목록에 있으면 가능, 없거나 목록 파일이 없으면 불가(정수만).
"""
import json
import os
import re

DEFAULT_BROKER = "miraeasset"
BROKER_LABELS = {"miraeasset": "미래에셋"}
_DIR = os.path.join(os.path.dirname(__file__), "data", "fractional")
_cache: dict = {}


def _load(broker: str) -> dict:
    if broker not in _cache:
        if not re.fullmatch(r"[a-z0-9_]+", broker or ""):
            _cache[broker] = {}
        else:
            try:
                with open(os.path.join(_DIR, f"{broker}.json"), encoding="utf-8") as f:
                    _cache[broker] = json.load(f)
            except (OSError, ValueError):
                _cache[broker] = {}
    return _cache[broker]


def _norm(code: str) -> str:
    c = (code or "").strip().upper()
    return c[1:] if len(c) == 7 and c.startswith("A") else c


def list_updated_at(broker: str = DEFAULT_BROKER) -> str:
    return _load(broker).get("updated_at", "")


def is_fractional_tradable(code: str, broker: str = DEFAULT_BROKER) -> tuple[bool, str]:
    stocks = _load(broker).get("stocks")
    if not stocks:
        return False, "소수점 거래 가능 종목 목록 없음"
    if _norm(code) in stocks:
        return True, "소수점 거래 가능 종목"
    return False, "소수점 거래 불가 종목 (1주 단위)"


def _reset_cache():  # 테스트용
    _cache.clear()
