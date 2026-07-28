import threading
import time
from concurrent.futures import ThreadPoolExecutor

from online_query.query_cache import SessionEngineCache


class _FakeEngine:
    def __init__(self) -> None:
        self.last_accessed_at = time.time()
        self.closed = False

    def needs_reload(self) -> bool:
        return False

    def touch(self) -> None:
        self.last_accessed_at = time.time()

    def close(self) -> None:
        self.closed = True


def test_get_or_load_singleflight_per_session() -> None:
    cache = SessionEngineCache(max_sessions=2, ttl_seconds=3600)
    barrier = threading.Barrier(4)
    call_count = 0
    call_lock = threading.Lock()

    def loader(_session_id: str) -> _FakeEngine:
        nonlocal call_count
        with call_lock:
            call_count += 1
        time.sleep(0.1)
        return _FakeEngine()

    def load() -> tuple[_FakeEngine, bool, int]:
        barrier.wait()
        return cache.get_or_load(
            session_id="session1",
            long_term_retrieval_scheme="em2memory",
            loader=loader,
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: load(), range(4)))

    assert call_count == 1
    assert len({id(result[0]) for result in results}) == 1
    assert sum(1 for _, cache_hit, _ in results if not cache_hit) == 1
    assert sum(1 for _, cache_hit, _ in results if cache_hit) == 3
