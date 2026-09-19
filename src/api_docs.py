"""Telegram API documentation index used by docsearch and docfetch actions."""

import importlib
import inspect
import pkgutil
import re
import zlib
from typing import Any, Dict, List, Optional, Tuple

import telethon.tl.functions as functions_module
import telethon.tl.types as types_module
from telethon.tl.tlobject import TLObject

from src.dto import format_annotation, type_path
from src.exceptions import MethodNotFoundError
from src.logger import get_logger

logger = get_logger("api_docs")

ENTITY_ABSTRACTS = ("InputPeer", "InputUser", "InputChannel")

API_NOTES = {
    "telethon.tl.types.MissingInvitee": (
        "Пользователь не был добавлен в чат. Проверь поля MissingInvitee; если прямое добавление "
        "недоступно, можно создать invite-ссылку через messages.ExportChatInviteRequest и отправить её пользователю."
    ),
    "telethon.tl.types.messages.InvitedUsers": (
        "Результат добавления участников: invitees — кого добавили, missing_invitees — кого добавить не удалось."
    ),
}

FIELD_NOTES = {
    "telethon.tl.types.MissingInvitee": {
        "premium_would_allow_invite": (
            "True, если пользователя можно было бы добавить при наличии у него Telegram Premium."
        ),
        "premium_required_for_pm": "True, если для личных сообщений пользователю нужен Telegram Premium.",
    },
}


class _Entry:
    """Indexed Telegram API class with precomputed search metadata."""

    __slots__ = ("path", "alias", "cls", "kind", "returns", "param_names", "text")

    def __init__(self, path: str, alias: str, cls: type, kind: str):
        self.path = path
        self.alias = alias
        self.cls = cls
        self.kind = kind
        self.returns = _returns_of(cls) or ""
        try:
            self.param_names = [name for name in inspect.signature(cls.__init__).parameters if name != "self"]
        except (TypeError, ValueError):
            self.param_names = []
        self.text = " ".join([alias.lower(), self.returns.lower(), " ".join(self.param_names)]).lower()


_entries: Optional[List[_Entry]] = None
_by_path: Optional[Dict[str, _Entry]] = None
_by_alias: Optional[Dict[str, _Entry]] = None
_by_short: Optional[Dict[str, List[_Entry]]] = None
_variants_cache: Dict[str, List[str]] = {}
_type_classes: Optional[List[type]] = None


def _returns_of(cls: type) -> Optional[str]:
    doc = inspect.getdoc(cls.__init__) or ""
    for line in doc.splitlines():
        line = line.strip()
        if line.startswith(":returns"):
            rest = line[len(":returns") :].strip()
            return rest.split(":")[0].strip() or rest
    return None


def _iter_type_classes():
    seen = set()
    for name, obj in vars(types_module).items():
        if inspect.isclass(obj) and issubclass(obj, TLObject) and obj is not TLObject and obj not in seen:
            seen.add(obj)
            yield name, obj, f"types.{name}"
    for modinfo in pkgutil.iter_modules(types_module.__path__):
        module = importlib.import_module(f"telethon.tl.types.{modinfo.name}")
        for name, obj in vars(module).items():
            if inspect.isclass(obj) and issubclass(obj, TLObject) and obj is not TLObject and obj not in seen:
                seen.add(obj)
                yield name, obj, f"{modinfo.name}.{name}"


def _all_type_classes() -> List[type]:
    global _type_classes
    if _type_classes is None:
        _type_classes = [cls for _, cls, _ in _iter_type_classes()]
    return _type_classes


def _iter_classes():
    for _, obj, alias in _iter_type_classes():
        path = f"telethon.tl.{alias}" if alias.startswith("types.") else f"telethon.tl.types.{alias}"
        yield path, alias, obj, "type"
    for name, obj in vars(functions_module).items():
        if inspect.isclass(obj) and issubclass(obj, TLObject) and obj is not TLObject:
            yield f"telethon.tl.functions.{name}", name, obj, "function"
    for modinfo in pkgutil.iter_modules(functions_module.__path__):
        module = importlib.import_module(f"telethon.tl.functions.{modinfo.name}")
        for name, obj in vars(module).items():
            if inspect.isclass(obj) and issubclass(obj, TLObject) and obj is not TLObject:
                yield f"telethon.tl.functions.{modinfo.name}.{name}", f"{modinfo.name}.{name}", obj, "function"


def _build_index():
    global _entries, _by_path, _by_alias, _by_short
    if _entries is not None:
        return

    entries: List[_Entry] = []
    by_path: Dict[str, _Entry] = {}
    by_alias: Dict[str, _Entry] = {}
    by_short: Dict[str, List[_Entry]] = {}
    seen_classes = set()

    for path, alias, cls, kind in _iter_classes():
        if cls in seen_classes:
            continue
        seen_classes.add(cls)
        entry = _Entry(path, alias, cls, kind)
        entries.append(entry)
        by_path[path] = entry
        by_alias[alias] = entry
        by_short.setdefault(cls.__name__, []).append(entry)

    _entries = entries
    _by_path = by_path
    _by_alias = by_alias
    _by_short = by_short
    logger.info("Telegram API index built: %d entries.", len(entries))


def _resolve_exact(query: str) -> _Entry:
    query = query.strip()
    if not query:
        raise MethodNotFoundError("Empty API query. Use docsearch to find the exact name.")

    _build_index()

    if query in _by_path:
        return _by_path[query]
    if query in _by_alias:
        return _by_alias[query]

    candidates = _by_short.get(query, [])
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        variants = ", ".join(entry.path for entry in candidates)
        raise MethodNotFoundError(f"Ambiguous API '{query}'. Use one of: {variants}")

    raise MethodNotFoundError(f"Unknown API '{query}'. Use docsearch first to find the exact name.")


def _safe_default(default: Any) -> Any:
    if default is None or isinstance(default, (bool, int, float, str)):
        return default
    return str(default)


def _entity_abstract(annotation: Any) -> Optional[str]:
    for match in re.finditer(r"Type([A-Za-z0-9_]+)", str(annotation)):
        if match.group(1) in ENTITY_ABSTRACTS:
            return match.group(1)
    return None


def _is_list_annotation(annotation: Any) -> bool:
    return bool(re.search(r"\b(List|list|Vector)\s*\[", str(annotation)))


def _entity_example(annotation: Any) -> Any:
    abstract = _entity_abstract(annotation)
    if _is_list_annotation(annotation):
        if abstract == "InputUser":
            return [100000001, 100000002]
        return [-1001234567890]
    if abstract == "InputUser":
        return 100000001
    return -1001234567890


def _variants_for(annotation: Any) -> List[str]:
    match = re.search(r"Type([A-Za-z0-9_]+)", str(annotation))
    if not match:
        return []

    abstract = match.group(1)
    if abstract in _variants_cache:
        return _variants_cache[abstract]

    subclass_id = zlib.crc32(abstract.encode())
    variants = sorted(
        type_path(cls) for cls in _all_type_classes() if getattr(cls, "SUBCLASS_OF_ID", None) == subclass_id
    )
    _variants_cache[abstract] = variants
    return variants


def _build_template(entry: _Entry) -> Tuple[Dict[str, Any], List[str]]:
    data: Dict[str, Any] = {}
    omitted_required: List[str] = []
    for name, param in inspect.signature(entry.cls.__init__).parameters.items():
        if name == "self":
            continue
        if _entity_abstract(param.annotation):
            data[name] = _entity_example(param.annotation)
        elif param.default is inspect._empty:
            omitted_required.append(name)
    return data, omitted_required


def describe_api(query: str) -> Dict[str, Any]:
    """Return full documentation for an exact API name, including a partial template."""
    entry = _resolve_exact(query)

    params = []
    for name, param in inspect.signature(entry.cls.__init__).parameters.items():
        if name == "self":
            continue
        required = param.default is inspect._empty
        item: Dict[str, Any] = {
            "name": name,
            "type": format_annotation(param.annotation),
            "required": required,
            "default": None if required else _safe_default(param.default),
        }
        variants = _variants_for(param.annotation)
        if variants:
            item["variants"] = variants
        abstract = _entity_abstract(param.annotation)
        if abstract:
            item["entity_like"] = True
            item["preferred_input"] = "integer marked ID or username"
            item["examples"] = _entity_example_examples(param.annotation)
        field_note = FIELD_NOTES.get(entry.path, {}).get(name)
        if field_note:
            item["note"] = field_note
        params.append(item)

    template_data, omitted_required = _build_template(entry)
    result: Dict[str, Any] = {
        "api": entry.path,
        "kind": entry.kind,
        "constructor_id": entry.cls.CONSTRUCTOR_ID,
        "params": params,
        "returns": entry.returns or None,
        "template_partial": True,
        "template": {"data": template_data},
        "omitted_required_fields": omitted_required,
    }
    api_note = API_NOTES.get(entry.path)
    if api_note:
        result["note"] = api_note
    return result


def _entity_example_examples(annotation: Any) -> List[Any]:
    example = _entity_example(annotation)
    if _is_list_annotation(annotation):
        return [example]
    return [example, "username"]


def search_api(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Search the Telegram API by keywords and return the best matches."""
    tokens = [token for token in query.lower().replace(".", " ").replace("_", " ").split() if token]
    if not tokens:
        return []

    _build_index()

    results = []
    for entry in _entries:
        short_name = entry.cls.__name__.lower()
        score = 0
        matched = set()
        for token in tokens:
            if token in short_name:
                score += 4
                matched.add("name")
            if token in entry.alias.lower():
                score += 2
                matched.add("namespace")
            if token in entry.returns.lower():
                score += 1
                matched.add("returns")
            if any(token in name.lower() for name in entry.param_names):
                score += 1
                matched.add("params")
        if score:
            results.append((score, entry, sorted(matched)))

    results.sort(key=lambda item: (-item[0], item[1].path))
    return [
        {"api": entry.path, "kind": entry.kind, "returns": entry.returns or None, "matched": matched}
        for _, entry, matched in results[:limit]
    ]
