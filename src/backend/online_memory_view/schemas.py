from __future__ import annotations

from typing import Final


SCHEMA_VERSION: Final[int] = 1
MEMORY_GRAPH_SCHEMA_VERSION: Final[int] = 1
MEMORY_SOURCE: Final[str] = "M_lt"
MEMORY_CATALOG_PAGE_SIZE: Final[int] = 10
MEMORY_CATALOG_CURSOR_VERSION: Final[int] = 1
EPISODIC_GRANULARITIES: Final[tuple[str, ...]] = ("30sec", "3min", "10min", "1h")
MEMORY_GRAPH_SCALES: Final[tuple[str, ...]] = ("30sec", "30s")
MEMORY_GRAPH_DEFAULT_MAX_RESPONSE_BYTES: Final[int] = 33_554_432
MEMORY_GRAPH_MIN_RESPONSE_BYTES: Final[int] = 1_048_576
MEMORY_GRAPH_MAX_ARRAY_ITEMS: Final[int] = 100
MEMORY_GRAPH_MAX_DEPTH: Final[int] = 6
MEMORY_GRAPH_IMAGE_SUFFIXES: Final[frozenset[str]] = frozenset({".jpg", ".jpeg", ".png", ".webp"})

EPISODIC_DATA_FIELDS: Final[tuple[str, ...]] = (
    "date",
    "duration",
    "text",
    "caption",
    "fine_caption",
    "visual_summary",
    "scene_summary",
    "transcript",
    "transcript_text",
    "critical_speech_lines",
    "key_observations",
    "topic_threads",
    "action_threads",
    "object_threads",
    "visual_object_threads",
    "salient_objects",
    "scene",
    "speakers",
    "speaker_stats",
    "events",
)

SEMANTIC_DATA_FIELDS: Final[tuple[str, ...]] = (
    "triple",
    "head",
    "relation",
    "tail",
    "semantic_summary",
    "support_count",
    "raw_support_count",
    "support_days",
    "support_scales",
    "habit_strength",
    "head_type",
    "tail_type",
)

VISUAL_DATA_FIELDS: Final[tuple[str, ...]] = (
    "keyframe_caption",
    "segment_caption",
    "scene",
    "visual_objects",
    "main_actions",
    "state_changes",
    "conversation_focus",
    "linked_memory_ids",
)

FORBIDDEN_NESTED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "video_path",
        "source_video_path",
        "clip_path",
        "image_path",
        "keyframe_path",
        "keyframe_paths",
        "file_path",
        "model_path",
        "embedding",
        "embeddings",
        "faiss",
        "graph",
        "hipporag",
        "snapshot",
        "token",
        "authorization",
    }
)
