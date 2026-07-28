import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_timestamp_utils():
    spec = importlib.util.spec_from_file_location(
        "memory_timestamp_utils_under_test",
        ROOT / "src" / "em2mem" / "memory" / "timestamp_utils.py",
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_memory_timestamp_accepts_weekday_suffix() -> None:
    module = _load_timestamp_utils()

    assert module.memory_timestamp_range("DAY1 周一", "00000000", "00003000") == (
        100000000,
        100003000,
    )
    assert module.memory_timestamp_range("1 周一", "00:00:30", "00:01:00") == (
        100003000,
        100010000,
    )


def test_memory_timestamp_rejects_unparseable_day() -> None:
    module = _load_timestamp_utils()

    try:
        module.memory_timestamp_range("周一", "00000000", "00003000")
    except ValueError as exc:
        assert "Invalid memory day label" in str(exc)
    else:
        raise AssertionError("expected ValueError for a day label without a numeric day")


def test_query_until_timestamp_accepts_weekday_suffix() -> None:
    timestamp_module = _load_timestamp_utils()
    assert timestamp_module.memory_timestamp_range("DAY2 周二", "00003000", "00003000")[0] == 200003000
