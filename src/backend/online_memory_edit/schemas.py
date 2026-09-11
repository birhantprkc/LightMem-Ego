from __future__ import annotations

from typing import Any, Final

try:
    from pydantic import BaseModel, PositiveInt
except Exception:  # pragma: no cover - keeps the module importable in workers
    BaseModel = object  # type: ignore
    PositiveInt = int  # type: ignore

from online_memory.content import EPISODIC_CONTENT_FIELDS


MAX_CHARS_PER_RECORD: Final[int] = 4_000
MAX_TOTAL_CHARS: Final[int] = 32_000
CONTENT_FIELDS: Final[tuple[str, ...]] = EPISODIC_CONTENT_FIELDS


def edit_policy() -> dict[str, Any]:
    return {
        "field": "episodic.30sec[].content",
        "maxCharsPerRecord": MAX_CHARS_PER_RECORD,
        "maxTotalChars": MAX_TOTAL_CHARS,
        "lengthUnit": "unicode_code_points",
    }


if BaseModel is not object:
    class ThirtySecondRecordUpdate(BaseModel):
        id: str
        content: str

    class ThirtySecondMemoryUpdateRequest(BaseModel):
        baseVersion: PositiveInt
        records: list[ThirtySecondRecordUpdate]

    class ThirtySecondMemoryRollbackRequest(BaseModel):
        currentVersion: PositiveInt
else:  # pragma: no cover
    ThirtySecondRecordUpdate = ThirtySecondMemoryUpdateRequest = ThirtySecondMemoryRollbackRequest = object  # type: ignore
