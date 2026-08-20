from online_query.evidence_sufficiency import EvidenceSufficiencyEvaluator, apply_recent_recall_decision


def _event(**overrides):
    event = {
        "event_id": "mst_event_1",
        "score": 0.82,
        "bm25_score": 0.88,
        "lexical_score": 0.80,
        "recency_score": 0.95,
        "status": "refined",
        "caption_source": "refined",
        "event_caption_refined": "I put the cup on the kitchen table.",
        "retrieval_text": "I put the cup on the kitchen table.",
        "transcript": "",
        "keyframes": [{"timestamp": 95.0, "path": "stream/frame.jpg"}],
        "entities": ["cup", "kitchen table"],
        "visual_objects": [{"name": "cup"}, {"name": "kitchen table"}],
        "main_actions": [{"action": "put", "actor": "camera wearer", "objects": ["cup", "kitchen table"]}],
        "state_changes": [{"entity": "cup", "attribute": "position", "after": "on the kitchen table"}],
        "confidence": 0.9,
    }
    event.update(overrides)
    return event


def _evaluate(question: str, events: list[dict], **kwargs):
    return EvidenceSufficiencyEvaluator().evaluate(
        question=question,
        query_type="recent_recall",
        short_term_results=events,
        current_results=[],
        **kwargs,
    )


def test_accepts_direct_refined_location_evidence() -> None:
    decision = _evaluate("Where did I put the cup just now?", [_event()])

    assert decision["sufficient"] is True
    assert decision["decision"] == "use_st"
    assert decision["missing_slots"] == []
    assert decision["supporting_event_ids"] == ["mst_event_1"]


def test_escalates_when_placement_result_is_missing() -> None:
    event = _event(
        event_caption_refined="I carried the cup into the kitchen.",
        retrieval_text="I carried the cup into the kitchen.",
        main_actions=[{"action": "carry", "actor": "camera wearer", "objects": ["cup"]}],
        state_changes=[],
    )

    decision = _evaluate("Where did I put the cup just now?", [event])

    assert decision["sufficient"] is False
    assert decision["decision"] == "escalate_lt"
    assert "placement_action" in decision["missing_slots"]


def test_escalates_when_high_score_evidence_misses_target_entity() -> None:
    event = _event(
        event_caption_refined="I put the phone on the kitchen table.",
        retrieval_text="I put the phone on the kitchen table.",
        entities=["phone", "kitchen table"],
        visual_objects=[{"name": "phone"}, {"name": "kitchen table"}],
        main_actions=[{"action": "put", "actor": "camera wearer", "objects": ["phone", "kitchen table"]}],
        state_changes=[{"entity": "phone", "attribute": "position", "after": "on the kitchen table"}],
        score=0.99,
        bm25_score=0.99,
        lexical_score=0.99,
    )

    decision = _evaluate("Where did I put the cup just now?", [event])

    assert decision["sufficient"] is False
    assert decision["signals"]["target_coverage"] < decision["thresholds"]["target_coverage"]


def test_accepts_direct_chinese_location_evidence() -> None:
    event = _event(
        event_caption_refined="我刚才把杯子放在厨房桌面上。",
        retrieval_text="我刚才把杯子放在厨房桌面上。",
        entities=["杯子", "厨房桌面"],
        visual_objects=[{"name": "杯子"}, {"name": "厨房桌面"}],
        main_actions=[{"action": "放下", "actor": "佩戴者", "objects": ["杯子", "厨房桌面"]}],
        state_changes=[{"entity": "杯子", "attribute": "position", "after": "厨房桌面上"}],
        lexical_score=0.9,
    )

    decision = _evaluate("我刚才把杯子放在哪里了？", [event])

    assert decision["sufficient"] is True


def test_accepts_recent_speech_when_transcript_contains_content() -> None:
    event = _event(
        event_caption_refined='The doctor said: "Take the medicine after dinner."',
        retrieval_text='The doctor said: "Take the medicine after dinner."',
        transcript="Take the medicine after dinner.",
        entities=["doctor"],
        main_actions=[{"action": "speak", "actor": "doctor", "objects": ["medicine after dinner"]}],
        lexical_score=0.9,
    )

    decision = _evaluate("What did the doctor say just now?", [event])

    assert decision["sufficient"] is True
    assert decision["intent"] == "speech"


def test_accepts_direct_recent_action_evidence() -> None:
    event = _event(
        event_caption_refined="I opened the book at the desk.",
        retrieval_text="I opened the book at the desk.",
        entities=["book", "desk"],
        visual_objects=[{"name": "book"}, {"name": "desk"}],
        main_actions=[{"action": "open", "actor": "camera wearer", "objects": ["book"]}],
        lexical_score=0.9,
    )

    decision = _evaluate("What did I do with the book just now?", [event])

    assert decision["sufficient"] is True
    assert decision["intent"] == "event_detail"


def test_escalates_recent_speech_without_transcript_content() -> None:
    event = _event(
        event_caption_refined="I was talking with the doctor.",
        retrieval_text="I was talking with the doctor.",
        transcript="",
        entities=["doctor"],
        main_actions=[{"action": "talk", "actor": "doctor"}],
    )

    decision = _evaluate("What did the doctor say just now?", [event])

    assert decision["sufficient"] is False
    assert "speech_content" in decision["missing_slots"]


def test_aggregate_recent_query_always_escalates() -> None:
    decision = _evaluate("How many times did I pick up the cup recently?", [_event()])

    assert decision["sufficient"] is False
    assert decision["reason"] == "aggregate_or_long_scope_query"


def test_explicit_long_term_override_disables_fast_path() -> None:
    decision = _evaluate("Where did I put the cup just now?", [_event()], explicit_long_term_override=True)

    assert decision["enabled"] is False
    assert decision["sufficient"] is False
    assert decision["reason"] == "explicit_long_term_override"


def test_non_recent_query_type_is_not_evaluated() -> None:
    decision = EvidenceSufficiencyEvaluator().evaluate(
        question="Where is the cup?",
        query_type="entity_tracking",
        short_term_results=[_event()],
    )

    assert decision["enabled"] is False
    assert decision["evaluated"] is False


def test_fast_path_disables_long_term_in_all_route_views() -> None:
    route_decision = {
        "memory_route": {"use_short_term": True, "use_long_term": True},
        "memory_router_decision": {
            "memory_route": {"use_short_term": True, "use_long_term": True},
        },
        "warnings": [],
    }
    retrieval_plan = {"retrieval_plan": {"M_lt": {"enabled": True}}}
    decision = {"evaluated": True, "sufficient": True, "reason": "short_term_evidence_sufficient"}

    applied = apply_recent_recall_decision(route_decision, retrieval_plan, decision)

    assert applied is True
    assert route_decision["memory_route"]["use_long_term"] is False
    assert route_decision["memory_router_decision"]["memory_route"]["use_long_term"] is False
    assert retrieval_plan["retrieval_plan"]["M_lt"]["enabled"] is False
    assert route_decision["recent_recall_fast_path"] is True


def test_insufficient_evidence_keeps_long_term_enabled() -> None:
    route_decision = {
        "memory_route": {"use_short_term": True, "use_long_term": True},
        "memory_router_decision": {
            "memory_route": {"use_short_term": True, "use_long_term": True},
        },
    }
    retrieval_plan = {"retrieval_plan": {"M_lt": {"enabled": True}}}
    decision = {"evaluated": True, "sufficient": False, "reason": "missing_location"}

    applied = apply_recent_recall_decision(route_decision, retrieval_plan, decision)

    assert applied is False
    assert route_decision["memory_route"]["use_long_term"] is True
    assert route_decision["memory_router_decision"]["memory_route"]["use_long_term"] is True
    assert retrieval_plan["retrieval_plan"]["M_lt"]["enabled"] is True
    assert route_decision["recent_recall_escalated_to_long_term"] is True
