"""후보 8개 사전 등록(설계서 4절). 시험 중 변경·추가 금지이며, 설계서와 어긋나면 테스트가 실패한다."""
import hashlib
import json
from dataclasses import dataclass

DIRECTIONS = ("filter", "exit", "signal")


@dataclass(frozen=True)
class Candidate:
    name: str
    direction: str           # "filter" | "exit" | "signal" | "baseline"
    pre_exposed: bool        # 검증 기간이 포함된 전체 기간 결과를 본 뒤 고른 후보인가


REGISTRY = (
    Candidate("F1", "filter", True),
    Candidate("E1", "exit", True),
    Candidate("E2", "exit", True),
    Candidate("E3", "exit", True),
    Candidate("S1", "signal", False),
    Candidate("S2", "signal", False),
    Candidate("S3", "signal", False),
    Candidate("S4", "signal", True),
)
BASELINE = Candidate("BASE", "baseline", False)

# simulate_trade 인자. 적지 않은 값은 기본값(익절 +6.5%, 손절 -3%, 5거래일)이다.
_EXIT_TABLE = {
    "E1": {"stop_ratio": 0.95},
    "E2": {"stop_ratio": 0.95, "target_ratio": 1.10, "hold_days": 10},
    "E3": {"stop_ratio": 0.93, "target_ratio": 1.15, "hold_days": 20},
}


def by_name(name: str) -> Candidate:
    for candidate in REGISTRY:
        if candidate.name == name:
            return candidate
    raise KeyError(name)


def exit_kwargs(candidate: Candidate) -> dict:
    return dict(_EXIT_TABLE.get(candidate.name, {}))


@dataclass(frozen=True)
class Combo:
    """뽑힌 방향을 합친 조합: 신호 -> 필터 -> 청산. 없는 방향은 None."""
    signal: "Candidate | None"
    filter: "Candidate | None"
    exit: "Candidate | None"

    @property
    def name(self) -> str:
        return "COMBO(" + "+".join(c.name for c in (self.signal, self.filter, self.exit) if c is not None) + ")"

    @property
    def pre_exposed(self) -> bool:
        return any(c.pre_exposed for c in (self.signal, self.filter, self.exit) if c is not None)

    def exit_kwargs(self) -> dict:
        return exit_kwargs(self.exit) if self.exit is not None else {}


def registry_fingerprint() -> str:
    """레지스트리(이름·방향·사전 노출·청산 인자)의 sha256. test 단계가 train 때와 같은지 확인하는 데 쓴다."""
    payload = {"registry": [[c.name, c.direction, c.pre_exposed] for c in REGISTRY], "exit": _EXIT_TABLE}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
