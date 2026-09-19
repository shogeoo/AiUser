"""Tests for action execution: high-level, raw, docs and error handling."""

import mimetypes
from contextlib import asynccontextmanager

import pytest
import telethon.utils as tu
from telethon.errors import FloodWaitError
from telethon.tl.types import InputPeerChat

from src.exceptions import ExecutionError
from src.executor import ActionExecutor


class FakeClient:
    """Minimal TelegramClient stand-in that mimics Telethon's request.resolve."""

    def __init__(self):
        self.sent = []
        self.calls = []

    async def send_message(self, entity, message):
        self.calls.append(("send_message", entity, message))
        return {"message": message}

    async def get_me(self):
        return {"ok": True}

    async def get_input_entity(self, peer):
        return InputPeerChat(chat_id=abs(int(peer)))

    async def __call__(self, request):
        await request.resolve(self, tu)
        self.sent.append(request)
        return {"sent": type(request).__name__}

    @asynccontextmanager
    async def action(self, entity, action):
        self.calls.append(("action", entity, action))
        yield


class FlakyClient(FakeClient):
    async def get_me(self):
        raise FloodWaitError(request=None, capture=3)


def build_executor(client=None, modalities=None):
    return ActionExecutor(client or FakeClient(), input_modalities=modalities or {"image", "text"})


async def test_high_level_action_returns_action_result():
    client = FakeClient()
    executor = build_executor(client)

    results, attachments = await executor.execute_actions(
        [
            {"id": "a000001", "type": "send_message", "data": {"entity": 100000001, "message": "hi", "reply_to": None}},
        ]
    )

    assert attachments == []
    entry = results[0]["data"]
    assert entry["status"] == "success"
    assert entry["result"] == {"message": "hi"}
    assert client.calls == [("send_message", 100000001, "hi")]


async def test_unknown_action_type_is_reported():
    executor = build_executor()

    results, _ = await executor.execute_actions([{"id": "a000001", "type": "nope", "data": {}}])

    entry = results[0]["data"]
    assert entry["status"] == "error"
    assert entry["error_type"] == "MethodNotFoundError"


async def test_raw_request_resolves_scalar_entity():
    client = FakeClient()
    executor = build_executor(client)

    results, _ = await executor.execute_actions(
        [
            {
                "id": "a000001",
                "type": "telethon.tl.functions.messages.ExportChatInviteRequest",
                "data": {"peer": -1001234567890},
            },
        ]
    )

    assert results[0]["data"]["status"] == "success"
    sent = client.sent[0]
    assert type(sent.peer).__name__ == "InputPeerChat"
    assert sent.peer.chat_id == 1001234567890


async def test_malformed_envelope_is_rejected_with_hint():
    executor = build_executor()

    results, _ = await executor.execute_actions(
        [
            {
                "id": "a000001",
                "type": "telethon.tl.functions.messages.ExportChatInviteRequest",
                "data": {"peer": {"type": "telethon.tl.types.InputPeerChat", "data those chat_id": 1}},
            },
        ]
    )

    entry = results[0]["data"]
    assert entry["status"] == "error"
    assert "Malformed Telegram DTO envelope" in entry["message"]


async def test_docsearch_and_docfetch_return_api_info():
    executor = build_executor()

    results, _ = await executor.execute_actions(
        [
            {"id": "a000001", "type": "docsearch", "data": {"query": "install sticker set"}},
            {
                "id": "a000002",
                "type": "docfetch",
                "data": {"query": "telethon.tl.functions.messages.InstallStickerSetRequest"},
            },
        ]
    )

    search_result = results[0]["data"]["result"]
    assert search_result["type"] == "api_info"
    assert any(match["api"].endswith("InstallStickerSetRequest") for match in search_result["data"]["matches"])

    fetch_result = results[1]["data"]["result"]
    assert fetch_result["type"] == "api_info"
    assert fetch_result["data"]["api"].endswith("InstallStickerSetRequest")


async def test_rpc_error_is_reported_with_wait_seconds():
    executor = build_executor(FlakyClient())

    results, _ = await executor.execute_actions([{"id": "a000001", "type": "get_me", "data": {}}])

    entry = results[0]["data"]
    assert entry["status"] == "error"
    assert entry["error_type"] == "FloodWaitError"
    assert "retry after 3" in entry["message"]


async def test_action_duration_validation():
    executor = build_executor()

    results, _ = await executor.execute_actions(
        [
            {"id": "a000001", "type": "action", "data": {"entity": 100000001, "action": "typing", "duration": -1}},
        ]
    )

    entry = results[0]["data"]
    assert entry["status"] == "error"
    assert entry["error_type"] == "ArgumentError"


def test_build_file_part_by_modalities(tmp_path):
    executor = build_executor(modalities={"image", "video", "file", "audio"})
    files = {
        "photo.jpg": "image_url",
        "clip.mp4": "video_url",
        "doc.pdf": "file",
        "voice.ogg": "input_audio",
    }

    for name, expected_type in files.items():
        path = tmp_path / name
        path.write_bytes(b"data")
        mime_type, _ = mimetypes.guess_type(name)
        part = executor._build_file_part(str(path), mime_type)
        assert part["type"] == expected_type


def test_build_file_part_returns_none_for_unsupported_input(tmp_path):
    executor = build_executor(modalities={"text"})
    path = tmp_path / "photo.jpg"
    path.write_bytes(b"data")

    assert executor._build_file_part(str(path), "image/jpeg") is None


async def test_download_media_without_media_raises():
    executor = build_executor()

    class MessageStub:
        media = None

    with pytest.raises(ExecutionError):
        await executor._download_media({"message": MessageStub()})
