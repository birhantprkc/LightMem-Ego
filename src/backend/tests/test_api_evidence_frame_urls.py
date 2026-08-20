from pathlib import Path
import asyncio
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import api_server  # noqa: E402


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"image")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_augments_single_session_frames_with_file_urls(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(api_server, "ONLINE_SESSIONS_DIR", tmp_path)
    _touch(tmp_path / "session1" / "stream" / "day_assets" / "DAY1" / "stream" / "frames" / "frame_000074.jpg")
    _touch(tmp_path / "session1" / "stream" / "frames" / "frame_000051.jpg")
    payload = {
        "session_id": "session1",
        "result": {
            "session_id": "session1",
            "stream_context": {"long_term_session_id": "session1"},
            "evidence_frames": [
                {"path": "stream/day_assets/DAY1/stream/frames/frame_000074.jpg"},
                {"path": "stream/frames/frame_000051.jpg"},
            ],
        },
        "evidence_frames": [
            {"path": "stream/day_assets/DAY1/stream/frames/frame_000074.jpg"},
            {"path": "stream/frames/frame_000051.jpg"},
        ],
    }

    enhanced = api_server._augment_evidence_frames_for_response(payload, "session1")

    frames = enhanced["result"]["evidence_frames"]
    assert enhanced["evidence_frames"] == frames
    assert frames[0]["owner_session_id"] == "session1"
    assert frames[0]["file_url"] == "/session/session1/file?path=stream%2Fday_assets%2FDAY1%2Fstream%2Fframes%2Fframe_000074.jpg"
    assert frames[0]["relative_file_url"] == "/session/session1/file?path=stream%2Fday_assets%2FDAY1%2Fstream%2Fframes%2Fframe_000074.jpg"
    assert frames[0]["image_url"] == frames[0]["file_url"]
    assert frames[0]["url"] == frames[0]["file_url"]
    assert frames[0]["src"] == frames[0]["file_url"]
    assert frames[0]["file_available"] is True
    assert frames[1]["owner_session_id"] == "session1"
    assert frames[1]["file_url"] == "/session/session1/file?path=stream%2Fframes%2Fframe_000051.jpg"
    assert frames[1]["file_available"] is True


def test_existing_owner_session_is_preserved_and_missing_file_is_false(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(api_server, "ONLINE_SESSIONS_DIR", tmp_path)
    _touch(tmp_path / "explicit_owner" / "stream" / "day_assets" / "DAY1" / "stream" / "frames" / "frame_000074.jpg")
    payload = {
        "stream_context": {"long_term_session_id": "parent1"},
        "evidence_frames": [
            {
                "path": "stream/day_assets/DAY1/stream/frames/frame_000074.jpg",
                "owner_session_id": "explicit_owner",
            },
            {"path": "stream/day_assets/DAY1/stream/frames/missing.jpg"},
        ],
    }

    enhanced = api_server._augment_evidence_frames_for_response(payload, "parent1__day0002")

    frames = enhanced["evidence_frames"]
    assert frames[0]["owner_session_id"] == "explicit_owner"
    assert frames[0]["file_url"] == "/session/explicit_owner/file?path=stream%2Fday_assets%2FDAY1%2Fstream%2Fframes%2Fframe_000074.jpg"
    assert frames[0]["file_available"] is True
    assert frames[1]["owner_session_id"] == "parent1"
    assert frames[1]["file_url"] == "/session/parent1/file?path=stream%2Fday_assets%2FDAY1%2Fstream%2Fframes%2Fmissing.jpg"
    assert frames[1]["file_available"] is False


def test_api_base_url_makes_browser_ready_absolute_image_urls(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(api_server, "ONLINE_SESSIONS_DIR", tmp_path)
    _touch(tmp_path / "parent1" / "stream" / "day_assets" / "DAY1" / "stream" / "frames" / "frame_000074.jpg")
    payload = {
        "stream_context": {"long_term_session_id": "parent1"},
        "evidence_frames": [
            {"path": "stream/day_assets/DAY1/stream/frames/frame_000074.jpg"},
        ],
    }

    enhanced = api_server._augment_evidence_frames_for_response(
        payload,
        "parent1__day0002",
        api_base_url="http://127.0.0.1:8000",
    )

    frame = enhanced["evidence_frames"][0]
    assert frame["relative_file_url"] == "/session/parent1/file?path=stream%2Fday_assets%2FDAY1%2Fstream%2Fframes%2Fframe_000074.jpg"
    assert frame["file_url"] == "http://127.0.0.1:8000/session/parent1/file?path=stream%2Fday_assets%2FDAY1%2Fstream%2Fframes%2Fframe_000074.jpg"
    assert frame["image_url"] == frame["file_url"]
    assert frame["url"] == frame["file_url"]
    assert frame["src"] == frame["file_url"]
    assert frame["thumbnail_url"] == frame["file_url"]
    assert frame["file_available"] is True


def test_historical_ask_bypasses_single_active_session_without_changing_legacy_ask(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / "project"
    sessions_root = project_root / "online_sessions"
    monkeypatch.setenv("EM2MEM_SINGLE_ACTIVE_SESSION", "true")
    monkeypatch.setattr(api_server, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(api_server, "ONLINE_SESSIONS_DIR", sessions_root)
    _write_json(project_root / "runtime" / "active_session.json", {"active_session_id": "active_session"})
    _write_json(sessions_root / "old_session" / "em2mem" / "memory_config.json", {"status": "memory_ready"})
    _write_json(sessions_root / "old_session" / "status.json", {"stage": "memory_ready", "progress": 100})

    legacy_request = api_server.AskRequest(question="what happened?", mode="async")
    legacy_response = asyncio.run(api_server.ask_session("old_session", legacy_request))

    assert legacy_response.status_code == 409
    assert json.loads(legacy_response.body)["status"] == "inactive_session"

    historical_request = api_server.AskRequest(question="what happened?", mode="async")
    historical_response = asyncio.run(api_server.ask_historical_session("old_session", historical_request))

    assert historical_response.status_code == 202
    historical_content = json.loads(historical_response.body)
    assert historical_content["status"] == "queued"
    task_id = historical_content["task_id"]
    task_payload = json.loads((project_root / "online_tasks" / "query" / f"{task_id}.json").read_text(encoding="utf-8"))
    assert task_payload["session_id"] == "old_session"
    assert task_payload["allow_inactive_session"] is True
    assert task_payload["task_source"] == "session_history_api"
