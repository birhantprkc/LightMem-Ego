from __future__ import annotations

import os
import shutil
from pathlib import Path
from uuid import uuid4

from online_preprocess.io_utils import read_json


def materialize_active_snapshot(session_dir: Path) -> bool:
    """Copy an immutable edit snapshot back to legacy writable component roots."""
    session_dir = Path(session_dir)
    config = read_json(session_dir / "em2mem" / "memory_config.json", default={})
    if not isinstance(config, dict):
        return False
    query_args = config.get("query_rag_args") if isinstance(config.get("query_rag_args"), dict) else {}
    mappings = (
        (query_args.get("episodic_caption_root") or config.get("caption_root"), session_dir / "em2mem" / "caption_root"),
        (query_args.get("episodic_sidecar_root") or config.get("sidecar_root"), session_dir / "em2mem" / "sidecar_root"),
        (query_args.get("semantic_root") or config.get("semantic_root"), session_dir / "em2mem" / "semantic_root"),
        (config.get("visual_root"), session_dir / "em2mem" / "visual_root"),
        (query_args.get("visual_root"), session_dir / "em2mem" / "embeddings"),
    )
    changed = False
    for configured, target in mappings:
        source = _safe_config_path(session_dir, configured)
        if source is None or not source.is_dir() or source.resolve() == target.resolve():
            continue
        _replace_directory(source, target)
        changed = True

    visual_items = _safe_config_path(session_dir, config.get("visual_items_path"))
    if visual_items is not None and visual_items.is_file():
        target = session_dir / "em2mem" / "visual" / "visual_items.jsonl"
        if visual_items.resolve() != target.resolve():
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(f"{target.name}.{uuid4().hex}.tmp")
            shutil.copy2(visual_items, temp)
            os.replace(temp, target)
            changed = True
    return changed


def _safe_config_path(session_dir: Path, value: object) -> Path | None:
    if value is None or not str(value).strip():
        return None
    candidate = Path(str(value))
    if not candidate.is_absolute():
        candidate = session_dir / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(session_dir.resolve())
    except ValueError:
        return None
    return resolved


def _replace_directory(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    if temp.exists():
        shutil.rmtree(temp)
    shutil.copytree(source, temp)
    if target.exists():
        shutil.rmtree(target)
    os.replace(temp, target)
