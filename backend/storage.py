"""
storage.py
사용자 JSON 파일 저장소: 사용자별 락 + 임시파일→os.replace 원자적 쓰기
"""
import hashlib
import json
import os
import tempfile
import threading
from contextlib import contextmanager

import config


class UserStore:
    def __init__(self, data_dir: str | None = None):
        self.users_dir = os.path.join(data_dir or config.DATA_DIR, "users")
        os.makedirs(self.users_dir, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _path(self, user_id: str) -> str:
        # 사용자 ID를 해시해 파일명 충돌·경로 조작을 차단
        digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:32]
        return os.path.join(self.users_dir, f"{digest}.json")

    def _lock(self, user_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(user_id, threading.Lock())

    @contextmanager
    def locked(self, user_id: str):
        """읽기-수정-쓰기 구간 전체를 한 사용자 단위로 직렬화."""
        with self._lock(user_id):
            yield

    def load(self, user_id: str) -> dict | None:
        path = self._path(user_id)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save(self, user_id: str, data: dict) -> None:
        path = self._path(user_id)
        fd, tmp = tempfile.mkstemp(dir=self.users_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
