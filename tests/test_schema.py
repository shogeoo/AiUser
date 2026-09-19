"""Tests for the model response JSON schema."""

from src.schema import AGENT_RESPONSE_SCHEMA


def test_schema_enforces_action_envelope():
    schema = AGENT_RESPONSE_SCHEMA["schema"]

    assert AGENT_RESPONSE_SCHEMA["strict"] is True
    assert schema["required"] == ["actions"]
    assert schema["additionalProperties"] is False

    item = schema["properties"]["actions"]["items"]
    assert item["required"] == ["id", "type", "data"]
    assert item["additionalProperties"] is False
    assert item["properties"]["data"]["type"] == "object"


def test_action_type_is_a_free_string():
    schema = AGENT_RESPONSE_SCHEMA["schema"]
    item = schema["properties"]["actions"]["items"]

    assert item["properties"]["type"]["type"] == "string"
