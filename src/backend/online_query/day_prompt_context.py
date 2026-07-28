from __future__ import annotations

from typing import Any


def build_day_context_block(day_context: dict[str, Any] | None) -> str:
    if not isinstance(day_context, dict):
        return ""
    day_label = str(day_context.get("day_label") or "").strip()
    display_day_label = str(day_context.get("display_day_label") or "").strip()
    weekday_label = str(day_context.get("weekday_label") or "").strip()
    if not day_label and not display_day_label:
        return ""
    day_index = day_context.get("day_index")
    run_id = str(day_context.get("run_id") or "").strip()
    relative_ts_base_ms = day_context.get("relative_ts_base_ms")

    lines = ["Current Rokid demo day context:"]
    if display_day_label:
        lines.append(f"- current_day: {display_day_label}")
    elif day_label:
        lines.append(f"- current_day: {day_label}")
    if day_index is not None:
        lines.append(f"- current_day_index: {day_index}")
    if day_label:
        lines.append(f"- current_day_label: {day_label}")
    if weekday_label:
        lines.append(f"- current_weekday: {weekday_label}")
    if run_id:
        lines.append(f"- current_run_id: {run_id}")
    if relative_ts_base_ms is not None:
        lines.append(f"- current_day_relative_start_ms: {relative_ts_base_ms}")
    lines.append("Use this demo day context as authoritative for questions about current, previous, next, today, yesterday, or weekday references.")
    lines.append("Do not use real calendar dates for Rokid demo-day answers; answer with DAY labels and weekdays when dates matter.")
    return "\n".join(lines)
