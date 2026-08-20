from __future__ import annotations

import argparse
import json
import sys
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from online_pipeline.audio_stream import AudioStreamStore
from online_pipeline.realtime_ingest import ingest_audio_chunk
from online_pipeline.rokid_ingest import ROKID_INPUT_MODE, initialize_rokid_state
from online_preprocess.io_utils import read_json, utc_now_iso, write_json_atomic, write_status
from online_short_term.stream_chunk_manager import StreamChunkManager


ONLINE_SESSIONS_DIR = PROJECT_ROOT / "online_sessions"


def parse_iso(value: Any) -> float | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        return None


def wav_duration_ms(path: Path) -> int:
    with wave.open(str(path), "rb") as handle:
        frames = handle.getnframes()
        rate = handle.getframerate()
    return int(round(frames * 1000.0 / rate))


def create_minimal_rokid_session(metadata: dict[str, Any], chunk_duration: float) -> tuple[str, Path, str]:
    session_id = uuid4().hex[:12]
    session_dir = ONLINE_SESSIONS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=False)
    metadata_payload = {
        "session_id": session_id,
        "source": "rokid_internal_audio_speed_test",
        "original_filename": None,
        "saved_video_path": str(session_dir / "input.mp4"),
        "size_bytes": 0,
        "upload_time": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata,
    }
    write_json_atomic(session_dir / "metadata.json", metadata_payload)
    write_status(
        session_dir=session_dir,
        session_id=session_id,
        status="streaming",
        stage="stream_started",
        progress=0,
        error=None,
    )
    manager = StreamChunkManager(session_dir)
    stream_state = manager.init_stream(chunk_duration=chunk_duration, metadata=metadata, reset=False)

    def set_rokid_state(state: dict[str, Any]) -> None:
        state["input_mode"] = ROKID_INPUT_MODE
        state.setdefault("metadata", {}).update(metadata)

    stream_state, _ = manager.update_stream_state_locked(set_rokid_state)
    stream_id = str(stream_state.get("stream_id") or "")
    AudioStreamStore(session_dir).initialize(stream_id=stream_id, input_mode=ROKID_INPUT_MODE)
    initialize_rokid_state(session_dir, stream_id=stream_id, metadata=metadata, input_mode=ROKID_INPUT_MODE)
    return session_id, session_dir, stream_id


def list_task_files(project_root: Path, session_id: str) -> list[Path]:
    root = project_root / "online_tasks"
    paths: list[Path] = []
    for dirname in ("stream_asr", "stream_asr_in_progress", "stream_asr_done", "stream_asr_failed"):
        paths.extend(sorted((root / dirname).glob(f"{session_id}_*.json")))
    return paths


def collect_state(project_root: Path, session_id: str) -> dict[str, Any]:
    session_dir = project_root / "online_sessions" / session_id
    asr_state = read_json(session_dir / "stream" / "audio_asr_state.json", default={})
    audio_state = read_json(session_dir / "stream" / "audio_state.json", default={})
    transcript_state = read_json(session_dir / "stream" / "transcript" / "partial_transcript_state.json", default={})
    tasks = []
    for path in list_task_files(project_root, session_id):
        payload = read_json(path, default={})
        if isinstance(payload, dict) and payload.get("source") == "audio_chunk_window":
            tasks.append({**payload, "_path": str(path.relative_to(project_root))})
    return {
        "audio_state": audio_state if isinstance(audio_state, dict) else {},
        "asr_state": asr_state if isinstance(asr_state, dict) else {},
        "transcript_state": transcript_state if isinstance(transcript_state, dict) else {},
        "tasks": tasks,
    }


def summarize_tasks(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for task in tasks:
        created = parse_iso(task.get("created_at"))
        claimed = parse_iso(task.get("claimed_at"))
        updated = parse_iso(task.get("updated_at"))
        result = task.get("result") if isinstance(task.get("result"), dict) else {}
        rows.append(
            {
                "task_id": task.get("task_id"),
                "window_id": task.get("window_id"),
                "status": task.get("status"),
                "window_duration_ms": task.get("duration_ms"),
                "segment_count": result.get("segment_count"),
                "no_audio": result.get("no_audio"),
                "queue_wait_s": round(claimed - created, 3) if created is not None and claimed is not None else None,
                "worker_process_s": round(updated - claimed, 3) if updated is not None and claimed is not None else None,
                "task_total_s": round(updated - created, 3) if updated is not None and created is not None else None,
                "path": task.get("_path"),
            }
        )
    done = [row for row in rows if row["status"] == "done" and row["worker_process_s"] is not None]
    worker_times = [float(row["worker_process_s"]) for row in done]
    queue_times = [float(row["queue_wait_s"]) for row in done if row["queue_wait_s"] is not None]
    audio_seconds = sum(float(row.get("window_duration_ms") or 0) / 1000.0 for row in done)
    process_seconds = sum(worker_times)
    return {
        "task_count": len(rows),
        "done_count": len(done),
        "failed_count": len([row for row in rows if row["status"] == "failed"]),
        "audio_seconds_done": round(audio_seconds, 3),
        "worker_process_seconds_sum": round(process_seconds, 3),
        "realtime_factor_worker_sum": round(process_seconds / audio_seconds, 3) if audio_seconds else None,
        "avg_worker_process_s": round(sum(worker_times) / len(worker_times), 3) if worker_times else None,
        "max_worker_process_s": round(max(worker_times), 3) if worker_times else None,
        "avg_queue_wait_s": round(sum(queue_times) / len(queue_times), 3) if queue_times else None,
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Internally ingest Rokid-style WAV chunks and measure WhisperX ASR worker speed.")
    parser.add_argument("--audio-dir", required=True)
    parser.add_argument("--pattern", default="rokid-audio-*.wav")
    parser.add_argument("--sleep-between", type=float, default=-1.0, help="Seconds between ingests. Negative means use WAV duration.")
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    audio_dir = Path(args.audio_dir).resolve()
    audio_paths = sorted(audio_dir.glob(args.pattern))
    if not audio_paths:
        raise SystemExit(f"No WAV chunks found in {audio_dir} matching {args.pattern}")

    run_id = "whisperx_internal_clothes_" + datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    metadata = {
        "source": "rokid_glass",
        "device_type": "rokid",
        "transport": "http_frame_audio",
        "sdk": "android_camera_x_audio_record",
        "input_mode": ROKID_INPUT_MODE,
        "test_name": "clothes_camera_like_av_whisperx_speed_internal",
        "run_id": run_id,
        "created_by": "rokid_audio_whisperx_speed_internal.py",
    }
    session_id, session_dir, stream_id = create_minimal_rokid_session(metadata, chunk_duration=4.0)
    print(f"[start] session_id={session_id} stream_id={stream_id} run_id={run_id}", flush=True)

    started = time.monotonic()
    ingests = []
    relative_ts_ms = 0
    for index, path in enumerate(audio_paths):
        duration_ms = wav_duration_ms(path)
        before = time.monotonic()
        result = ingest_audio_chunk(
            PROJECT_ROOT,
            session_id,
            path.read_bytes(),
            audio_index=index,
            client_ts_ms=int(time.time() * 1000),
            relative_ts_ms=relative_ts_ms,
            timestamp_source="connector_relative_ts_ms",
            duration_ms=duration_ms,
            sample_rate=16000,
            channels=1,
            format="wav",
            content_type="audio/wav",
            source="rokid_sdk_audio",
            input_mode=ROKID_INPUT_MODE,
            filename_hint=path.name,
            enqueue_asr=True,
            allow_live_input=True,
        )
        elapsed = time.monotonic() - before
        print(f"[ingest] index={index:03d} duration_ms={duration_ms} elapsed_s={elapsed:.3f} status={result.get('status')}", flush=True)
        ingests.append(
            {
                "audio_index": index,
                "file": path.name,
                "duration_ms": duration_ms,
                "relative_ts_ms": relative_ts_ms,
                "ingest_elapsed_s": round(elapsed, 3),
                "result": result,
            }
        )
        relative_ts_ms += duration_ms
        sleep_for = duration_ms / 1000.0 if args.sleep_between < 0 else args.sleep_between
        if index != len(audio_paths) - 1 and sleep_for > 0:
            time.sleep(sleep_for)

    expected_windows = len(audio_paths)
    deadline = time.monotonic() + args.timeout
    last_line = ""
    while time.monotonic() < deadline:
        state = collect_state(PROJECT_ROOT, session_id)
        asr_state = state["asr_state"]
        completed = int(asr_state.get("completed_window_count", asr_state.get("asr_windows_completed", 0)) or 0)
        failed = int(asr_state.get("failed_window_count", asr_state.get("asr_windows_failed", 0)) or 0)
        pending = int(asr_state.get("pending_window_count", 0) or 0)
        enqueued = int(asr_state.get("queued_window_count", asr_state.get("asr_windows_enqueued", 0)) or 0)
        line = f"[poll] enqueued={enqueued} completed={completed} failed={failed} pending={pending} status={asr_state.get('asr_status')}"
        if line != last_line:
            print(line, flush=True)
            last_line = line
        if completed + failed >= expected_windows:
            break
        time.sleep(args.poll_interval)

    state = collect_state(PROJECT_ROOT, session_id)
    summary = summarize_tasks(state["tasks"])
    result = {
        "created_at": utc_now_iso(),
        "run_id": run_id,
        "session_id": session_id,
        "stream_id": stream_id,
        "session_dir": str(session_dir),
        "audio_dir": str(audio_dir),
        "audio_chunk_count": len(audio_paths),
        "uploaded_audio_seconds": round(sum(item["duration_ms"] for item in ingests) / 1000.0, 3),
        "wall_seconds": round(time.monotonic() - started, 3),
        "ingests": ingests,
        "final_state": state,
        "task_summary": summary,
    }
    output_path = Path(args.output) if args.output else audio_dir / f"{run_id}_result.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[result] wrote {output_path}", flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
