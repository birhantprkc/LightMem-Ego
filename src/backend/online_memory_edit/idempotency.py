from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from online_preprocess.io_utils import read_json, utc_now_iso, write_json_atomic


_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,199}$")


class IdempotencyError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass(frozen=True)
class StoredResponse:
    status_code: int
    payload: dict[str, Any]


class IdempotencyStore:
    def __init__(self, session_dir: Path, ttl_hours: int = 24) -> None:
        self.root = Path(session_dir) / "memory" / "idempotency"
        self.ttl_hours = max(1, ttl_hours)

    @staticmethod
    def request_digest(operation: str, body: Any) -> str:
        encoded = json.dumps(
            {"operation": operation, "body": body},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def begin(self, key: str, operation: str, body: Any) -> StoredResponse | None:
        self._validate_key(key)
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(key)
        digest = self.request_digest(operation, body)
        existing = read_json(path, default=None)
        if isinstance(existing, dict):
            if self._expired(existing):
                try:
                    path.unlink()
                except OSError:
                    pass
                existing = None
        if isinstance(existing, dict):
            if existing.get("operation") != operation or existing.get("requestDigest") != digest:
                raise IdempotencyError(409, "idempotency_key_conflict", "幂等键已用于不同的请求")
            if existing.get("state") in {"success", "failed"}:
                payload = existing.get("response")
                if isinstance(payload, dict):
                    return StoredResponse(int(existing.get("statusCode") or 500), payload)
            if existing.get("state") == "retryable_failed":
                existing.update({"state": "pending", "lastAttemptAt": utc_now_iso()})
                write_json_atomic(path, existing)
                return None
            raise IdempotencyError(503, "memory_update_in_progress", "记忆更新仍在处理中，请使用相同幂等键重试")

        created = datetime.now(timezone.utc)
        write_json_atomic(
            path,
            {
                "key": key,
                "operation": operation,
                "requestDigest": digest,
                "state": "pending",
                "createdAt": created.isoformat(),
                "expiresAt": (created + timedelta(hours=self.ttl_hours)).isoformat(),
            },
        )
        self._cleanup_expired(exclude=path)
        return None

    def finish(
        self,
        key: str,
        status_code: int,
        payload: dict[str, Any],
        *,
        retryable: bool = False,
    ) -> None:
        path = self._path(key)
        existing = read_json(path, default={})
        if not isinstance(existing, dict):
            existing = {"key": key}
        existing.update(
            {
                "state": (
                    "success"
                    if 200 <= status_code < 300
                    else "retryable_failed"
                    if retryable
                    else "failed"
                ),
                "statusCode": int(status_code),
                "response": payload,
                "completedAt": utc_now_iso(),
            }
        )
        write_json_atomic(path, existing)

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.json"

    @staticmethod
    def _validate_key(key: str) -> None:
        if not isinstance(key, str) or not _KEY_RE.fullmatch(key):
            raise IdempotencyError(400, "invalid_idempotency_key", "Idempotency-Key 格式无效")

    def _cleanup_expired(self, exclude: Path) -> None:
        now = datetime.now(timezone.utc)
        for path in self.root.glob("*.json"):
            if path == exclude:
                continue
            value = read_json(path, default={})
            if not isinstance(value, dict):
                continue
            raw = value.get("expiresAt")
            try:
                expires = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            except ValueError:
                continue
            if expires <= now:
                try:
                    path.unlink()
                except OSError:
                    pass

    @staticmethod
    def _expired(value: dict[str, Any]) -> bool:
        raw = value.get("expiresAt")
        try:
            expires = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return False
        return expires <= datetime.now(timezone.utc)
