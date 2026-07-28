from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from online_pipeline.runtime_state import WorkerTaskHeartbeat, get_pipeline_mode, refresh_session_pipeline_state, write_worker_runtime
from online_pipeline.stream_timeline import append_timeline_event
from online_preprocess.asr_whisperx import WhisperXRuntime
from online_preprocess.io_utils import read_json
from online_preprocess.task_queue import (
    claim_stream_asr_task,
    finish_stream_asr_task,
    list_queued_stream_asr_tasks,
)
from online_streaming.stream_asr_processor import mark_stream_asr_failed, process_stream_asr_task


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_SESSIONS_ROOT = PROJECT_ROOT / "online_sessions"
DEFAULT_WHISPERX_MODEL_DIR = PROJECT_ROOT / "models" / "whisperx"
DEFAULT_WHISPERX_ALIGN_MODEL_DIR = DEFAULT_WHISPERX_MODEL_DIR / "alignment"


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _split_languages(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _normalize_asr_backend(value: str | None, default: str = "xfyun") -> str:
    backend = (value or default).strip().lower()
    return "xfyun" if backend == "iflytek" else backend


def _voice_question_backend() -> str:
    return _normalize_asr_backend(os.getenv("EM2MEM_VOICE_QUESTION_ASR_BACKEND"), "whisperx")


def _normalize_task_filter(value: str | None) -> str:
    task_filter = str(value or "all").strip().lower()
    if task_filter in {"voice", "voice_question", "voice-question", "voice_questions", "voice-question-only"}:
        return "voice_question"
    if task_filter in {"stream", "stream_asr", "normal", "background", "non_voice_question"}:
        return "stream"
    return "all"


def _is_voice_question_task(task: dict) -> bool:
    source = str(task.get("source") or "").strip().lower()
    reason = str(task.get("reason") or "").strip().lower()
    return source == "voice_question" or reason == "voice_question"


def _task_matches_filter(task: dict, task_filter: str) -> bool:
    normalized_filter = _normalize_task_filter(task_filter)
    if normalized_filter == "all":
        return True
    is_voice_question = _is_voice_question_task(task)
    if normalized_filter == "voice_question":
        return is_voice_question
    if normalized_filter == "stream":
        return not is_voice_question
    return True


def run_worker(args: argparse.Namespace) -> None:
    project_root = Path(args.project_root).resolve()
    sessions_root = Path(args.sessions_root).resolve()
    worker_name = args.worker_name
    task_filter = _normalize_task_filter(args.task_filter)

    runtime = WhisperXRuntime(
        model_name=args.whisperx_model,
        device=args.device,
        compute_type=args.compute_type,
        model_dir=args.model_dir,
        align_model_dir=args.align_model_dir,
        preload_align_languages=_split_languages(args.preload_align_languages),
    )

    stream_asr_processed_count = 0
    last_stream_asr_task_id: str | None = None
    last_stream_asr_session_id: str | None = None
    last_stream_asr_error: str | None = None

    def _backend_for_task(task: dict) -> str:
        source = str(task.get("source") or "")
        if source == "audio_chunk_window":
            return _normalize_asr_backend(os.getenv("EM2MEM_AUDIO_ASR_BACKEND") or str(task.get("asr_backend") or ""), "xfyun")
        if source == "voice_question":
            return _normalize_asr_backend(os.getenv("EM2MEM_VOICE_QUESTION_ASR_BACKEND") or str(task.get("asr_backend") or ""), "whisperx")
        return _normalize_asr_backend(os.getenv("EM2MEM_STREAM_ASR_BACKEND") or str(task.get("asr_backend") or ""), "xfyun")

    def _default_status_backend() -> str:
        if task_filter == "voice_question":
            return _voice_question_backend()
        if task_filter == "stream":
            return _normalize_asr_backend(os.getenv("EM2MEM_STREAM_ASR_BACKEND"), "xfyun")
        return _voice_question_backend()

    def _runtime_model_loaded() -> bool:
        return runtime.asr_model is not None

    def _status_model_name(asr_backend: str | None = None) -> str:
        return _normalize_asr_backend(asr_backend or _default_status_backend(), "whisperx")

    def _status_model_path(asr_backend: str | None = None) -> str:
        return str(args.model_dir) if _status_model_name(asr_backend) == "whisperx" else ""

    def _status_device(asr_backend: str | None = None) -> str:
        return runtime.device if _status_model_name(asr_backend) == "whisperx" or _runtime_model_loaded() else "api"

    def _list_worker_stream_asr_tasks() -> list[Path]:
        tasks = list_queued_stream_asr_tasks(project_root)
        if task_filter == "all":
            return tasks
        matched: list[Path] = []
        for task_path in tasks:
            task = read_json(task_path, default={})
            if isinstance(task, dict) and _task_matches_filter(task, task_filter):
                matched.append(task_path)
        return matched

    def _queue_pending() -> int:
        return len(_list_worker_stream_asr_tasks())

    def _runtime_extra(session_id: str | None = None, asr_backend: str | None = None) -> dict:
        total_pending = len(list_queued_stream_asr_tasks(project_root))
        worker_pending = _queue_pending()
        extra = {
            "asr_backend": _status_model_name(asr_backend),
            "stream_asr_backend": _normalize_asr_backend(os.getenv("EM2MEM_STREAM_ASR_BACKEND"), "xfyun"),
            "audio_asr_backend": _normalize_asr_backend(os.getenv("EM2MEM_AUDIO_ASR_BACKEND"), "xfyun"),
            "voice_question_asr_backend": _voice_question_backend(),
            "task_filter": task_filter,
            "whisperx_model": args.whisperx_model,
            "compute_type": runtime.compute_type,
            "preload_align_languages": args.preload_align_languages,
            "whisperx_loaded": _runtime_model_loaded(),
            "pipeline_mode": get_pipeline_mode(),
            "stream_asr_enabled": _env_bool("EM2MEM_STREAM_ASR_ENABLED", True),
            "stream_asr_queue_pending": worker_pending,
            "stream_asr_queue_pending_total": total_pending,
            "stream_asr_processed_count": stream_asr_processed_count,
            "last_stream_asr_task_id": last_stream_asr_task_id,
            "last_stream_asr_session_id": last_stream_asr_session_id,
            "last_stream_asr_error": last_stream_asr_error,
        }
        if session_id:
            extra["session_id"] = session_id
        return extra

    if task_filter == "voice_question":
        configured_backends = {_voice_question_backend()}
    elif task_filter == "stream":
        configured_backends = {
            _normalize_asr_backend(os.getenv("EM2MEM_STREAM_ASR_BACKEND"), "xfyun"),
            _normalize_asr_backend(os.getenv("EM2MEM_AUDIO_ASR_BACKEND"), "xfyun"),
        }
    else:
        configured_backends = {
            _normalize_asr_backend(os.getenv("EM2MEM_STREAM_ASR_BACKEND"), "xfyun"),
            _normalize_asr_backend(os.getenv("EM2MEM_AUDIO_ASR_BACKEND"), "xfyun"),
            _voice_question_backend(),
        }
    if _env_bool("EM2MEM_WHISPERX_PRELOAD", True) and "whisperx" in configured_backends:
        print("[asr_worker] preloading WhisperX runtime", flush=True)
        runtime.load()
        print("[asr_worker] WhisperX runtime preloaded", flush=True)

    write_worker_runtime(
        project_root,
        worker_name,
        status="ready",
        model_name=_status_model_name(),
        model_path=_status_model_path(),
        device=_status_device(),
        model_loaded=_runtime_model_loaded(),
        warmup_done=_runtime_model_loaded(),
        queue_pending=_queue_pending(),
        extra=_runtime_extra(),
    )
    print(
        "ASR worker ready:",
        f"task_filter={task_filter}",
        f"stream_backend={_normalize_asr_backend(os.getenv('EM2MEM_STREAM_ASR_BACKEND'), 'xfyun')}",
        f"audio_backend={_normalize_asr_backend(os.getenv('EM2MEM_AUDIO_ASR_BACKEND'), 'xfyun')}",
        f"voice_question_backend={_voice_question_backend()}",
        f"whisperx_loaded={_runtime_model_loaded()}",
        flush=True,
    )

    while True:
        stream_asr_tasks = _list_worker_stream_asr_tasks() if _env_bool("EM2MEM_STREAM_ASR_ENABLED", True) else []
        if not stream_asr_tasks:
            write_worker_runtime(
                project_root,
                worker_name,
                status="ready",
                model_name=_status_model_name(),
                model_path=_status_model_path(),
                device=_status_device(),
                model_loaded=_runtime_model_loaded(),
                warmup_done=_runtime_model_loaded(),
                queue_pending=0,
                extra=_runtime_extra(),
            )
            if args.once:
                return
            time.sleep(args.poll_interval)
            continue

        for task_path in stream_asr_tasks:
            claimed = claim_stream_asr_task(project_root, task_path)
            if claimed is None:
                continue
            claimed_path, task = claimed
            session_id = str(task.get("session_id") or "")
            task_id = str(task.get("task_id") or claimed_path.stem)
            asr_backend = _backend_for_task(task)
            last_stream_asr_task_id = task_id
            last_stream_asr_session_id = session_id
            try:
                append_timeline_event(
                    sessions_root / session_id,
                    "asr_started",
                    chunk_index=int(task.get("upload_chunk_index", -1)),
                    chunk_id=str(task.get("upload_chunk_id") or ""),
                    metadata={"task_id": task_id, "backend": asr_backend, "worker": worker_name},
                )
                write_worker_runtime(
                    project_root,
                    worker_name,
                    status="busy_stream_asr",
                    model_name=_status_model_name(asr_backend),
                    model_path=_status_model_path(asr_backend),
                    device=_status_device(asr_backend),
                    model_loaded=_runtime_model_loaded(),
                    warmup_done=_runtime_model_loaded(),
                    queue_pending=_queue_pending(),
                    last_task_id=task_id,
                    extra={**_runtime_extra(session_id, asr_backend), "last_stream_asr_error": None},
                )
                with WorkerTaskHeartbeat(
                    project_root,
                    worker_name,
                    task=task,
                    claimed_path=claimed_path,
                    status="busy_stream_asr",
                    model_name=_status_model_name(asr_backend),
                    model_path=_status_model_path(asr_backend),
                    device=_status_device(asr_backend),
                    model_loaded=_runtime_model_loaded(),
                    warmup_done=_runtime_model_loaded(),
                    queue_pending=_queue_pending,
                    extra_fn=lambda session_id=session_id, asr_backend=asr_backend: _runtime_extra(session_id, asr_backend),
                    interval_env="EM2MEM_ASR_HEARTBEAT_SECONDS",
                ):
                    result = process_stream_asr_task(
                        project_root=project_root,
                        sessions_root=sessions_root,
                        task=task,
                        asr_runtime=runtime,
                        whisperx_model=args.whisperx_model,
                        device=args.device,
                        compute_type=args.compute_type,
                        language=args.language,
                        model_dir=args.model_dir,
                        align_model_dir=args.align_model_dir,
                        force=bool(task.get("force", False)),
                    )
                finish_stream_asr_task(project_root, claimed_path, task, status="done", result=result)
                append_timeline_event(
                    sessions_root / session_id,
                    "asr_done",
                    chunk_index=int(task.get("upload_chunk_index", -1)),
                    chunk_id=str(task.get("upload_chunk_id") or ""),
                    metadata={
                        "task_id": task_id,
                        "backend": result.get("backend"),
                        "requested_backend": result.get("requested_backend"),
                        "segment_count": result.get("segment_count"),
                        "no_audio": result.get("no_audio"),
                        "worker": worker_name,
                    },
                )
                append_timeline_event(
                    sessions_root / session_id,
                    "transcript_backfilled",
                    chunk_index=int(task.get("upload_chunk_index", -1)),
                    chunk_id=str(task.get("upload_chunk_id") or ""),
                    metadata=result.get("backfill") if isinstance(result.get("backfill"), dict) else {},
                )
                stream_asr_processed_count += 1
                last_stream_asr_error = None
                refresh_session_pipeline_state(sessions_root / session_id)
            except Exception as exc:
                last_stream_asr_error = str(exc)
                mark_stream_asr_failed(sessions_root, task, str(exc))
                append_timeline_event(
                    sessions_root / session_id,
                    "error",
                    chunk_index=int(task.get("upload_chunk_index", -1)),
                    chunk_id=str(task.get("upload_chunk_id") or ""),
                    metadata={"stage": "stream_asr", "task_id": task_id, "error": str(exc), "worker": worker_name},
                )
                finish_stream_asr_task(project_root, claimed_path, task, status="failed", error=str(exc))
                write_worker_runtime(
                    project_root,
                    worker_name,
                    status="error",
                    model_name=_status_model_name(asr_backend),
                    model_path=_status_model_path(asr_backend),
                    device=_status_device(asr_backend),
                    model_loaded=_runtime_model_loaded(),
                    warmup_done=_runtime_model_loaded(),
                    queue_pending=_queue_pending(),
                    last_task_id=task_id,
                    last_error=str(exc),
                    extra=_runtime_extra(session_id, asr_backend),
                )
            if args.once:
                return
            break


def main() -> None:
    parser = argparse.ArgumentParser(description="Dedicated online ASR worker for stream and voice-question transcription tasks.")
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--sessions-root", default=str(DEFAULT_SESSIONS_ROOT))
    parser.add_argument("--worker-name", default=os.getenv("EM2MEM_ASR_WORKER_NAME", "asr"))
    parser.add_argument("--whisperx-model", default=os.getenv("EM2MEM_WHISPERX_MODEL", "medium"))
    parser.add_argument("--device", default=os.getenv("EM2MEM_WHISPERX_DEVICE", "cuda"))
    parser.add_argument("--compute-type", default=os.getenv("EM2MEM_WHISPERX_COMPUTE_TYPE", "float16"))
    parser.add_argument("--language", default=os.getenv("EM2MEM_WHISPERX_LANGUAGE") or None)
    parser.add_argument("--model-dir", default=os.getenv("EM2MEM_WHISPERX_MODEL_DIR", str(DEFAULT_WHISPERX_MODEL_DIR)))
    parser.add_argument(
        "--align-model-dir",
        default=os.getenv("EM2MEM_WHISPERX_ALIGN_MODEL_DIR", str(DEFAULT_WHISPERX_ALIGN_MODEL_DIR)),
    )
    parser.add_argument("--preload-align-languages", default=os.getenv("EM2MEM_WHISPERX_ALIGN_LANGS", "zh,en"))
    parser.add_argument("--task-filter", default=os.getenv("EM2MEM_ASR_TASK_FILTER", "all"))
    parser.add_argument("--poll-interval", type=float, default=float(os.getenv("EM2MEM_ASR_POLL_INTERVAL", "0.5") or 0.5))
    parser.add_argument("--once", action="store_true")
    run_worker(parser.parse_args())


if __name__ == "__main__":
    main()
