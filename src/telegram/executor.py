"""Execution of model actions: high-level commands, raw TL requests and API docs."""

import asyncio
import base64
import mimetypes
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from telethon import TelegramClient
from telethon.errors import RPCError

from src.core.exceptions import ActionError, ArgumentError, ExecutionError, MethodNotFoundError
from src.core.logger import get_logger
from src.telegram.api_docs import describe_api, search_api
from src.telegram.commands import HIGH_LEVEL_COMMANDS
from src.telegram.dto import (
    coerce_arguments,
    format_callable_signature,
    format_signature,
    from_json,
    missing_required_fields,
    resolve_dto_class,
    to_json,
)

logger = get_logger("executor")

DOWNLOADS_DIR = "downloads/"


class ActionExecutor:
    """Executes actions sequentially and reports a result for each of them."""

    def __init__(self, tg_client: TelegramClient, input_modalities: Optional[set] = None):
        self.tg_client = tg_client
        self.input_modalities = input_modalities if input_modalities is not None else set()

    async def execute_actions(
        self,
        actions: List[Dict[str, Any]],
        on_result: Optional[Callable[[Dict[str, Any], List[Dict[str, Any]]], None]] = None,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Run actions in order, optionally publishing each result via callback."""
        results: List[Dict[str, Any]] = []
        attachments: List[Dict[str, Any]] = []

        for action in actions:
            result, parts = await self._execute_action(action)
            results.append(result)
            attachments.extend(parts)
            if on_result is not None:
                on_result(result, parts)

        return results, attachments

    async def _execute_action(self, action: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        action_id = action.get("id")
        try:
            result, parts = await self._dispatch(action)
            envelope = {"type": "action_result", "data": {"id": action_id, "status": "success", "result": result}}
            return envelope, parts
        except ActionError as e:
            logger.warning("Action %s failed: %s", action_id, e)
            return self._error_result(action_id, type(e).__name__, str(e)), []
        except RPCError as e:
            message = str(e)
            wait_seconds = getattr(e, "seconds", None)
            if wait_seconds is not None:
                message = f"{message} (retry after {wait_seconds} seconds)"
            logger.warning("Action %s raised RPC error: %s", action_id, message)
            return self._error_result(action_id, type(e).__name__, message), []
        except Exception as e:
            logger.exception("Unexpected error while executing action %s", action_id)
            return self._error_result(action_id, type(e).__name__, str(e)), []

    @staticmethod
    def _error_result(action_id: Any, error_type: str, message: str) -> Dict[str, Any]:
        return {
            "type": "action_result",
            "data": {"id": action_id, "status": "error", "error_type": error_type, "message": message},
        }

    async def _dispatch(self, action: Dict[str, Any]) -> Tuple[Any, List[Dict[str, Any]]]:
        action_type = action.get("type")
        data = action.get("data")
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise ArgumentError("'data' must be an object.")

        if action_type == "docsearch":
            query = str(data.get("query", "")).strip()
            if not query:
                raise ArgumentError("docsearch requires 'query'.")
            return {"type": "api_info", "data": {"matches": search_api(query)}}, []
        if action_type == "docfetch":
            query = str(data.get("query", "")).strip()
            if not query:
                raise ArgumentError("docfetch requires 'query'.")
            return {"type": "api_info", "data": describe_api(query)}, []

        if action_type in HIGH_LEVEL_COMMANDS:
            return await self._execute_high_level(action_type, data)
        if isinstance(action_type, str) and action_type.startswith("telethon."):
            return await self._execute_raw(action_type, data)

        raise MethodNotFoundError(f"Unknown action type: {action_type}")

    async def _execute_high_level(self, command: str, data: Dict[str, Any]) -> Tuple[Any, List[Dict[str, Any]]]:
        params = {key: from_json(value) for key, value in data.items() if value is not None}

        if command == "download_media":
            return await self._download_media(params)
        if command == "download_profile_photo":
            return await self._download_profile_photo(params)
        if command == "action":
            return await self._perform_action(params)

        method = getattr(self.tg_client, command)
        params = coerce_arguments(method, params)
        try:
            result = await method(**params)
        except TypeError as e:
            raise ArgumentError(
                f"Invalid parameters for {command}: {e}. Signature: {format_callable_signature(method)}"
            ) from e
        return to_json(result), []

    async def _execute_raw(self, type_path: str, data: Dict[str, Any]) -> Tuple[Any, List[Dict[str, Any]]]:
        if ".functions." not in type_path:
            raise MethodNotFoundError(f"Not a raw Telegram request: {type_path}")

        request_cls = resolve_dto_class(type_path)
        params = coerce_arguments(request_cls, from_json(data))
        try:
            request_object = request_cls(**params)
        except TypeError as e:
            missing = missing_required_fields(request_cls, params.keys())
            details = f"missing required fields: {', '.join(missing)}. " if missing else ""
            raise ArgumentError(
                f"Invalid parameters for {type_path}: {details}{e}. Signature: {format_signature(request_cls)}"
            ) from e

        result = await self.tg_client(request_object)
        return to_json(result), []

    async def _download_media(self, params: Dict[str, Any]) -> Tuple[Any, List[Dict[str, Any]]]:
        message = params.pop("message", None)
        if message is None:
            entity = params.pop("entity", None)
            message_id = params.pop("message_id", None)
            if entity is None or message_id is None:
                raise ArgumentError("download_media requires 'message' (DTO) or 'entity' and 'message_id'.")
            try:
                message = await self.tg_client.get_messages(entity, ids=message_id)
            except TypeError as e:
                raise ArgumentError(f"Invalid parameters for download_media: {e}") from e

        if not message or not getattr(message, "media", None):
            raise ExecutionError("Message has no media to download.")

        return await self._download_and_attach(lambda path: self.tg_client.download_media(message, file=path))

    async def _download_profile_photo(self, params: Dict[str, Any]) -> Tuple[Any, List[Dict[str, Any]]]:
        entity = params.pop("entity", None)
        if entity is None:
            raise ArgumentError("download_profile_photo requires 'entity'.")
        return await self._download_and_attach(lambda path: self.tg_client.download_profile_photo(entity, file=path))

    async def _perform_action(self, params: Dict[str, Any]) -> Tuple[None, List[Dict[str, Any]]]:
        entity = params.pop("entity", None)
        if entity is None:
            raise ArgumentError("action requires 'entity'.")
        action_name = params.pop("action", "typing")
        duration = params.pop("duration", 5)
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration < 0:
            raise ArgumentError("'duration' must be a non-negative number.")

        async with self.tg_client.action(entity, action_name):
            await asyncio.sleep(duration)
        return None, []

    async def _download_and_attach(self, download_coro) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)

        local_path = await download_coro(DOWNLOADS_DIR)
        if not local_path or not os.path.exists(local_path):
            raise ExecutionError("Download failed, file not found.")

        mime_type, _ = mimetypes.guess_type(local_path)
        if not mime_type:
            mime_type = "application/octet-stream"

        data: Dict[str, Any] = {"file": os.path.basename(local_path), "mime_type": mime_type}
        file_part = self._build_file_part(local_path, mime_type)
        if file_part is None:
            data["attached"] = False
            data["note"] = f"Model does not support '{mime_type}' input; the file was saved but not attached."
            return {"type": "file", "data": data}, []

        data["attached"] = True
        return {"type": "file", "data": data}, [file_part]

    def _build_file_part(self, local_path: str, mime_type: str) -> Optional[Dict[str, Any]]:
        with open(local_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")

        data_uri = f"data:{mime_type};base64,{encoded}"

        if mime_type.startswith("image/") and "image" in self.input_modalities:
            return {"type": "image_url", "image_url": {"url": data_uri}}
        if mime_type.startswith("video/") and "video" in self.input_modalities:
            return {"type": "video_url", "video_url": {"url": data_uri}}
        if mime_type == "application/pdf" and "file" in self.input_modalities:
            return {"type": "file", "file": {"filename": os.path.basename(local_path), "file_data": data_uri}}
        if mime_type.startswith("audio/") and "audio" in self.input_modalities:
            audio_format = os.path.splitext(local_path)[1].lstrip(".").lower()
            return {"type": "input_audio", "input_audio": {"data": encoded, "format": audio_format}}

        return None
