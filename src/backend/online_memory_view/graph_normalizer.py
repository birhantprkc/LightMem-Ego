from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote

from online_memory.content import effective_episodic_content

from .graph_repository import MemoryGraphSources
from .schemas import (
    FORBIDDEN_NESTED_KEYS,
    MEMORY_GRAPH_IMAGE_SUFFIXES,
    MEMORY_GRAPH_MAX_ARRAY_ITEMS,
    MEMORY_GRAPH_MAX_DEPTH,
)


_DAY_RE = re.compile(r"\bDAY\s*0*(\d+)\b", re.IGNORECASE)
_ISO_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


class MemoryGraphNormalizer:
    def __init__(self, session_id: str, session_dir: Path) -> None:
        self.session_id = session_id
        self.session_dir = Path(session_dir)
        self.invalid_edge_count = 0
        self.invalid_fact_count = 0
        self.unresolved_support_count = 0
        self.truncated_field_count = 0

    def normalize(self, sources: MemoryGraphSources) -> dict[str, Any]:
        docs_by_id = self._source_documents(sources.captions)
        day_offsets = _build_day_offsets(docs_by_id.values())
        raw_graph = sources.episodic_graph
        raw_nodes = [item for item in raw_graph.get("nodes", []) if isinstance(item, dict)]
        raw_edges = [item for item in raw_graph.get("edges", []) if isinstance(item, dict)]
        raw_doc_index = {
            str(key).strip(): str(value).strip()
            for key, value in (raw_graph.get("doc_id_to_event_id") or {}).items()
            if _safe_identifier(key) and _safe_identifier(value)
        }
        inverse_doc_index = {event_id: doc_id for doc_id, event_id in raw_doc_index.items()}

        event_nodes, event_by_id, doc_id_to_event_id = self._events(
            raw_nodes,
            docs_by_id,
            day_offsets,
            inverse_doc_index,
        )
        raw_entity_map, entity_labels = self._raw_entities(raw_nodes)
        episodic_edges, entity_stats, edge_stats = self._episodic_edges(
            raw_edges,
            event_by_id,
            raw_entity_map,
            entity_labels,
        )
        episodic_entities = [
            {
                "id": entity_id,
                "kind": "entity",
                "label": _display_label(entity_labels.get(entity_id, set())),
                "mention_count": entity_stats[entity_id]["mention_count"],
                "event_count": len(entity_stats[entity_id]["event_ids"]),
            }
            for entity_id in sorted(entity_labels, key=lambda value: (_normalize_text(_display_label(entity_labels[value])), value))
        ]

        documents = self._documents(docs_by_id, doc_id_to_event_id, day_offsets)
        orphan_document_count = sum(1 for doc_id in documents if doc_id not in doc_id_to_event_id)

        semantic_nodes, semantic_edges, timeline, event_to_facts, fact_to_events = self._semantic(
            sources.semantic_memory,
            event_by_id,
            doc_id_to_event_id,
        )

        event_order = {node["id"]: index for index, node in enumerate(event_nodes)}
        indexes = {
            "doc_id_to_event_id": dict(sorted(doc_id_to_event_id.items())),
            "event_id_to_fact_ids": {
                event_id: sorted(set(event_to_facts.get(event_id, [])))
                for event_id in (node["id"] for node in event_nodes)
            },
            "fact_id_to_event_ids": {
                fact_id: sorted(set(event_ids), key=lambda value: (event_order.get(value, 10**12), value))
                for fact_id, event_ids in sorted(fact_to_events.items())
            },
        }

        return {
            "stats": {
                "documents": len(documents),
                "episodic": {
                    "events": len(event_nodes),
                    "entities": len(episodic_entities),
                    "before_edges": edge_stats["before_edges"],
                    "mentions_edges": edge_stats["mentions_edges"],
                    "raw_mentions_edges": edge_stats["raw_mentions_edges"],
                    "relation_edges": edge_stats["relation_edges"],
                },
                "semantic": {
                    "entities": len(semantic_nodes),
                    "facts": len(semantic_edges),
                    "timeline_entries": len(timeline),
                },
            },
            "episodic": {"nodes": event_nodes + episodic_entities, "edges": episodic_edges},
            "semantic": {"nodes": semantic_nodes, "edges": semantic_edges, "timeline": timeline},
            "documents": documents,
            "indexes": indexes,
            "warnings": {
                "invalid_edge_count": self.invalid_edge_count,
                "invalid_fact_count": self.invalid_fact_count,
                "orphan_document_count": orphan_document_count,
                "unresolved_support_count": self.unresolved_support_count,
                "truncated_field_count": self.truncated_field_count,
            },
        }

    @staticmethod
    def _source_documents(captions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        documents: dict[str, dict[str, Any]] = {}
        for item in captions:
            doc_id = str(item.get("doc_id") or item.get("evidence_doc_id") or "").strip()
            if _safe_identifier(doc_id) and doc_id not in documents:
                documents[doc_id] = item
        return documents

    def _events(
        self,
        raw_nodes: list[dict[str, Any]],
        docs_by_id: dict[str, dict[str, Any]],
        day_offsets: dict[str, float],
        inverse_doc_index: dict[str, str],
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, str]]:
        events: list[dict[str, Any]] = []
        event_by_id: dict[str, dict[str, Any]] = {}
        doc_index: dict[str, str] = {}
        for raw in raw_nodes:
            if str(raw.get("type") or raw.get("kind") or "").casefold() != "event":
                continue
            event_id = str(raw.get("id") or "").strip()
            if not _safe_identifier(event_id) or event_id in event_by_id:
                self.invalid_edge_count += 1
                continue
            doc_id = str(inverse_doc_index.get(event_id) or raw.get("doc_id") or raw.get("label") or "").strip()
            doc = docs_by_id.get(doc_id, {})
            event_time = _event_time(doc, day_offsets)
            title = _event_title(doc, raw)
            event = {
                "id": event_id,
                "kind": "event",
                "doc_id": doc_id,
                "label": _event_label(event_time),
                "title": title,
                "description": _text(raw.get("text")) or _text(doc.get("text")),
                "event_time": event_time,
                "confidence": _confidence(doc.get("confidence")),
                "status": _optional_text(doc.get("status")),
                "counts": {
                    "objects": len(_as_list(doc.get("visual_objects") or doc.get("visual_object_threads"))),
                    "actions": len(_as_list(doc.get("main_actions") or doc.get("action_threads"))),
                    "state_changes": len(_as_list(doc.get("state_changes"))),
                },
            }
            events.append(event)
            event_by_id[event_id] = event
            if doc_id:
                doc_index.setdefault(doc_id, event_id)
        events.sort(key=_event_sort_key)
        return events, event_by_id, doc_index

    @staticmethod
    def _raw_entities(raw_nodes: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, set[str]]]:
        raw_to_canonical: dict[str, str] = {}
        labels: dict[str, set[str]] = defaultdict(set)
        for raw in raw_nodes:
            if str(raw.get("type") or raw.get("kind") or "").casefold() != "entity":
                continue
            raw_id = str(raw.get("id") or "").strip()
            label = _text(raw.get("label"))
            entity_id = canonical_entity_id(label)
            if not _safe_identifier(raw_id) or not entity_id:
                continue
            raw_to_canonical[raw_id] = entity_id
            labels[entity_id].add(label)
        return raw_to_canonical, labels

    def _episodic_edges(
        self,
        raw_edges: list[dict[str, Any]],
        event_by_id: dict[str, dict[str, Any]],
        raw_entity_map: dict[str, str],
        entity_labels: dict[str, set[str]],
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, int]]:
        before: dict[tuple[str, str], int] = defaultdict(int)
        mentions: dict[tuple[str, str], int] = defaultdict(int)
        relations: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        raw_mentions = 0
        entity_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {"mention_count": 0, "event_ids": set()})

        for raw in raw_edges:
            raw_kind = _text(raw.get("type") or raw.get("kind"))
            source = str(raw.get("source") or "").strip()
            target = str(raw.get("target") or "").strip()
            if raw_kind == "before":
                if source not in event_by_id or target not in event_by_id:
                    self.invalid_edge_count += 1
                    continue
                before[(source, target)] += 1
                continue
            if raw_kind == "mentions":
                raw_mentions += 1
                entity_id = raw_entity_map.get(target)
                if source not in event_by_id or not entity_id:
                    self.invalid_edge_count += 1
                    continue
                mentions[(source, entity_id)] += 1
                entity_stats[entity_id]["mention_count"] += 1
                entity_stats[entity_id]["event_ids"].add(source)
                continue

            event_id = str(raw.get("event_id") or "").strip()
            source_id = raw_entity_map.get(source)
            target_id = raw_entity_map.get(target)
            relation = raw_kind
            normalized_relation = _normalize_text(relation)
            if not source_id or not target_id or not normalized_relation or event_id not in event_by_id:
                self.invalid_edge_count += 1
                continue
            key = (event_id, source_id, normalized_relation, target_id)
            record = relations.setdefault(key, {"count": 0, "labels": set()})
            record["count"] += 1
            record["labels"].add(relation)

        edges: list[dict[str, Any]] = []
        for (source, target), count in sorted(before.items()):
            edges.append(
                {
                    "id": _edge_id("before", source, target, "", ""),
                    "kind": "before",
                    "source": source,
                    "target": target,
                    "confidence": None,
                    "occurrence_count": count,
                }
            )
        for (event_id, entity_id), count in sorted(mentions.items()):
            edges.append(
                {
                    "id": _edge_id("mentions", event_id, entity_id, event_id, ""),
                    "kind": "mentions",
                    "source": event_id,
                    "target": entity_id,
                    "event_id": event_id,
                    "confidence": event_by_id[event_id].get("confidence"),
                    "occurrence_count": count,
                }
            )
        for (event_id, source, normalized_relation, target), record in sorted(relations.items()):
            relation = _display_label(record["labels"])
            edges.append(
                {
                    "id": _edge_id("entity_relation", source, target, event_id, normalized_relation),
                    "kind": "entity_relation",
                    "source": source,
                    "target": target,
                    "event_id": event_id,
                    "relation": relation,
                    "confidence": event_by_id[event_id].get("confidence"),
                    "occurrence_count": record["count"],
                }
            )

        for entity_id in entity_labels:
            entity_stats[entity_id]
        return edges, entity_stats, {
            "before_edges": len(before),
            "mentions_edges": len(mentions),
            "raw_mentions_edges": raw_mentions,
            "relation_edges": len(relations),
        }

    def _documents(
        self,
        docs_by_id: dict[str, dict[str, Any]],
        doc_id_to_event_id: dict[str, str],
        day_offsets: dict[str, float],
    ) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for doc_id in sorted(docs_by_id):
            doc = docs_by_id[doc_id]
            content = effective_episodic_content(doc)
            result[doc_id] = {
                "doc_id": doc_id,
                "event_id": doc_id_to_event_id.get(doc_id),
                "event_time": _event_time(doc, day_offsets),
                "text": content,
                "caption": content,
                "visual_summary": _text(doc.get("visual_summary")),
                "transcript": _text(doc.get("transcript")),
                "transcript_segments": self._safe_value(_as_list(doc.get("transcript_segments")), 0),
                "scene": _text(doc.get("scene")),
                "scene_summary": self._safe_value(doc.get("scene_summary") if isinstance(doc.get("scene_summary"), dict) else {}, 0),
                "visual_objects": self._safe_value(_as_list(doc.get("visual_objects") or doc.get("visual_object_threads")), 0),
                "actions": self._safe_value(_as_list(doc.get("main_actions") or doc.get("action_threads")), 0),
                "state_changes": self._safe_value(_as_list(doc.get("state_changes")), 0),
                "topic_threads": self._safe_value(_as_list(doc.get("topic_threads")), 0),
                "critical_speech_lines": self._safe_value(_as_list(doc.get("critical_speech_lines")), 0),
                "confidence": _confidence(doc.get("confidence")),
                "status": _optional_text(doc.get("status")),
                "keyframes": self._keyframes(doc),
            }
        return result

    def _keyframes(self, doc: dict[str, Any]) -> list[dict[str, Any]]:
        caption_meta: dict[str, dict[str, Any]] = {}
        for raw in _as_list(doc.get("keyframe_captions")):
            if isinstance(raw, dict) and raw.get("path"):
                caption_meta[str(raw["path"])] = raw
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for value in _as_list(doc.get("keyframe_paths"))[:MEMORY_GRAPH_MAX_ARRAY_ITEMS]:
            raw_path = str(value or "").strip().replace("\\", "/")
            if not raw_path or raw_path in seen:
                continue
            relative = Path(raw_path)
            if relative.is_absolute() or any(part == ".." for part in relative.parts):
                continue
            if relative.suffix.lower() not in MEMORY_GRAPH_IMAGE_SUFFIXES:
                continue
            try:
                (self.session_dir / relative).resolve().relative_to(self.session_dir.resolve())
            except ValueError:
                continue
            seen.add(raw_path)
            meta = caption_meta.get(raw_path, {})
            result.append(
                {
                    "thumbnail_url": f"/session/{quote(self.session_id, safe='')}/file?path={quote(relative.as_posix(), safe='')}",
                    "timestamp_seconds": _clock_value(meta.get("timestamp")),
                }
            )
        raw_count = len(_as_list(doc.get("keyframe_paths")))
        if raw_count > MEMORY_GRAPH_MAX_ARRAY_ITEMS:
            self.truncated_field_count += 1
        return result

    def _semantic(
        self,
        semantic_memory: dict[str, Any],
        event_by_id: dict[str, dict[str, Any]],
        doc_id_to_event_id: dict[str, str],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, list[str]], dict[str, list[str]]]:
        fact_edges: list[dict[str, Any]] = []
        seen_fact_ids: set[str] = set()
        entity_labels: dict[str, set[str]] = defaultdict(set)
        entity_facts: dict[str, set[str]] = defaultdict(set)
        entity_support: dict[str, int] = defaultdict(int)
        entity_first: dict[str, list[dict[str, Any]]] = defaultdict(list)
        entity_last: dict[str, list[dict[str, Any]]] = defaultdict(list)
        event_to_facts: dict[str, list[str]] = defaultdict(list)
        fact_to_events: dict[str, list[str]] = {}
        ordered_events = sorted(event_by_id.values(), key=_event_sort_key)
        event_order = {event["id"]: index for index, event in enumerate(ordered_events)}

        for raw in semantic_memory.get("facts", []):
            if not isinstance(raw, dict):
                self.invalid_fact_count += 1
                continue
            triple = raw.get("triple") if isinstance(raw.get("triple"), list) else []
            head = _text(raw.get("head")) or (_text(triple[0]) if len(triple) > 0 else "")
            relation = _text(raw.get("relation")) or (_text(triple[1]) if len(triple) > 1 else "")
            tail = _text(raw.get("tail")) or (_text(triple[2]) if len(triple) > 2 else "")
            source = canonical_entity_id(head)
            target = canonical_entity_id(tail)
            if not source or not target or not relation:
                self.invalid_fact_count += 1
                continue
            raw_support_docs = _merge_string_lists(
                raw.get("support_docs"),
                raw.get("evidence_event_ids"),
                raw.get("source_doc_ids"),
                raw.get("provenance_root_ids"),
            )
            support_docs = [value for value in raw_support_docs if _safe_identifier(value)]
            invalid_support_count = len(raw_support_docs) - len(support_docs)
            semantic_version = _nonnegative_int(raw.get("semantic_version"))
            raw_fact_id = str(raw.get("fact_id") or "").strip()
            fact_id = raw_fact_id if _safe_identifier(raw_fact_id) else _fact_id(head, relation, tail, support_docs, semantic_version)
            if fact_id in seen_fact_ids:
                self.invalid_fact_count += 1
                continue
            seen_fact_ids.add(fact_id)
            support_event_ids = [doc_id_to_event_id[doc_id] for doc_id in support_docs if doc_id in doc_id_to_event_id]
            support_event_ids = sorted(set(support_event_ids), key=lambda value: (event_order.get(value, 10**12), value))
            unresolved_count = invalid_support_count + sum(1 for doc_id in support_docs if doc_id not in doc_id_to_event_id)
            self.unresolved_support_count += unresolved_count
            support_count = _nonnegative_int(raw.get("support_count"))
            if support_count is None:
                support_count = len(support_docs)
            raw_support_count = _nonnegative_int(raw.get("raw_support_count"))
            if raw_support_count is None:
                raw_support_count = support_count
            first_seen = self._safe_seen(raw.get("first_seen"))
            last_seen = self._safe_seen(raw.get("last_seen"))
            edge = {
                "id": fact_id,
                "kind": "semantic_fact",
                "source": source,
                "target": target,
                "relation": relation,
                "label": relation,
                "confidence": _confidence(raw.get("confidence")),
                "support_count": support_count,
                "raw_support_count": raw_support_count,
                "habit_strength": _optional_text(raw.get("habit_strength")),
                "support_days": sorted(_merge_string_lists(raw.get("support_days"))),
                "support_scales": sorted(_merge_string_lists(raw.get("support_scales"))),
                "support_doc_ids": support_docs,
                "support_event_ids": support_event_ids,
                "unresolved_support_count": unresolved_count,
                "first_seen": first_seen,
                "last_seen": last_seen,
                "semantic_version": semantic_version,
            }
            fact_edges.append(edge)
            fact_to_events[fact_id] = support_event_ids
            for event_id in support_event_ids:
                event_to_facts[event_id].append(fact_id)
            entity_labels[source].add(head)
            entity_labels[target].add(tail)
            for entity_id in {source, target}:
                entity_facts[entity_id].add(fact_id)
                entity_support[entity_id] += support_count
                if first_seen:
                    entity_first[entity_id].append(first_seen)
                if last_seen:
                    entity_last[entity_id].append(last_seen)

        fact_edges.sort(key=lambda item: (-item["support_count"], -(item["confidence"] or 0.0), item["id"]))
        semantic_nodes = [
            {
                "id": entity_id,
                "kind": "entity",
                "label": _display_label(entity_labels[entity_id]),
                "fact_count": len(entity_facts[entity_id]),
                "total_support_count": entity_support[entity_id],
                "first_seen": min(entity_first[entity_id], key=_seen_key) if entity_first[entity_id] else {},
                "last_seen": max(entity_last[entity_id], key=_seen_key) if entity_last[entity_id] else {},
            }
            for entity_id in sorted(entity_labels, key=lambda value: (_normalize_text(_display_label(entity_labels[value])), value))
        ]
        valid_fact_ids = {edge["id"] for edge in fact_edges}
        timeline: list[dict[str, Any]] = []
        for raw in semantic_memory.get("timeline", []):
            if not isinstance(raw, dict):
                continue
            fact_ids = sorted({str(value) for value in _as_list(raw.get("fact_ids")) if str(value) in valid_fact_ids})
            if not fact_ids:
                continue
            timeline.append(
                {
                    "timestamp": _optional_text(raw.get("timestamp")),
                    "fact_ids": fact_ids,
                    "source": _optional_text(raw.get("source")),
                }
            )
        timeline.sort(key=lambda item: (_timeline_key(item.get("timestamp")), str(item.get("timestamp") or ""), tuple(item["fact_ids"])))
        return semantic_nodes, fact_edges, timeline, event_to_facts, fact_to_events

    def _safe_seen(self, value: Any) -> dict[str, Any]:
        return self._safe_value(value, 0) if isinstance(value, dict) else {}

    def _safe_value(self, value: Any, depth: int) -> Any:
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if depth >= MEMORY_GRAPH_MAX_DEPTH:
            self.truncated_field_count += 1
            return {"truncated": True, "reason": "max_depth"}
        if isinstance(value, list):
            selected = value[:MEMORY_GRAPH_MAX_ARRAY_ITEMS]
            items = [self._safe_value(item, depth + 1) for item in selected]
            if len(value) > MEMORY_GRAPH_MAX_ARRAY_ITEMS:
                self.truncated_field_count += 1
                return items
            return items
        if isinstance(value, dict):
            return {
                str(key): self._safe_value(item, depth + 1)
                for key, item in value.items()
                if not _forbidden_key(str(key))
            }
        return str(value)


def canonical_entity_id(label: Any) -> str | None:
    normalized = _normalize_text(label)
    if not normalized:
        return None
    return "ent_" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return " ".join(text.split()).casefold()


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple, set)):
        return ""
    return " ".join(str(value).strip().split())


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _display_label(values: set[str]) -> str:
    valid = [value for value in values if _text(value)]
    return min(valid, key=lambda value: (_normalize_text(value), value)) if valid else ""


def _edge_id(kind: str, source: str, target: str, event_id: str, relation: str) -> str:
    raw = "\x1f".join((kind, source, target, event_id, relation))
    return "epe_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _fact_id(head: str, relation: str, tail: str, support_docs: list[str], semantic_version: int | None) -> str:
    raw = "\x1f".join((_normalize_text(head), _normalize_text(relation), _normalize_text(tail), ",".join(support_docs), str(semantic_version or "")))
    return "fact_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    return None


def _clock_value(value: Any) -> float | None:
    numeric = _finite_number(value)
    if numeric is not None:
        return numeric
    text = str(value or "").strip()
    if not text:
        return None
    if re.fullmatch(r"\d{8}", text):
        hours = int(text[0:2])
        minutes = int(text[2:4])
        seconds = int(text[4:6])
        fraction = int(text[6:8]) / 100.0
        if minutes < 60 and seconds < 60:
            return hours * 3600.0 + minutes * 60.0 + seconds + fraction
        return None
    parts = text.split(":")
    if len(parts) == 3:
        try:
            parsed = int(parts[0]) * 3600.0 + int(parts[1]) * 60.0 + float(parts[2])
        except ValueError:
            return None
        return parsed if math.isfinite(parsed) else None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def _event_time(doc: dict[str, Any], day_offsets: dict[str, float]) -> dict[str, Any]:
    start = _finite_number(doc.get("start"))
    if start is None:
        start = _clock_value(doc.get("local_start_time"))
    if start is None:
        start = _clock_value(doc.get("start_time"))
    end = _finite_number(doc.get("end"))
    if end is None:
        end = _clock_value(doc.get("local_end_time"))
    if end is None:
        end = _clock_value(doc.get("end_time"))
    date_label = _text(doc.get("date") or doc.get("day_label"))
    offset = day_offsets.get(date_label, 0.0)
    return {
        "date": date_label or None,
        "start_code": _optional_text(doc.get("start_time")),
        "end_code": _optional_text(doc.get("end_time")),
        "start_seconds": start,
        "end_seconds": end,
        "timeline_start_seconds": offset + start if start is not None else None,
        "timeline_end_seconds": offset + end if end is not None else None,
    }


def _event_title(doc: dict[str, Any], raw: dict[str, Any]) -> str:
    summary = doc.get("scene_summary")
    if isinstance(summary, dict):
        candidate = _text(summary.get("dominant_scene") or summary.get("scene"))
    else:
        candidate = _text(summary)
    candidate = candidate or _text(doc.get("scene"))
    candidate = candidate or _text(effective_episodic_content(doc) or raw.get("text"))
    if not candidate:
        return "Untitled event"
    first = re.split(r"(?<=[.!?。！？])\s+", candidate, maxsplit=1)[0]
    return first[:120].rstrip()


def _event_label(event_time: dict[str, Any]) -> str:
    return f"{_format_clock(event_time.get('start_seconds'))}–{_format_clock(event_time.get('end_seconds'))}"


def _format_clock(value: Any) -> str:
    numeric = _finite_number(value)
    if numeric is None:
        return "—"
    total = max(0, int(round(numeric)))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours == 0:
        return f"{minutes:02d}:{seconds:02d}"
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _event_sort_key(event: dict[str, Any]) -> tuple[int, float, float, str]:
    time = event.get("event_time") if isinstance(event.get("event_time"), dict) else {}
    start = _finite_number(time.get("timeline_start_seconds"))
    end = _finite_number(time.get("timeline_end_seconds"))
    return (1 if start is None else 0, start or 0.0, end or 0.0, str(event.get("id") or ""))


def _build_day_offsets(documents: Any) -> dict[str, float]:
    labels = sorted({_text(doc.get("date") or doc.get("day_label")) for doc in documents if isinstance(doc, dict)})
    labels = [label for label in labels if label]
    iso_values: dict[str, date] = {}
    for label in labels:
        match = _ISO_DATE_RE.search(label)
        if match:
            try:
                iso_values[label] = date.fromisoformat(match.group(1))
            except ValueError:
                pass
    earliest_iso = min(iso_values.values()) if iso_values else None
    offsets: dict[str, float] = {}
    unknown: list[str] = []
    for label in labels:
        day_match = _DAY_RE.search(label)
        if day_match:
            offsets[label] = max(0, int(day_match.group(1)) - 1) * 86400.0
        elif label in iso_values and earliest_iso is not None:
            offsets[label] = max(0, (iso_values[label] - earliest_iso).days) * 86400.0
        else:
            unknown.append(label)
    next_day = int(max(offsets.values(), default=-86400.0) / 86400.0) + 1
    for index, label in enumerate(sorted(unknown, key=lambda value: (_normalize_text(value), value))):
        offsets[label] = (next_day + index) * 86400.0
    return offsets


def _confidence(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return min(1.0, max(0.0, parsed))


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, parsed)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _merge_string_lists(*values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        for item in _as_list(value):
            text = str(item or "").strip()
            if text and text not in seen:
                seen.add(text)
                result.append(text)
    return result


def _safe_identifier(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(
        text
        and len(text) <= 512
        and "/" not in text
        and "\\" not in text
        and ".." not in text
        and not any(ord(char) < 32 for char in text)
    )


def _seen_key(value: dict[str, Any]) -> tuple[int, float, str, float, float]:
    date_label = _text(value.get("date"))
    day_match = _DAY_RE.search(date_label)
    iso_match = _ISO_DATE_RE.search(date_label)
    if day_match:
        date_key = (0, float(int(day_match.group(1))), "")
    elif iso_match:
        try:
            date_key = (1, float(date.fromisoformat(iso_match.group(1)).toordinal()), "")
        except ValueError:
            date_key = (2, 0.0, _normalize_text(date_label))
    else:
        date_key = (2, 0.0, _normalize_text(date_label))
    return (
        *date_key,
        _clock_value(value.get("start_time")) or 0.0,
        _clock_value(value.get("end_time")) or 0.0,
    )


def _timeline_key(value: Any) -> tuple[int, float]:
    parsed = _clock_value(value)
    return (1, 0.0) if parsed is None else (0, parsed)


def _forbidden_key(key: str) -> bool:
    normalized = key.strip().lower()
    return (
        normalized in FORBIDDEN_NESTED_KEYS
        or normalized.endswith("_path")
        or normalized.endswith("_paths")
        or "embedding" in normalized
        or "token" in normalized
    )
