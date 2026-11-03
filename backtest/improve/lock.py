"""단계 잠금(설계서 7절): 검증 기간을 한 번만 쓰도록 선별 결과를 잠그고, test 단계가 train 때와 같은 코드·데이터·설정인지 확인한다.

실수로 검증 기간을 재사용하는 것을 막고 기록으로 남기는 용도이며, 파일을 일부러 지우는 것까지 막지는 못한다.
"""
import hashlib
import json
import subprocess
from pathlib import Path

from .candidates import Candidate, Combo, by_name

OUT_DIR = Path("backtest/results/improve")
SELECTION = "selection.json"
TEST_RESULT = "test_result.json"
CODE_GLOBS = ("backtest/improve/*.py", "backtest/*.py", "backtest/analysis/*.py")
CODE_FILES = ("backend/strategy.py", "backend/fees.py", "backend/orders.py")
_DATA_KEYS = ("listing_hash", "candle_hash", "n_frames", "first_date", "last_date", "test_end")


class StageError(RuntimeError):
    pass


def file_hash(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree_hash(paths) -> str:
    digest = hashlib.sha256()
    for path in sorted(str(p) for p in paths):
        digest.update(path.encode("utf-8"))
        digest.update(file_hash(path).encode("utf-8"))
    return digest.hexdigest()


def code_hashes(repo_root=".") -> dict:
    """파이프라인 코드 파일별 내용 해시(상대 경로 -> sha256). train 뒤에 순위 계산 코드를 고치면 test 가 거부된다."""
    root = Path(repo_root)
    paths = {p for pattern in CODE_GLOBS for p in root.glob(pattern)}
    paths |= {root / name for name in CODE_FILES if (root / name).exists()}
    return {p.relative_to(root).as_posix(): file_hash(p) for p in sorted(paths)}


def data_snapshot(cache_dir, codes, *, n_frames: int, first_date: str, last_date: str, test_end: "str | None" = None) -> dict:
    """사용하는 일봉 CSV 전체의 내용 해시(코드 순서와 무관)와 listing.json 해시, 프레임 수, 기간, 검증 끝."""
    cache = Path(cache_dir)
    digest = hashlib.sha256()
    for code in sorted(codes):
        path = cache / f"{code}.csv"
        if path.exists():
            digest.update(code.encode("utf-8"))
            digest.update(file_hash(path).encode("utf-8"))
    listing = cache / "listing.json"
    return {"listing_hash": file_hash(listing) if listing.exists() else None, "candle_hash": digest.hexdigest(),
            "n_frames": n_frames, "first_date": first_date, "last_date": last_date, "test_end": test_end}


def git_state() -> dict:
    """저장소 커밋 해시와 working tree 변경 여부. git 이 없거나 저장소가 아니면 None."""
    def run(*args):
        try:
            result = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
        except Exception:
            return None
        return result.stdout.strip() if result.returncode == 0 else None
    commit = run("rev-parse", "HEAD")
    status = run("status", "--porcelain")
    return {"commit": commit, "dirty": None if status is None else bool(status)}


def finalists_to_json(finalists: list) -> list:
    out = []
    for f in finalists:
        if isinstance(f, Combo):
            out.append({"kind": "combo", "signal": f.signal.name if f.signal else None,
                        "filter": f.filter.name if f.filter else None, "exit": f.exit.name if f.exit else None})
        else:
            out.append({"kind": "candidate", "name": f.name})
    return out


def finalists_from_json(items: list) -> list:
    out = []
    for item in items:
        if item["kind"] == "combo":
            pick = lambda key: by_name(item[key]) if item[key] else None
            out.append(Combo(signal=pick("signal"), filter=pick("filter"), exit=pick("exit")))
        else:
            out.append(by_name(item["name"]))
    return out


def build_selection_payload(selection, mde: dict, config: dict, snapshot: dict, code: dict, registry_fp: str,
                            train_table, test_end: str) -> dict:
    return {"version": 1, "chosen": selection.chosen, "folded": selection.folded, "n": selection.n,
            "finalists": finalists_to_json(selection.finalists), "mde": mde, "config": config, "data": snapshot,
            "code": code, "registry": registry_fp, "train": train_table, "test_end": test_end, "git": git_state()}


def write_selection(out_dir, payload: dict) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / SELECTION
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def read_selection(out_dir) -> dict:
    return json.loads((Path(out_dir) / SELECTION).read_text(encoding="utf-8"))


def selection_hash(out_dir) -> str:
    return file_hash(Path(out_dir) / SELECTION)


def test_result_exists(out_dir) -> bool:
    return (Path(out_dir) / TEST_RESULT).exists()


def check_train_allowed(out_dir) -> None:
    """검증 결과가 이미 있으면 train 도 거부한다(검증을 본 뒤 선별을 덮어쓰는 것을 막는다)."""
    if test_result_exists(out_dir):
        raise StageError("test_result.json 이 이미 있어 train 단계를 다시 실행할 수 없다(검증을 본 뒤 선별을 덮어쓰는 것을 막는다)")


def _differences(saved: dict, current: dict) -> list:
    found = []
    for key in ("config", "registry"):
        if saved.get(key) != current.get(key):
            found.append(key)
    for key in _DATA_KEYS:
        if saved.get("data", {}).get(key) != current.get("data", {}).get(key):
            found.append(f"data:{key}")
    saved_code, current_code = saved.get("code", {}), current.get("code", {})
    for name in sorted(set(saved_code) | set(current_code)):
        if saved_code.get(name) != current_code.get(name):
            found.append(f"code:{name}")
    return found


def check_test_allowed(out_dir, current: dict, *, allow_rerun: bool) -> list:
    """test 단계 실행 전 확인. selection.json 이 없으면, 이미 test 결과가 있는데 allow_rerun 이 아니면, 코드·데이터·설정·레지스트리가
    selection.json 과 다르면(allow_rerun 이 아닐 때) StageError. 어긋난 항목 목록을 돌려준다(allow_rerun 일 때 결과에 기록한다)."""
    out = Path(out_dir)
    if not (out / SELECTION).exists():
        raise StageError("selection.json 이 없다: 먼저 --stage train 을 실행해야 한다")
    if test_result_exists(out) and not allow_rerun:
        raise StageError("test_result.json 이 이미 있다: 검증 기간은 한 번만 쓴다(--allow-rerun 으로 재실행하면 결과에 재사용으로 기록된다)")
    mismatches = _differences(read_selection(out), current)
    if mismatches and not allow_rerun:
        raise StageError("selection.json 과 현재 코드·데이터·설정이 다르다: " + ", ".join(mismatches))
    return mismatches


def write_test_result(out_dir, payload: dict, *, selection_hash: str, rerun: bool, mismatches: list) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / TEST_RESULT
    body = dict(payload, selection_hash=selection_hash, rerun=rerun, mismatches=mismatches)
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path
