"""Tests for the Telegram API documentation index (docsearch/docfetch)."""

import pytest

from src.core.exceptions import MethodNotFoundError
from src.telegram.api_docs import describe_api, search_api


def test_describe_create_chat_marks_entity_like_and_builds_partial_template():
    info = describe_api("telethon.tl.functions.messages.CreateChatRequest")

    users = next(param for param in info["params"] if param["name"] == "users")
    assert users["entity_like"] is True
    assert users["preferred_input"] == "integer marked ID or username"
    assert users["examples"] == [[100000001, 100000002]]

    assert info["template_partial"] is True
    assert info["template"] == {"data": {"users": [100000001, 100000002]}}
    assert info["omitted_required_fields"] == ["title"]


def test_describe_export_chat_invite_uses_scalar_peer_example():
    info = describe_api("telethon.tl.functions.messages.ExportChatInviteRequest")

    peer = next(param for param in info["params"] if param["name"] == "peer")
    assert peer["entity_like"] is True
    assert info["template"] == {"data": {"peer": -1001234567890}}
    assert info["omitted_required_fields"] == []


def test_non_entity_abstract_type_is_not_marked():
    info = describe_api("telethon.tl.functions.messages.ExportChatInviteRequest")

    pricing = next(param for param in info["params"] if param["name"] == "subscription_pricing")
    assert "entity_like" not in pricing
    assert "variants" in pricing


def test_optional_entity_annotation_is_detected():
    info = describe_api("telethon.tl.functions.channels.GetFullChannelRequest")

    channel = next(param for param in info["params"] if param["name"] == "channel")
    assert channel["entity_like"] is True


def test_namespaced_type_can_be_fetched():
    info = describe_api("telethon.tl.types.messages.InvitedUsers")

    assert info["api"] == "telethon.tl.types.messages.InvitedUsers"
    names = [param["name"] for param in info["params"]]
    assert "missing_invitees" in names


def test_notes_are_returned_for_missing_invitee():
    info = describe_api("telethon.tl.types.MissingInvitee")

    assert "note" in info
    fields = {param["name"]: param for param in info["params"]}
    assert "note" in fields["premium_would_allow_invite"]
    assert "note" in fields["premium_required_for_pm"]


def test_search_finds_sticker_set_install():
    matches = search_api("install sticker set")

    apis = [match["api"] for match in matches]
    assert "telethon.tl.functions.messages.InstallStickerSetRequest" in apis
    first = next(match for match in matches if match["api"].endswith("InstallStickerSetRequest"))
    assert "name" in first["matched"]


def test_search_without_tokens_returns_nothing():
    assert search_api("   ") == []


def test_unknown_api_points_to_docsearch():
    with pytest.raises(MethodNotFoundError, match="docsearch"):
        describe_api("make me a sandwich")
