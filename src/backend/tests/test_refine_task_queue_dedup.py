from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from online_preprocess.task_queue import claim_mst_refine_task, enqueue_mst_refine_task


def test_concurrent_enqueue_reuses_one_refine_task() -> None:
    with TemporaryDirectory() as temp_dir:
        project_root = Path(temp_dir)

        def enqueue() -> Path:
            return enqueue_mst_refine_task(
                project_root=project_root,
                session_id="session1",
                backend="mock",
                limit_events=10,
                event_ids=["event1", "event2"],
                force_refine=False,
                reason="frame_stream_batch",
            )

        with ThreadPoolExecutor(max_workers=4) as executor:
            paths = list(executor.map(lambda _: enqueue(), range(4)))

        assert len({path.name for path in paths}) == 1
        queued = list((project_root / "online_tasks" / "mst_refine").glob("*.json"))
        assert len(queued) == 1


def test_concurrent_claim_returns_one_winner_without_error() -> None:
    with TemporaryDirectory() as temp_dir:
        project_root = Path(temp_dir)
        task_path = enqueue_mst_refine_task(
            project_root=project_root,
            session_id="session1",
            backend="mock",
            limit_events=1,
            event_id="event1",
            reason="frame_stream_batch",
        )

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(
                executor.map(
                    lambda _: claim_mst_refine_task(project_root, task_path),
                    range(4),
                )
            )

        winners = [result for result in results if result is not None]
        assert len(winners) == 1
        assert winners[0][0].parent.name == "mst_refine_in_progress"
