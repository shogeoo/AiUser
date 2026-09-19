"""Tests for Telegram DTO <-> protocol JSON conversion."""

import datetime

import pytest

from src.core.exceptions import ArgumentError, MethodNotFoundError
from src.telegram.dto import coerce_arguments, from_json, resolve_dto_class, to_json, type_path


def test_user_serialization_keeps_all_public_fields(sample_user):
    envelope = to_json(sample_user)

    assert envelope["type"] == "telethon.tl.types.User"
    assert envelope["data"]["access_hash"] == -777
    assert envelope["data"]["last_name"] is None
    assert "_client" not in envelope["data"]


def test_document_serializes_bytes_dates_and_sticker_emoji(sample_document):
    envelope = to_json(sample_document)
    data = envelope["data"]

    assert data["file_reference"] == {"$bytes": "AQI="}
    assert data["date"] == "2026-09-19T00:00:00+00:00"
    sticker = data["attributes"][0]
    assert sticker["type"] == "telethon.tl.types.DocumentAttributeSticker"
    assert sticker["data"]["alt"] == "😀"


def test_custom_message_type_is_normalized():
    from telethon.tl.custom.message import Message as CustomMessage
    from telethon.tl.types import PeerUser

    message = CustomMessage(
        id=1,
        peer_id=PeerUser(user_id=100000001),
        date=datetime.datetime(2026, 9, 19, tzinfo=datetime.timezone.utc),
        message="x",
        out=False,
    )

    assert to_json(message)["type"] == "telethon.tl.types.Message"


def test_namespaced_type_path():
    from telethon.tl.types.messages import InvitedUsers

    assert type_path(InvitedUsers) == "telethon.tl.types.messages.InvitedUsers"


def test_envelope_without_data_is_rejected():
    with pytest.raises(ArgumentError, match="Malformed Telegram DTO envelope"):
        from_json({"type": "telethon.tl.types.InputPeerChat", "data those chat_id": 1})


def test_envelope_with_non_object_data_is_rejected():
    with pytest.raises(ArgumentError, match="must be an object with fields"):
        from_json({"type": "telethon.tl.types.InputPeerChat", "data": "chat_id"})


def test_nested_dto_construction():
    obj = from_json({"type": "telethon.tl.types.InputPhoneCall", "data": {"id": 1, "access_hash": -2}})

    assert type(obj).__name__ == "InputPhoneCall"
    assert obj.id == 1
    assert obj.access_hash == -2


def test_bytes_decoding():
    assert from_json({"$bytes": "AQID"}) == b"\x01\x02\x03"


def test_datetime_coercion_for_raw_request():
    request_cls = resolve_dto_class("telethon.tl.functions.messages.SendMessageRequest")
    params = from_json(
        {
            "peer": {"type": "telethon.tl.types.InputPeerSelf", "data": {}},
            "message": "hi",
            "schedule_date": "2026-09-19T10:00:00+00:00",
        }
    )

    request = request_cls(**coerce_arguments(request_cls, params))

    assert isinstance(request.schedule_date, datetime.datetime)


def test_missing_required_fields_include_signature():
    with pytest.raises(ArgumentError) as exc_info:
        from_json({"type": "telethon.tl.types.InputStickerSetID", "data": {"id": 1}})

    message = str(exc_info.value)
    assert "access_hash" in message
    assert "Signature:" in message


def test_unknown_type_is_rejected():
    with pytest.raises(MethodNotFoundError):
        from_json({"type": "telethon.tl.types.NoSuchThing", "data": {}})


def test_non_dto_type_is_rejected():
    with pytest.raises(MethodNotFoundError):
        from_json({"type": "telethon.tl.types.TLObject", "data": {}})
