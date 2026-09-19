"""Telegram DTO <-> protocol JSON conversion."""

import base64
import datetime
import importlib
import inspect
import re
from typing import Any, Dict, List

import telethon.tl.types as tl_types
from telethon.tl.tlobject import TLObject

from src.core.exceptions import ArgumentError, MethodNotFoundError
from src.core.logger import get_logger

logger = get_logger("dto")

ENVELOPE_TYPE_PREFIX = "telethon."


def type_path(cls: type) -> str:
    """Return the canonical protocol type path for a Telethon class."""
    if hasattr(tl_types, cls.__name__):
        return f"telethon.tl.types.{cls.__name__}"
    return f"{cls.__module__}.{cls.__name__}"


def format_annotation(annotation: Any) -> str:
    """Return a compact human-readable form of a type annotation."""
    if annotation is inspect._empty:
        return "any"
    text = str(annotation)
    text = re.sub(r"ForwardRef\((?:'|\")([^'\"]+)(?:'|\")\)", r"\1", text)
    if text.startswith("<class '") and text.endswith("'>"):
        text = text[len("<class '") : -2]
    return text


def constructor_parameters(cls: type) -> Dict[str, inspect.Parameter]:
    """Return constructor parameters of a DTO class, excluding self."""
    return {name: param for name, param in inspect.signature(cls.__init__).parameters.items() if name != "self"}


def format_signature(cls: type) -> str:
    """Return a compact constructor signature with types and defaults."""
    parts = []
    for name, param in constructor_parameters(cls).items():
        annotation = format_annotation(param.annotation)
        if param.default is inspect._empty:
            parts.append(f"{name}: {annotation}")
        else:
            parts.append(f"{name}: {annotation} = {param.default!r}")
    return f"{cls.__name__}({', '.join(parts)})"


def format_callable_signature(func: Any) -> str:
    """Return a compact signature for a callable, including variadic parameters."""
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return getattr(func, "__name__", str(func))

    parts = []
    for name, param in signature.parameters.items():
        annotation = format_annotation(param.annotation)
        if param.kind is param.VAR_POSITIONAL:
            parts.append(f"*{name}")
        elif param.kind is param.VAR_KEYWORD:
            parts.append(f"**{name}")
        elif param.default is inspect._empty:
            parts.append(f"{name}: {annotation}")
        else:
            parts.append(f"{name}: {annotation} = {param.default!r}")
    return f"{getattr(func, '__name__', 'callable')}({', '.join(parts)})"


def missing_required_fields(cls: type, provided: Any) -> List[str]:
    """List required constructor fields that are absent from the provided names."""
    provided = set(provided)
    missing = []
    for name, param in constructor_parameters(cls).items():
        if param.default is inspect._empty and name not in provided:
            missing.append(f"{name}: {format_annotation(param.annotation)}")
    return missing


def _fields_hint(cls: type) -> str:
    return ", ".join(
        f"{name}: {format_annotation(param.annotation)}" for name, param in constructor_parameters(cls).items()
    )


def to_json(value: Any) -> Any:
    """Convert a Telethon value into protocol JSON (envelopes, $bytes, ISO dates)."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return {"$bytes": base64.b64encode(value).decode("ascii")}
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [to_json(item) for item in value]
    if isinstance(value, dict):
        return {key: to_json(item) for key, item in value.items()}
    if isinstance(value, TLObject):
        data: Dict[str, Any] = {}
        for key, item in vars(value).items():
            if key.startswith("_"):
                continue
            data[key] = to_json(item)
        return {"type": type_path(type(value)), "data": data}
    return str(value)


def resolve_dto_class(type_path: str) -> type:
    """Resolve a protocol type path to a Telethon DTO class."""
    module_path, _, class_name = type_path.rpartition(".")
    if not module_path or not class_name:
        raise MethodNotFoundError(f"Invalid DTO type path: {type_path}")
    try:
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
    except (ImportError, AttributeError) as e:
        raise MethodNotFoundError(f"Unknown DTO type: {type_path}") from e
    if not inspect.isclass(cls) or not issubclass(cls, TLObject) or cls is TLObject:
        raise MethodNotFoundError(f"Not a Telegram DTO type: {type_path}")
    return cls


def _convert_by_annotation(value: Any, annotation: Any) -> Any:
    if value is None or isinstance(value, datetime.datetime):
        return value
    if "datetime" in str(annotation):
        if isinstance(value, (int, float)):
            return datetime.datetime.fromtimestamp(value, datetime.timezone.utc)
        if isinstance(value, str):
            try:
                return datetime.datetime.fromisoformat(value)
            except ValueError:
                return value
    return value


def coerce_arguments(target: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce values to datetime where the target signature expects it."""
    try:
        signature = inspect.signature(target)
    except (TypeError, ValueError):
        return params
    for name, value in params.items():
        param = signature.parameters.get(name)
        if param is not None:
            params[name] = _convert_by_annotation(value, param.annotation)
    return params


def from_json(value: Any) -> Any:
    """Build Telethon objects from protocol JSON with strict envelope validation."""
    if isinstance(value, list):
        return [from_json(item) for item in value]
    if isinstance(value, dict):
        if "$bytes" in value:
            try:
                return base64.b64decode(value["$bytes"])
            except (ValueError, TypeError) as e:
                raise ArgumentError(f"Invalid $bytes value: {e}") from e
        type_path = value.get("type")
        if isinstance(type_path, str) and type_path.startswith(ENVELOPE_TYPE_PREFIX):
            if "data" not in value:
                raise ArgumentError(
                    f"Malformed Telegram DTO envelope for {type_path}: expected "
                    f'{{"type": ..., "data": {{...}}}}, got keys: {list(value.keys())}.'
                )
            cls = resolve_dto_class(type_path)
            data = value["data"]
            if not isinstance(data, dict):
                raise ArgumentError(
                    f"Envelope 'data' for {type_path} must be an object with fields: {_fields_hint(cls)} "
                    f"(got: {type(data).__name__})."
                )
            kwargs: Dict[str, Any] = {}
            annotations: Dict[str, Any] = {}
            for name, param in constructor_parameters(cls).items():
                annotations[name] = param.annotation
                if name in data:
                    kwargs[name] = from_json(data[name])
            for name in list(kwargs.keys()):
                kwargs[name] = _convert_by_annotation(kwargs[name], annotations.get(name))
            try:
                return cls(**kwargs)
            except TypeError as e:
                missing = missing_required_fields(cls, kwargs.keys())
                details = f"missing required fields: {', '.join(missing)}. " if missing else ""
                raise ArgumentError(
                    f"Invalid parameters for {type_path}: {details}{e}. Signature: {format_signature(cls)}"
                ) from e
        return {key: from_json(item) for key, item in value.items()}
    return value
