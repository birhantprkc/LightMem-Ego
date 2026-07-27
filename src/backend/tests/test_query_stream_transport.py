from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from online_query.stream_transport import (
    QueryStreamEventWriter,
    read_query_stream_events,
)


def test_stream_event_transport_handles_concurrent_appends() -> None:
    with TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "events.jsonl"
        writer = QueryStreamEventWriter(path)

        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(lambda index: writer({"type": "delta", "index": index}), range(20)))

        events, offset, pending = read_query_stream_events(path)
        assert offset == path.stat().st_size
        assert pending == b""
        assert sorted(event["index"] for event in events) == list(range(20))


def test_stream_event_transport_retains_partial_line() -> None:
    with TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "events.jsonl"
        path.write_bytes(b'{"type":"delta","delta":"a"}\n{"type":"delta"')

        events, offset, pending = read_query_stream_events(path)
        assert events == [{"type": "delta", "delta": "a"}]
        assert pending == b'{"type":"delta"'

        with path.open("ab") as handle:
            handle.write(b',"delta":"b"}\n')
        events, offset, pending = read_query_stream_events(path, offset=offset, pending=pending)
        assert events == [{"type": "delta", "delta": "b"}]
        assert pending == b""
