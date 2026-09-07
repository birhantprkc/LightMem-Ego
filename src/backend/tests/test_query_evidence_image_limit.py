from pathlib import Path

from online_query.evidence_packer import EvidencePacker


def _frame(path: str, segment_id: str, timestamp: float) -> dict:
    return {
        "path": path,
        "segment_id": segment_id,
        "canonical_segment_id": segment_id,
        "timestamp": timestamp,
        "score": 1.0,
    }


def test_evidence_packer_caps_total_images_across_evidence(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EM2MEM_IMAGES_PER_EVIDENCE_LIMIT", "3")
    monkeypatch.setenv("EM2MEM_QUERY_MAX_TOTAL_IMAGES", "9")
    paths = [f"current/frame_{index}.jpg" for index in range(16)]
    for path in paths:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()

    result = EvidencePacker(session_dir=tmp_path).pack(
        query="what happened?",
        route_decision={
            "use_image_evidence": True,
            "max_image_evidence": 9,
            "text_top_k": 5,
            "final_evidence_k": 4,
        },
        retrieval_result={
            "evidence_frames": [
                _frame(path, f"evidence-{index // 4}", index * 2.0)
                for index, path in enumerate(paths)
            ]
        },
    )

    selected = result["selected_image_paths_for_mllm"]
    selected_per_evidence: dict[int, int] = {}
    for path in selected:
        frame_index = int(Path(path).stem.rsplit("_", 1)[1])
        evidence_id = frame_index // 4
        selected_per_evidence[evidence_id] = selected_per_evidence.get(evidence_id, 0) + 1
    assert len(selected) == 9
    assert all(count <= 3 for count in selected_per_evidence.values())
    assert result["evidence_pack_summary"]["per_evidence_image_limit"] == 3
    assert result["evidence_pack_summary"]["total_image_limit"] == 9
    assert result["evidence_pack_summary"]["sent_image_count"] == 9


def test_evidence_packer_honors_smaller_request_limit(monkeypatch) -> None:
    monkeypatch.setenv("EM2MEM_IMAGES_PER_EVIDENCE_LIMIT", "3")
    monkeypatch.setenv("EM2MEM_QUERY_MAX_TOTAL_IMAGES", "9")
    result = EvidencePacker().pack(
        query="what happened?",
        route_decision={
            "use_image_evidence": True,
            "max_image_evidence": 4,
            "text_top_k": 5,
            "final_evidence_k": 4,
        },
        retrieval_result={
            "evidence_frames": [
                _frame(f"frame_{index}.jpg", f"evidence-{index // 3}", index * 2.0)
                for index in range(9)
            ]
        },
    )

    assert len(result["selected_image_paths_for_mllm"]) == 4
    assert result["evidence_pack_summary"]["total_image_limit"] == 4
