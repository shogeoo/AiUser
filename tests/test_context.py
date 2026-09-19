"""Tests for conversation context persistence."""

import json

import pytest

import src.agent.context as context_module
from src.agent.context import ContextManager


@pytest.fixture
def context_path(tmp_path, monkeypatch):
    path = tmp_path / "context.json"
    monkeypatch.setattr(context_module, "CONTEXT_FILE_PATH", path)
    return path


def test_history_roundtrip(context_path):
    manager = ContextManager("system")
    manager.add_user_message("hello")
    manager.add_model_message('{"actions": []}')

    restored = ContextManager("system")

    assert [message["role"] for message in restored.history] == ["user", "assistant"]
    assert restored.history[0]["content"] == "hello"


def test_legacy_model_role_is_mapped_to_assistant(context_path):
    context_path.write_text(json.dumps([{"role": "model", "content": "old"}]), encoding="utf-8")

    manager = ContextManager("system")

    assert manager.history[0]["role"] == "assistant"


def test_multimodal_message_persists_only_text(context_path):
    manager = ContextManager("system")
    manager.add_user_message("caption", file_parts=[{"type": "image_url", "image_url": {"url": "data:x"}}])

    data = json.loads(context_path.read_text(encoding="utf-8"))

    assert data == [{"role": "user", "content": "caption"}]


def test_get_messages_includes_system_prompt(context_path):
    manager = ContextManager("system prompt")
    manager.add_user_message("hi")

    messages = manager.get_messages()

    assert messages[0] == {"role": "system", "content": "system prompt"}
    assert messages[1]["role"] == "user"
