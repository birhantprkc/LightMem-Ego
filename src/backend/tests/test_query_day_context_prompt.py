import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "online_query" / "day_prompt_context.py"
SPEC = importlib.util.spec_from_file_location("day_prompt_context", MODULE_PATH)
assert SPEC is not None
day_prompt_context = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(day_prompt_context)
build_day_context_block = day_prompt_context.build_day_context_block


def test_builds_rokid_demo_day_context_for_single_session() -> None:
    day_context = {
        "day_label": "DAY3",
        "day_index": 3,
        "weekday_label": "周三",
        "display_day_label": "DAY3 周三",
        "run_id": "83d7d0b9-76d3-4ee8-8af1-466ba7339e1b",
        "relative_ts_base_ms": 120000,
    }

    result = build_day_context_block(day_context)

    assert "Current Rokid demo day context:" in result
    assert "- current_day: DAY3 周三" in result
    assert "- current_day_label: DAY3" in result
    assert "- current_day_index: 3" in result
    assert "- current_weekday: 周三" in result
    assert "- current_day_relative_start_ms: 120000" in result
    assert "Do not use real calendar dates" in result
    assert "parent_session_id" not in result
    assert "child_session_id" not in result


def test_does_not_modify_query_without_day_context() -> None:
    assert build_day_context_block({"is_rokid_day_child": False}) == ""
    assert build_day_context_block(None) == ""
