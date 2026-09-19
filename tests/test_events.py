"""Tests for event serialization."""

from telethon.tl.types import PeerUser, UpdateReadHistoryInbox

from src.telegram.events import serialize_event


def test_update_is_serialized_into_envelope():
    update = UpdateReadHistoryInbox(
        peer=PeerUser(user_id=100000001),
        max_id=5,
        still_unread_count=0,
        pts=1,
        pts_count=1,
    )

    envelope = serialize_event(update)

    assert envelope["type"] == "telethon.tl.types.UpdateReadHistoryInbox"
    assert envelope["data"]["peer"]["type"] == "telethon.tl.types.PeerUser"
    assert envelope["data"]["max_id"] == 5
