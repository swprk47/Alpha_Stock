"""후보 등록표: 설계서에서 확정한 후보 사양과 검증 상수를 한 곳에 고정한다.

fingerprint()는 이 값 전체의 해시라서, 값이 바뀌면 사전 등록과 달라졌음을 알 수 있다.
"""
import hashlib
import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class LotterySpec:
    name: str = "lottery_avoid"
    exclude_pct: float = 0.20
    reentry_choices: tuple = (0.20, 0.30)
    min_days: int = 15


@dataclass(frozen=True)
class GateSpec:
    name: str = "ma_gate"
    months: int = 10


LOTTERY = LotterySpec()
GATE = GateSpec()
BENCHMARK = "069500"

BAD_RETURN = 0.31
SLIPPAGE = 0.001
COST_MULTIPLIERS = (1.0, 1.5, 2.0)
DRAWS = 20_000
SEED = 20261110
BLOCK_MONTHS = 3
BLOCK_DAYS = 63
N_CANDIDATES = 2
ALPHA = 0.05
MIN_EFFECT_ANNUAL = 0.01
BIG_DROP = 0.15
TRAIN_END = "2021-12-31"
REHEARSAL_START = "2022-01-01"


def fingerprint() -> str:
    """호출 시점의 모듈 전역값 전체를 정렬된 JSON으로 만들어 sha256 16진 문자열을 돌려준다."""
    values = {
        "LOTTERY": asdict(LOTTERY),
        "GATE": asdict(GATE),
        "BENCHMARK": BENCHMARK,
        "BAD_RETURN": BAD_RETURN,
        "SLIPPAGE": SLIPPAGE,
        "COST_MULTIPLIERS": COST_MULTIPLIERS,
        "DRAWS": DRAWS,
        "SEED": SEED,
        "BLOCK_MONTHS": BLOCK_MONTHS,
        "BLOCK_DAYS": BLOCK_DAYS,
        "N_CANDIDATES": N_CANDIDATES,
        "ALPHA": ALPHA,
        "MIN_EFFECT_ANNUAL": MIN_EFFECT_ANNUAL,
        "BIG_DROP": BIG_DROP,
        "TRAIN_END": TRAIN_END,
        "REHEARSAL_START": REHEARSAL_START,
    }
    text = json.dumps(values, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
