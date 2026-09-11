from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .graph_normalizer import MemoryGraphNormalizer
from .graph_repository import (
    LongTermMemoryGraphRepository,
    MemoryGraphRepositoryError,
)
from .schemas import (
    MEMORY_GRAPH_DEFAULT_MAX_RESPONSE_BYTES,
    MEMORY_GRAPH_MIN_RESPONSE_BYTES,
    MEMORY_GRAPH_SCHEMA_VERSION,
    MEMORY_GRAPH_SCALES,
    MEMORY_SOURCE,
)


class MemoryGraphError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class MemoryGraphResult:
    payload: dict[str, Any] | None
    response_bytes: int
    etag: str
    not_modified: bool
    signature: dict[str, Any]


class LongTermMemoryGraphService:
    def __init__(self, sessions_root: Path, session_id: str) -> None:
        self.sessions_root = Path(sessions_root)
        self.session_id = session_id

    def load(self, scale: str = "30sec", if_none_match: str | None = None) -> MemoryGraphResult:
        normalized_scale = _normalize_scale(scale)
        last_signature: dict[str, Any] | None = None
        for attempt in range(2):
            repository = LongTermMemoryGraphRepository(self.sessions_root, self.session_id)
            try:
                probe = repository.probe()
            except FileNotFoundError as exc:
                raise MemoryGraphError(404, "session_not_found", "Session 不存在") from exc
            except MemoryGraphRepositoryError as exc:
                raise _repository_error(exc) from exc

            etag = memory_graph_etag(self.session_id, normalized_scale, probe.signature)
            if etag_matches(if_none_match, etag):
                return MemoryGraphResult(
                    payload=None,
                    response_bytes=0,
                    etag=etag,
                    not_modified=True,
                    signature=probe.signature,
                )

            try:
                sources = repository.load_sources(probe.config)
                after = repository.reload_probe(probe)
            except MemoryGraphRepositoryError as exc:
                if exc.reason in {"not_ready", "lagging"} and attempt == 0:
                    last_signature = probe.signature
                    continue
                raise _repository_error(exc) from exc
            if probe.signature != after.signature:
                last_signature = after.signature
                continue

            normalized = MemoryGraphNormalizer(
                session_id=self.session_id,
                session_dir=self.sessions_root / self.session_id,
            ).normalize(sources)
            signature = after.signature
            payload = {
                "schema_version": MEMORY_GRAPH_SCHEMA_VERSION,
                "status": "ok",
                "session_id": self.session_id,
                "memory_source": MEMORY_SOURCE,
                "scale": normalized_scale,
                "memory_version": signature["memory_version"],
                "component_versions": {
                    "episodic": signature["memory_version"],
                    "graph": signature["graph_version"],
                    "semantic": signature["semantic_version"],
                },
                "graph_versions": {
                    "episodic_graph": signature["graph_version"],
                    "semantic_graph": signature["semantic_version"],
                },
                "updated_at": signature.get("updated_at"),
                "availability": {
                    "episodic_graph": "ready",
                    "semantic_graph": "ready",
                },
                **normalized,
            }
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            max_bytes = memory_graph_max_response_bytes()
            if len(encoded) > max_bytes:
                raise MemoryGraphError(
                    413,
                    "memory_graph_response_too_large",
                    "该 Session 的记忆图数据超过安全展示上限",
                    {"max_response_bytes": max_bytes},
                )
            return MemoryGraphResult(
                payload=payload,
                response_bytes=len(encoded),
                etag=etag,
                not_modified=False,
                signature=signature,
            )
        raise MemoryGraphError(
            503,
            "memory_snapshot_changing",
            "记忆图正在更新，请稍后刷新",
            _safe_version_details(last_signature),
        )


def memory_graph_etag(session_id: str, scale: str, signature: dict[str, Any]) -> str:
    raw = json.dumps(
        {
            "schema_version": MEMORY_GRAPH_SCHEMA_VERSION,
            "session_id": session_id,
            "scale": scale,
            "memory_version": signature.get("memory_version"),
            "graph_version": signature.get("graph_version"),
            "semantic_version": signature.get("semantic_version"),
            "updated_at": signature.get("updated_at"),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return '"mg-' + hashlib.sha256(raw.encode("utf-8")).hexdigest() + '"'


def etag_matches(if_none_match: str | None, current_etag: str) -> bool:
    if not if_none_match:
        return False
    current = _opaque_etag(current_etag)
    for value in if_none_match.split(","):
        candidate = value.strip()
        if candidate == "*":
            return True
        if _opaque_etag(candidate) == current and current is not None:
            return True
    return False


def memory_graph_max_response_bytes() -> int:
    raw = os.getenv("EM2MEM_MEMORY_GRAPH_MAX_RESPONSE_BYTES", str(MEMORY_GRAPH_DEFAULT_MAX_RESPONSE_BYTES))
    try:
        value = int(raw)
    except ValueError:
        value = MEMORY_GRAPH_DEFAULT_MAX_RESPONSE_BYTES
    return max(MEMORY_GRAPH_MIN_RESPONSE_BYTES, value)


def _normalize_scale(scale: str) -> str:
    value = str(scale or "").strip().lower()
    if value not in MEMORY_GRAPH_SCALES:
        raise MemoryGraphError(400, "unsupported_graph_scale", "记忆图尺度仅支持 30sec")
    return "30sec"


def _opaque_etag(value: str) -> str | None:
    candidate = str(value or "").strip()
    if candidate[:2].casefold() == "w/":
        candidate = candidate[2:].strip()
    if len(candidate) < 2 or not candidate.startswith('"') or not candidate.endswith('"'):
        return None
    return candidate[1:-1]


def _repository_error(exc: MemoryGraphRepositoryError) -> MemoryGraphError:
    if exc.reason == "unsupported":
        return MemoryGraphError(409, "graph_not_supported", "该旧格式 Session 不支持记忆图")
    if exc.reason == "not_ready":
        return MemoryGraphError(503, "memory_graph_not_ready", "记忆图尚未就绪，请稍后刷新")
    if exc.reason == "lagging":
        return MemoryGraphError(503, "memory_component_lagging", "记忆图组件仍在更新，请稍后刷新")
    return MemoryGraphError(500, "memory_graph_failed", "记忆图读取失败")


def _safe_version_details(signature: dict[str, Any] | None) -> dict[str, Any]:
    if not signature:
        return {}
    return {
        key: signature.get(key)
        for key in ("memory_version", "graph_version", "semantic_version")
    }
