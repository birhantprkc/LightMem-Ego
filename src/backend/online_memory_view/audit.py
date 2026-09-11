from __future__ import annotations

import fcntl
import json
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


_STATE_LOCK = threading.Lock()
_LAST_CLEANUP_DAY: date | None = None


def append_memory_view_audit(log_root: Path, payload: dict[str, Any], retention_days: int = 30) -> None:
    try:
        now = datetime.now(timezone.utc)
        directory = Path(log_root) / "memory_query"
        directory.mkdir(parents=True, exist_ok=True, mode=0o750)
        path = directory / f"{now.date().isoformat()}.jsonl"
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with path.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                handle.write(line + "\n")
                handle.flush()
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        try:
            path.chmod(0o640)
        except OSError:
            pass
        _cleanup_once_per_day(directory, now.date(), retention_days)
    except Exception as exc:
        print(f"[memory_view_audit] append failed: {type(exc).__name__}", flush=True)


def _cleanup_once_per_day(directory: Path, today: date, retention_days: int) -> None:
    global _LAST_CLEANUP_DAY
    with _STATE_LOCK:
        if _LAST_CLEANUP_DAY == today:
            return
        _LAST_CLEANUP_DAY = today
    cutoff = today - timedelta(days=max(1, retention_days) - 1)
    for path in directory.glob("????-??-??.jsonl"):
        try:
            file_day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if file_day < cutoff:
            try:
                path.unlink()
            except OSError:
                pass
