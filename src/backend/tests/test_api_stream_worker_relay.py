import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import api_server
from online_preprocess.io_utils import read_json, write_json_atomic
from online_preprocess.task_queue import ensure_queue_dirs
from online_query.stream_transport import append_query_stream_event, query_stream_events_path


def _parse_sse(chunks: list[str | bytes]) -> list[tuple[str, dict]]:
    events = []
    for chunk in chunks:
        text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
        event_name = "message"
        data = None
        for line in text.splitlines():
            if line.startswith("event: "):
                event_name = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if isinstance(data, dict):
            events.append((event_name, data))
    return events


def test_api_stream_relay_uses_queued_worker_task() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            sessions_root = project_root / "online_sessions"
            sessions_root.mkdir(parents=True)
            dirs = ensure_queue_dirs(project_root)
            request = api_server.AskRequest(question="测试流式查询", response_mode="stream")

            with (
                patch.object(api_server, "PROJECT_ROOT", project_root),
                patch.object(api_server, "ONLINE_SESSIONS_DIR", sessions_root),
            ):
                response = await api_server._ask_streaming_response("session1", request)
                queued = list(dirs["query_queued"].glob("*.json"))
                assert len(queued) == 1
                task = read_json(queued[0], default={})
                task_id = str(task["task_id"])
                assert task["response_mode"] == "stream"
                assert task["priority"] == 0

                append_query_stream_event(
                    query_stream_events_path(project_root, task_id),
                    {"type": "delta", "stage": "answer", "delta": "你好"},
                )
                write_json_atomic(
                    dirs["query_done"] / f"{task_id}.json",
                    {
                        **task,
                        "status": "done",
                        "result": {
                            "status": "ok",
                            "response_mode": "stream",
                            "session_id": "session1",
                            "question": request.question,
                            "answer": "你好",
                        },
                    },
                )

                chunks = [chunk async for chunk in response.body_iterator]
                events = _parse_sse(chunks)
                assert [event for event, _ in events] == ["start", "delta", "done"]
                assert events[0][1]["query_process"] == "query_worker"
                assert events[1][1]["delta"] == "你好"
                assert events[2][1]["result"]["answer"] == "你好"
                assert not query_stream_events_path(project_root, task_id).exists()

    asyncio.run(run())
