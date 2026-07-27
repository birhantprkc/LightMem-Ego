import importlib.util
import json
import sys
import types
from pathlib import Path


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _install_import_stubs() -> None:
    online_preprocess = sys.modules.get("online_preprocess") or types.ModuleType("online_preprocess")
    online_preprocess.__path__ = []
    io_utils = sys.modules.get("online_preprocess.io_utils") or types.ModuleType("online_preprocess.io_utils")
    io_utils.ffmpeg_bin = lambda: "ffmpeg"
    io_utils.ffprobe_bin = lambda: "ffprobe"
    io_utils.read_json = lambda path, default=None: json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else default
    io_utils.utc_now_iso = lambda: "2026-07-16T00:00:00+00:00"
    io_utils.write_json_atomic = lambda path, data: _write_json(Path(path), data)
    sys.modules["online_preprocess"] = online_preprocess
    sys.modules["online_preprocess.io_utils"] = io_utils


_install_import_stubs()

MODULE_PATH = Path(__file__).resolve().parents[1] / "online_short_term" / "stream_chunk_manager.py"
SPEC = importlib.util.spec_from_file_location("stream_chunk_manager", MODULE_PATH)
assert SPEC is not None
stream_chunk_manager = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(stream_chunk_manager)
StreamChunkManager = stream_chunk_manager.StreamChunkManager


def test_init_stream_reopens_terminal_stream_state(tmp_path: Path) -> None:
    session_dir = tmp_path / "session1"
    manager = StreamChunkManager(session_dir)
    first = manager.init_stream(metadata={"run_id": "day1"})
    assert first["status"] == "running"

    def mark_ended(state: dict) -> None:
        state["status"] = "ended"
        state["ended_at"] = "2026-07-16T00:01:00+00:00"
        state["stream_end_task_id"] = "end-task"
        state["stream_end_task_path"] = "tasks/end-task.json"
        state["final_chunk_index"] = 0
        state["final_upload_chunk_index"] = 0
        state["close_open_event"] = True

    manager.update_stream_state_locked(mark_ended)
    assert manager.load_stream_state(default={})["status"] == "ended"

    reopened = manager.init_stream(metadata={"run_id": "day2"})
    persisted = manager.load_stream_state(default={})

    assert reopened["status"] == "running"
    assert persisted["status"] == "running"
    assert persisted["ended_at"] is None
    assert persisted["stream_end_task_id"] is None
    assert persisted["stream_end_task_path"] is None
    assert persisted["final_chunk_index"] is None
    assert persisted["final_upload_chunk_index"] is None
    assert persisted["close_open_event"] is None
