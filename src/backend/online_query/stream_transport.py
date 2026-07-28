from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any


STREAM_EVENTS_DIR_NAME = "query_stream_events"


def query_stream_events_path(project_root: Path, task_id: str) -> Path:
    return Path(project_root) / "online_tasks" / STREAM_EVENTS_DIR_NAME / f"{task_id}.jsonl"


def append_query_stream_event(path: Path, event: dict[str, Any]) -> None:
    """Append one complete JSON event for the API SSE relay."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(event, ensure_ascii=False, default=str).encode("utf-8") + b"\n"
    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o664)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("failed to append query stream event")
            view = view[written:]
    finally:
        os.close(fd)


def read_query_stream_events(
    path: Path,
    *,
    offset: int = 0,
    pending: bytes = b"",
) -> tuple[list[dict[str, Any]], int, bytes]:
    """Read newly appended complete events while retaining a partial last line."""

    path = Path(path)
    if not path.exists():
        return [], offset, pending
    try:
        with path.open("rb") as handle:
            handle.seek(max(0, int(offset)))
            chunk = handle.read()
            new_offset = handle.tell()
    except FileNotFoundError:
        return [], offset, pending
    if not chunk:
        return [], new_offset, pending

    data = pending + chunk
    lines = data.split(b"\n")
    remainder = lines.pop()
    events: list[dict[str, Any]] = []
    for raw in lines:
        if not raw.strip():
            continue
        try:
            item = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(item, dict):
            events.append(item)
    return events, new_offset, remainder


class QueryStreamEventWriter:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def __call__(self, event: dict[str, Any]) -> None:
        if not isinstance(event, dict):
            return
        with self._lock:
            append_query_stream_event(self.path, event)
