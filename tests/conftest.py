"""Shared fixtures and environment setup for the offline test suite."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("TG_API_ID", "1")
os.environ.setdefault("TG_API_HASH", "dummy-hash")
os.environ.setdefault("OPENROUTER_API_KEY", "dummy-key")

import datetime  # noqa: E402

import pytest  # noqa: E402
from telethon.tl.types import Document, DocumentAttributeSticker, PeerUser, User  # noqa: E402


@pytest.fixture
def sample_user() -> User:
    return User(id=100000001, is_self=False, access_hash=-777, first_name="Vasya", last_name=None)


@pytest.fixture
def sample_peer() -> PeerUser:
    return PeerUser(user_id=100000001)


@pytest.fixture
def sample_document() -> Document:
    return Document(
        id=77,
        access_hash=5,
        file_reference=b"\x01\x02",
        date=datetime.datetime(2026, 9, 19, tzinfo=datetime.timezone.utc),
        mime_type="image/webp",
        size=12345,
        dc_id=2,
        attributes=[DocumentAttributeSticker(alt="😀", stickerset=None)],
    )
