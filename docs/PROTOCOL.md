# Протокол агента

Вся работа агента — это обмен JSON-сообщениями между моделью и рантаймом. Модель не пишет код:
она возвращает список действий, рантайм выполняет их и присылает результаты.

## Ответ модели

Модель всегда отвечает ровно одним объектом:

```json
{"actions": [...]}
```

- Пустой массив `{"actions": []}` означает «ничего не делать».
- Действия выполняются строго по порядку, в одном потоке.
- У каждого действия есть `id`, `type` и `data`. `id` присваивает рантайм (`a000001`, `a000002`, ...),
  поэтому в ответе можно писать любое значение — оно будет заменено.

## Конверт объектов

Все Telegram-объекты (события, результаты, вложенные DTO) записываются единым конвертом:

```json
{"type": "полный Python-путь к классу", "data": { ...поля... }}
```

- Путь — полный: `telethon.tl.types.Message`, `telethon.tl.types.InputPhoneCall`,
  `telethon.tl.types.messages.InvitedUsers`.
- Поля передаются полностью, без сокращений: включая `access_hash`, `file_reference`, `null`
  и `alt` у стикеров.
- `bytes` кодируются как `{"$bytes": "<base64>"}`.
- `datetime` кодируются ISO-строкой, например `"2026-09-19T10:04:45+00:00"`.
- Вложенный DTO — такой же конверт. `data` вложенного DTO обязан быть объектом, а не строкой.
- Если объект пришёл в событии, его конверт можно копировать целиком.
- Конверт с `type: "telethon.*"` без корректного `data` отклоняется с ошибкой
  `Malformed Telegram DTO envelope ...`.

## Типы действий

### 1. High-level

```json
{"id": "...", "type": "send_message", "data": {"entity": 100000001, "message": "привет"}}
```

Доступные команды (`src/telegram/commands.py`):

| Команда | Поля `data` |
| --- | --- |
| `send_message` | `entity`, `message`, `reply_to?`, `silent?`, `parse_mode?`, `link_preview?` |
| `edit_message` | `entity`, `message`, `text`, `parse_mode?` |
| `delete_messages` | `entity`, `message_ids` (число или список), `revoke?` |
| `forward_messages` | `entity`, `messages`, `from_peer`, `silent?` |
| `get_messages` | `entity`, `limit?`, `search?`, `reverse?` |
| `pin_message` / `unpin_message` | `entity`, `message`, `notify?` |
| `send_read_acknowledge` | `entity`, `max_id?` |
| `send_file` | `entity`, `file`, `caption?`, `force_document?`, `reply_to?` |
| `download_media` | `message` (DTO) или `entity` + `message_id` |
| `download_profile_photo` | `entity`, `download_big?` |
| `get_dialogs` | `limit?`, `archived?` |
| `delete_dialog` | `entity`, `revoke?` |
| `get_me` | — |
| `get_entity` | `entity` |
| `get_input_entity` | `peer` |
| `get_participants` | `entity`, `limit?`, `search?` |
| `kick_participant` | `entity`, `user` |
| `get_admin_log` | `entity`, `limit?`, `edit?`, `delete?` |
| `get_profile_photos` | `entity`, `limit?` |
| `edit_admin` / `edit_permissions` | `entity`, `user`, права |
| `get_permissions` | `entity`, `user?` |
| `action` | `entity`, `action` (`typing`, `upload_photo`, ...), `duration?` |

`entity`/`user`/`peer` — числовой id, username или DTO-конверт.

### 2. Raw Telegram API

```json
{
  "id": "...",
  "type": "telethon.tl.functions.messages.CreateChatRequest",
  "data": {"users": [100000001, 100000002], "title": "Братья"}
}
```

- `type` — полный путь к `telethon.tl.functions.*`.
- Вложенные объекты — конверты: `{"type": "telethon.tl.types.InputPhoneCall", "data": {...}}`.
- Entity-параметры (`InputPeer`, `InputUser`, `InputChannel` и их обёртки `List[...]`, `Optional[...]`)
  можно передавать скалярами: id, marked id (`-1001234567890`) или username. Telethon сам резолвит
  их при выполнении (`request.resolve` → `get_input_entity`). `get_input_entity` — вспомогательный
  инструмент, а не обязательный шаг.

### 3. Документация API

Сначала поиск по ключевым словам:

```json
{"id": "...", "type": "docsearch", "data": {"query": "install sticker set"}}
```

Результат — конверт `api_info` со списком совпадений и полем `matched`, которое показывает, где
именно совпало: `name`, `namespace`, `params`, `returns`.

Затем полная документация по точному имени:

```json
{"id": "...", "type": "docfetch", "data": {"query": "telethon.tl.functions.messages.InstallStickerSetRequest"}}
```

`docfetch` возвращает `params` (имя, тип, `required`, `default`), `returns`, `constructor_id`,
а также:

- `entity_like`, `preferred_input`, `examples` — для entity-параметров;
- `variants` — конкретные классы для абстрактных типов вроде `TypeInputUser`;
- `template_partial: true`, `template` (только entity-поля с примерами) и `omitted_required_fields` —
  чтобы шаблон не выглядел полным запросом;
- `note` — смысловые подсказки для отдельных типов и полей.

Если `docfetch` получил не точное имя, он отвечает ошибкой и отправляет в `docsearch`.

## Результаты выполнения

После каждого действия приходит отдельное сообщение:

```json
{"type": "action_result", "data": {"id": "a000001", "status": "success", "result": {...}}}
```

или при ошибке:

```json
{"type": "action_result", "data": {"id": "a000001", "status": "error",
  "error_type": "ArgumentError", "message": "..."}}
```

- `result` — DTO-конверт, массив конвертов или `null`.
- Скачанные медиа прикрепляются к сообщению своего `action_result`, в `result` приходит
  `{"type": "file", "data": {"file": "...", "mime_type": "...", "attached": true}}`.
- Ошибки содержат подсказки: обязательные поля, полную сигнатуру, текст `TypeError`/`RPCError`.
- Результаты и события идут в хронологическом порядке — так, как произошли.

## События

Каждое событие Telegram приходит отдельным user-сообщением со своим конвертом, например:

```json
{
  "type": "telethon.tl.types.UpdateNewMessage",
  "data": {
    "message": {
      "type": "telethon.tl.types.Message",
      "data": {"id": 623, "message": "привет", "out": false, "peer_id": {...}}
    },
    "pts": 1686,
    "pts_count": 1
  }
}
```

События копятся буфером (`EVENT_BUFFER_TIMEOUT`) и отдаются пачкой, но в контекст попадают
отдельными сообщениями.

## Поведение при ошибках

- Ошибка сообщает точную причину и подсказки, чтобы исправить вызов.
- Заглушки в `data` (`"..."`, `"id"`, пустые строки) запрещены — только реальные значения.
- Если не хватает данных (например `access_hash`) — их нужно сначала получить другими действиями.
- Если не уверен в методе или полях — `docsearch`, затем `docfetch`.
- Повторять одну и ту же ошибку второй раз запрещено; если разные варианты не сработали,
  агент сообщает собеседнику, что не получилось, и продолжает диалог.
- После успешного запроса результат всё равно анализируется: `missing_*`, `failed_*` и другие
  признаки частичного выполнения требуют разбора и fallback.
