"""Autonomous agent loop: Telegram events -> LLM actions -> execution -> results."""

import asyncio
import json
import re
import time
from typing import Any, Dict, List, Tuple

from openai import AsyncOpenAI
from telethon import TelegramClient, errors

from src.buffer import EventBuffer
from src.config import (
    MODEL_NAME,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    PERSON_PROMPT_PATH,
    SESSION_FILE,
    SYSTEM_PROMPT_PATH,
    TG_API_HASH,
    TG_API_ID,
)
from src.context import ContextManager
from src.events import serialize_event
from src.executor import ActionExecutor
from src.logger import get_logger
from src.model_info import get_input_modalities
from src.schema import AGENT_RESPONSE_SCHEMA

logger = get_logger("assistant")

REQUEST_INTERVAL = 5


class TelegramAIAssistant:
    """Wires Telegram, OpenRouter, conversation context and the action executor."""

    def __init__(self):
        try:
            self.tg_client = TelegramClient(SESSION_FILE, TG_API_ID, TG_API_HASH)
            self.openai_client = AsyncOpenAI(api_key=OPENROUTER_API_KEY, base_url=OPENROUTER_BASE_URL)

            if not SYSTEM_PROMPT_PATH.exists():
                raise FileNotFoundError(f"System prompt file not found at {SYSTEM_PROMPT_PATH}")

            system_prompt_content = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()

            person_prompt_content = ""
            if PERSON_PROMPT_PATH.exists():
                person_prompt_content = PERSON_PROMPT_PATH.read_text(encoding="utf-8").strip()
            else:
                logger.warning(f"Person prompt file not found at {PERSON_PROMPT_PATH}. Continuing without it.")

            combined_prompt_text = system_prompt_content
            if person_prompt_content:
                combined_prompt_text += "\n\nPERSON:\n" + person_prompt_content

            self.context_mgr = ContextManager(combined_prompt_text)
            self.executor = ActionExecutor(self.tg_client, input_modalities=set())
            self.event_buffer = EventBuffer(self._on_event_buffer_flush)
            self._processing = False
            self._last_request_time = 0
            self._seq = 0
            self._action_counter = 0
            self._init_action_counter()
            self._pending_results: List[Tuple[int, Dict[str, Any], List[Dict[str, Any]]]] = []
            self.is_running = True
        except Exception as e:
            logger.critical("Failed to initialize assistant: %s", e)
            self.is_running = False

    async def setup(self):
        try:
            input_modalities = await get_input_modalities(MODEL_NAME)
            self.executor.input_modalities = input_modalities
            logger.info("Model %s input modalities: %s", MODEL_NAME, input_modalities)

            await self.tg_client.start(password=lambda: input("Please enter your 2FA password: "))
            self.tg_client.add_event_handler(self._raw_handler)
            logger.info("Started and connected to Telegram.")
            return True
        except errors.ApiIdInvalidError as e:
            logger.critical("Telegram API ID/Hash is invalid: %s", e)
        except Exception as e:
            logger.critical("Failed to connect to Telegram: %s", e)
        return False

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _init_action_counter(self):
        max_number = 0
        for message in self.context_mgr.history:
            content = message.get("content")
            if not isinstance(content, str):
                continue
            try:
                payload = json.loads(content)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue

            ids: List[Any] = []
            if message.get("role") == "assistant" and isinstance(payload.get("actions"), list):
                ids = [item.get("id") for item in payload["actions"] if isinstance(item, dict)]
            elif payload.get("type") == "action_result" and isinstance(payload.get("data"), dict):
                ids = [payload["data"].get("id")]

            for action_id in ids:
                match = re.match(r"^a(\d+)$", str(action_id))
                if match:
                    max_number = max(max_number, int(match.group(1)))

        self._action_counter = max_number

    def _assign_action_ids(self, actions: List[Any]):
        for action in actions:
            if not isinstance(action, dict):
                continue
            self._action_counter += 1
            action["id"] = f"a{self._action_counter:06d}"

    async def _raw_handler(self, event):
        serialized = serialize_event(event)
        logger.info("Telegram event:\n%s", json.dumps(serialized, ensure_ascii=False, indent=2))
        self.event_buffer.add_event((self._next_seq(), serialized))

    async def _on_event_buffer_flush(self, events_list: List[Tuple[int, Dict[str, Any]]]):
        self.event_buffer.buffer.extend(events_list)
        if self._processing:
            return

        self._processing = True
        try:
            await self._agent_turn()
        except Exception as e:
            logger.error("Error in agent turn: %s", e)
        finally:
            self._processing = False

    async def _agent_turn(self):
        while True:
            self._flush_pending()

            actions = await self._request_actions()
            if not actions:
                if not self._has_pending():
                    break
                continue

            logger.info("Executing %d action(s)...", len(actions))
            await self.executor.execute_actions(actions, self._publish_result)

    def _publish_result(self, envelope: Dict[str, Any], attachments: List[Dict[str, Any]]):
        logger.info("Action result:\n%s", json.dumps(envelope, ensure_ascii=False, indent=2))
        self._pending_results.append((self._next_seq(), envelope, attachments))

    def _has_pending(self) -> bool:
        return bool(self.event_buffer.buffer or self._pending_results)

    def _flush_pending(self):
        items = [(seq, envelope, []) for seq, envelope in self.event_buffer.buffer]
        items.extend(self._pending_results)
        if not items:
            return

        self.event_buffer.buffer.clear()
        self._pending_results.clear()

        for _, envelope, attachments in sorted(items, key=lambda item: item[0]):
            self.context_mgr.add_user_message(json.dumps(envelope, ensure_ascii=False), file_parts=attachments or None)

    async def _request_actions(self) -> List[Dict[str, Any]]:
        delay = REQUEST_INTERVAL - (time.monotonic() - self._last_request_time)
        if delay > 0:
            await asyncio.sleep(delay)
        self._last_request_time = time.monotonic()

        logger.info("Sending runtime state to the neural network...")
        try:
            response = await self.openai_client.chat.completions.create(
                model=MODEL_NAME,
                messages=self.context_mgr.get_messages(),
                response_format={"type": "json_schema", "json_schema": AGENT_RESPONSE_SCHEMA},
            )
        except Exception as e:
            logger.error("Neural network API call failed: %s", e)
            return []

        content = (response.choices[0].message.content or "").strip()
        if not content:
            logger.warning("Neural network returned empty content.")
            return []

        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            logger.error("Neural network returned invalid JSON:\n%s", content)
            return []

        actions = payload.get("actions")
        if not isinstance(actions, list):
            logger.error("Neural network response has no actions array:\n%s", content)
            return []

        self._assign_action_ids(actions)
        logger.info("Neural network actions:\n%s", json.dumps(actions, ensure_ascii=False, indent=2))
        self.context_mgr.add_model_message(json.dumps({"actions": actions}, ensure_ascii=False))

        return actions

    async def run(self):
        """Connect to Telegram and run until the client disconnects."""
        if not self.is_running or not await self.setup():
            return

        logger.info("Assistant is running. Press Ctrl+C to stop.")
        try:
            await self.tg_client.run_until_disconnected()
        finally:
            logger.info("Shutting down.")
            self.is_running = False
