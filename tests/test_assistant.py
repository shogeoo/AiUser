"""Tests for the agent loop: action ids, chronological flush and turn control."""

import asyncio
import json

from src.assistant import TelegramAIAssistant
from src.buffer import EventBuffer


class FakeContext:
    def __init__(self, history=None):
        self.history = history or []
        self.messages = []

    def add_user_message(self, text, file_parts=None):
        self.messages.append((text, file_parts))


def make_assistant(history=None):
    assistant = TelegramAIAssistant.__new__(TelegramAIAssistant)
    assistant.context_mgr = FakeContext(history)
    assistant.event_buffer = EventBuffer(lambda events: asyncio.sleep(0))
    assistant._pending_results = []
    assistant._seq = 0
    assistant._action_counter = 0
    assistant._init_action_counter()
    return assistant


def test_action_ids_are_sequential():
    assistant = make_assistant()
    actions = [{"id": "x"}, {"id": "y"}, {}]

    assistant._assign_action_ids(actions)

    assert [action["id"] for action in actions] == ["a000001", "a000002", "a000003"]


def test_action_counter_is_restored_from_history():
    history = [
        {"role": "assistant", "content": json.dumps({"actions": [{"id": "a000004"}]})},
        {"role": "user", "content": json.dumps({"type": "action_result", "data": {"id": "a000002"}})},
    ]

    assistant = make_assistant(history)

    assert assistant._action_counter == 4


def test_flush_pending_keeps_chronological_order():
    assistant = make_assistant()
    assistant.event_buffer.buffer.append((1, {"type": "event", "data": {"n": 1}}))
    assistant._pending_results.append((2, {"type": "action_result", "data": {"id": "a000001"}}, []))
    assistant.event_buffer.buffer.append((3, {"type": "event", "data": {"n": 2}}))

    assistant._flush_pending()

    types = [json.loads(text)["type"] for text, _ in assistant.context_mgr.messages]
    assert types == ["event", "action_result", "event"]
    assert assistant._has_pending() is False


def test_flush_pending_attaches_files_to_result_message():
    assistant = make_assistant()
    attachment = {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,x"}}
    assistant._pending_results.append((1, {"type": "action_result", "data": {"id": "a000001"}}, [attachment]))

    assistant._flush_pending()

    _, file_parts = assistant.context_mgr.messages[0]
    assert file_parts == [attachment]


async def test_agent_turn_stops_on_empty_actions():
    assistant = make_assistant()
    calls = []

    async def request_actions():
        calls.append("request")
        return []

    assistant._request_actions = request_actions
    assistant.executor = None
    assistant.event_buffer.buffer.append((1, {"type": "event", "data": {}}))

    await assistant._agent_turn()

    assert calls == ["request"]
    assert len(assistant.context_mgr.messages) == 1


async def test_agent_turn_executes_actions_and_publishes_results():
    assistant = make_assistant()
    responses = [[{"id": "x", "type": "get_me", "data": {}}], []]

    async def request_actions():
        return responses.pop(0)

    class FakeExecutor:
        async def execute_actions(self, actions, on_result=None):
            if on_result:
                on_result({"type": "action_result", "data": {"id": "a000001", "status": "success", "result": None}}, [])
            return [], []

    assistant._request_actions = request_actions
    assistant.executor = FakeExecutor()

    await assistant._agent_turn()

    types = [json.loads(text)["type"] for text, _ in assistant.context_mgr.messages]
    assert types == ["action_result"]


async def test_agent_turn_continues_when_new_events_arrive():
    assistant = make_assistant()
    calls = {"count": 0}

    async def request_actions():
        calls["count"] += 1
        if calls["count"] == 1:
            assistant.event_buffer.buffer.append((assistant._next_seq(), {"type": "event", "data": {"late": True}}))
        return []

    assistant._request_actions = request_actions

    await assistant._agent_turn()

    assert calls["count"] == 2
    types = [json.loads(text)["type"] for text, _ in assistant.context_mgr.messages]
    assert types == ["event"]
