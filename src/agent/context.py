"""Conversation history management with JSON persistence."""

import json
from typing import Any, Dict, List, Optional

from src.core.config import CONTEXT_FILE_PATH
from src.core.logger import get_logger

logger = get_logger("context")


class ContextManager:
    """Keeps system prompt and history, persisting text messages to disk."""

    def __init__(self, system_prompt: str):
        self.system_prompt = system_prompt
        self.history: List[Dict[str, Any]] = []
        self._load_from_file()

    def _load_from_file(self):
        if not CONTEXT_FILE_PATH.exists():
            return
        try:
            with open(CONTEXT_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data:
                    role = item["role"]
                    if role == "model":
                        role = "assistant"
                    self.history.append({"role": role, "content": item["content"]})
            logger.info(f"Successfully loaded context from {CONTEXT_FILE_PATH}")
        except (IOError, json.JSONDecodeError, KeyError) as e:
            logger.error("Failed to load context from %s: %s", CONTEXT_FILE_PATH, e)

    def _save_to_file(self):
        try:
            data = []
            for message in self.history:
                content = message["content"]
                if isinstance(content, str):
                    text = content
                else:
                    text = next((part.get("text", "") for part in content if part.get("type") == "text"), "")
                data.append({"role": message["role"], "content": text})
            with open(CONTEXT_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            logger.error("Failed to save context to %s: %s", CONTEXT_FILE_PATH, e)

    def get_messages(self) -> List[Dict[str, Any]]:
        """Return the OpenAI-compatible message list including the system prompt."""
        return [{"role": "system", "content": self.system_prompt}] + self.history

    def add_user_message(self, text: str, file_parts: Optional[List[Dict[str, Any]]] = None):
        """Append a user message, optionally with multimodal content parts."""
        if file_parts:
            content: Any = [{"type": "text", "text": text}] + file_parts
        else:
            content = text
        self.history.append({"role": "user", "content": content})
        self._save_to_file()

    def add_model_message(self, text: str):
        """Append an assistant message."""
        self.history.append({"role": "assistant", "content": text})
        self._save_to_file()
