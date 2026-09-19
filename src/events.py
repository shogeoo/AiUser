"""Serialization of incoming Telegram updates into protocol envelopes."""

from typing import Any, Dict

from src.dto import to_json


def serialize_event(event: Any) -> Dict[str, Any]:
    """Convert a raw Telethon update into a JSON envelope."""
    envelope = to_json(event)
    if isinstance(envelope, dict) and "type" in envelope and "data" in envelope:
        return envelope
    return {
        "type": f"{type(event).__module__}.{type(event).__name__}",
        "data": {"value": envelope},
    }
