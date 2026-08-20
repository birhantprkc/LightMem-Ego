from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from online_llm_config import local_cache_namespace, local_chat_request_kwargs, merge_local_chat_request_kwargs


def test_remote_profile_does_not_add_qwen_parameters(monkeypatch) -> None:
    monkeypatch.delenv("EM2MEM_LOCAL_LLM_ENABLED", raising=False)
    assert local_chat_request_kwargs() == {}


def test_local_profile_disables_qwen_thinking(monkeypatch) -> None:
    monkeypatch.setenv("EM2MEM_LOCAL_LLM_ENABLED", "1")
    assert local_chat_request_kwargs() == {
        "max_tokens": 4096,
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}}
    }


def test_local_parameters_merge_with_existing_extra_body(monkeypatch) -> None:
    monkeypatch.setenv("EM2MEM_LOCAL_LLM_ENABLED", "1")
    merged = merge_local_chat_request_kwargs(
        {"extra_body": {"top_k": 20, "chat_template_kwargs": {"custom": True}}}
    )
    assert merged == {
        "max_tokens": 4096,
        "extra_body": {
            "top_k": 20,
            "chat_template_kwargs": {"custom": True, "enable_thinking": False},
        }
    }


def test_local_cache_namespace_is_separate(monkeypatch) -> None:
    monkeypatch.setenv("EM2MEM_LOCAL_LLM_ENABLED", "1")
    assert local_cache_namespace() == "local_qwen35"
    monkeypatch.setenv("EM2MEM_LOCAL_LLM_CACHE_NAMESPACE", "qwen-override")
    assert local_cache_namespace() == "qwen_override"


def test_local_default_does_not_conflict_with_max_completion_tokens(monkeypatch) -> None:
    monkeypatch.setenv("EM2MEM_LOCAL_LLM_ENABLED", "1")
    merged = merge_local_chat_request_kwargs({"max_completion_tokens": 128})
    assert merged["max_completion_tokens"] == 128
    assert "max_tokens" not in merged
