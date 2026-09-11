from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from online_preprocess.io_utils import read_json

from .repository import ActiveMemoryRoot, LongTermMemoryRepository, MemoryRepositoryError


class MemoryGraphRepositoryError(RuntimeError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class MemoryGraphProbe:
    active: ActiveMemoryRoot
    config: dict[str, Any]
    signature: dict[str, Any]


@dataclass(frozen=True)
class MemoryGraphSources:
    captions: list[dict[str, Any]]
    episodic_graph: dict[str, Any]
    semantic_memory: dict[str, Any]


class LongTermMemoryGraphRepository:
    def __init__(self, sessions_root: Path, session_id: str) -> None:
        self.sessions_root = Path(sessions_root)
        self.session_id = session_id
        self.base = LongTermMemoryRepository(self.sessions_root, session_id)

    def probe(self) -> MemoryGraphProbe:
        try:
            active = self.base.resolve_active_root()
        except FileNotFoundError:
            raise
        except MemoryRepositoryError as exc:
            raise MemoryGraphRepositoryError("not_ready", "memory is not ready") from exc
        if active.kind != "em2mem":
            raise MemoryGraphRepositoryError("unsupported", "active memory root is not em2mem")
        signature = self._signature(active.config)
        self._ensure_ready(signature)
        return MemoryGraphProbe(active=active, config=active.config, signature=signature)

    def reload_probe(self, probe: MemoryGraphProbe) -> MemoryGraphProbe:
        try:
            config = self.base.reload_config(probe.active)
        except MemoryRepositoryError as exc:
            raise MemoryGraphRepositoryError("not_ready", "memory is not ready") from exc
        signature = self._signature(config)
        self._ensure_ready(signature)
        return MemoryGraphProbe(active=probe.active, config=config, signature=signature)

    def load_sources(self, config: dict[str, Any]) -> MemoryGraphSources:
        query_args = config.get("query_rag_args") if isinstance(config.get("query_rag_args"), dict) else {}
        subject = str(query_args.get("subject") or self.session_id).strip() or self.session_id
        model = str(query_args.get("retriever_model") or "").strip()
        caption_root = self._configured_root(query_args.get("episodic_caption_root") or config.get("caption_root"))
        sidecar_root = self._configured_root(query_args.get("episodic_sidecar_root") or config.get("sidecar_root"))
        semantic_root = self._configured_root(query_args.get("semantic_root") or config.get("semantic_root"))

        if caption_root is None or sidecar_root is None or semantic_root is None:
            raise MemoryGraphRepositoryError("not_ready", "memory graph paths are not configured")

        caption_path = self._safe_path(caption_root / f"{subject}_30sec.json")
        graph_dir = self._safe_path(sidecar_root / "30s")
        graph_path = self._resolve_model_file(
            graph_dir,
            exact_name=f"episodic_graph_30s_{model}.json" if model else None,
            pattern="episodic_graph_30s_*.json",
        )
        semantic_path = self._resolve_model_file(
            semantic_root,
            exact_name=f"semantic_memory_{model}.json" if model else None,
            pattern="semantic_memory_*.json",
        )
        if not caption_path.is_file() or graph_path is None or semantic_path is None:
            raise MemoryGraphRepositoryError("not_ready", "memory graph files are not ready")

        try:
            captions_value = read_json(caption_path, default=None)
            graph_value = read_json(graph_path, default=None)
            semantic_value = read_json(semantic_path, default=None)
        except Exception as exc:
            raise MemoryGraphRepositoryError("failed", "invalid memory graph JSON") from exc

        if not isinstance(captions_value, list) or not all(isinstance(item, dict) for item in captions_value):
            raise MemoryGraphRepositoryError("failed", "invalid caption graph source")
        if not isinstance(graph_value, dict):
            raise MemoryGraphRepositoryError("failed", "invalid episodic graph source")
        if not isinstance(graph_value.get("nodes", []), list) or not isinstance(graph_value.get("edges", []), list):
            raise MemoryGraphRepositoryError("failed", "invalid episodic graph collections")
        if not isinstance(graph_value.get("doc_id_to_event_id", {}), dict):
            raise MemoryGraphRepositoryError("failed", "invalid episodic graph index")

        if isinstance(semantic_value, list):
            semantic_value = {"facts": semantic_value, "timeline": []}
        if not isinstance(semantic_value, dict):
            raise MemoryGraphRepositoryError("failed", "invalid semantic graph source")
        if not isinstance(semantic_value.get("facts", []), list) or not isinstance(semantic_value.get("timeline", []), list):
            raise MemoryGraphRepositoryError("failed", "invalid semantic graph collections")

        return MemoryGraphSources(
            captions=[dict(item) for item in captions_value],
            episodic_graph=graph_value,
            semantic_memory=semantic_value,
        )

    def _safe_path(self, path: Path) -> Path:
        try:
            return self.base._ensure_session_path(path)
        except MemoryRepositoryError as exc:
            raise MemoryGraphRepositoryError("failed", "unsafe memory graph path") from exc

    def _configured_root(self, value: Any) -> Path | None:
        if value is None or not str(value).strip():
            return None
        configured = Path(str(value))
        if configured.is_absolute() or any(part == ".." for part in configured.parts):
            raise MemoryGraphRepositoryError("failed", "unsafe memory graph path")
        try:
            return self.base._config_path(value)
        except MemoryRepositoryError as exc:
            raise MemoryGraphRepositoryError("failed", "unsafe memory graph path") from exc

    def _resolve_model_file(self, root: Path, *, exact_name: str | None, pattern: str) -> Path | None:
        root = self._safe_path(root)
        if exact_name:
            exact = self._safe_path(root / exact_name)
            if exact.is_file():
                return exact
        if not root.is_dir():
            return None
        candidates = [self._safe_path(path) for path in sorted(root.glob(pattern)) if path.is_file()]
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            raise MemoryGraphRepositoryError("failed", "ambiguous memory graph model files")
        return None

    @staticmethod
    def _signature(config: dict[str, Any]) -> dict[str, Any]:
        building = config.get("building_versions") if isinstance(config.get("building_versions"), dict) else {}
        lag = config.get("lag") if isinstance(config.get("lag"), dict) else {}
        readiness = config.get("readiness") if isinstance(config.get("readiness"), dict) else {}
        return {
            "memory_version": _positive_int(config.get("latest_ready_memory_version") or config.get("memory_version")),
            "graph_version": _positive_int(config.get("latest_graph_ready_version") or config.get("graph_version")),
            "semantic_version": _positive_int(config.get("latest_semantic_ready_version") or config.get("semantic_version")),
            "building_memory_version": config.get("building_memory_version"),
            "building_graph_version": building.get("graph"),
            "building_semantic_version": building.get("semantic"),
            "graph_lagging": bool(lag.get("graph_lagging")),
            "semantic_lagging": bool(lag.get("semantic_lagging")),
            "graph_ready": readiness.get("graph_ready"),
            "semantic_ready": readiness.get("semantic_ready"),
            "updated_at": config.get("updated_at") or config.get("last_ready_at"),
        }

    @staticmethod
    def _ensure_ready(signature: dict[str, Any]) -> None:
        memory_version = signature.get("memory_version")
        graph_version = signature.get("graph_version")
        semantic_version = signature.get("semantic_version")
        if not memory_version or not graph_version or not semantic_version:
            raise MemoryGraphRepositoryError("not_ready", "memory graph versions are not ready")
        if signature.get("graph_ready") is False or signature.get("semantic_ready") is False:
            raise MemoryGraphRepositoryError("not_ready", "memory graph components are not ready")
        if (
            signature.get("building_memory_version") is not None
            or signature.get("building_graph_version") is not None
            or signature.get("building_semantic_version") is not None
            or signature.get("graph_lagging")
            or signature.get("semantic_lagging")
            or graph_version != memory_version
            or semantic_version != memory_version
        ):
            raise MemoryGraphRepositoryError("lagging", "memory graph components are lagging")


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
