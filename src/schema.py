"""JSON schema for the model response enforced via structured outputs."""

AGENT_RESPONSE_SCHEMA = {
    "name": "telegram_agent_response",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "actions": {
                "type": "array",
                "description": "Actions to execute strictly in order. Empty array means do nothing.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": (
                                "Action id. The runtime assigns sequential ids like a000001; "
                                "any value may be used here."
                            ),
                        },
                        "type": {
                            "type": "string",
                            "description": (
                                "High-level command name or full path to a Telegram DTO request, "
                                "e.g. telethon.tl.functions.phone.AcceptCallRequest."
                            ),
                        },
                        "data": {
                            "type": "object",
                            "description": "Parameters of the high-level command or fields of the raw DTO request.",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["id", "type", "data"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["actions"],
        "additionalProperties": False,
    },
}
