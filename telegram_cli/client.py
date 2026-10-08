"""Telegram session, login, and message fetching."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from telethon import TelegramClient, utils
from telethon.errors import AuthKeyUnregisteredError, SessionRevokedError

CONFIG_DIR = Path(
    os.environ.get("TELEGRAM_CLI_HOME", Path.home() / ".config" / "telegram-cli")
)
CONFIG_PATH = CONFIG_DIR / "config.json"
SESSION_PATH = CONFIG_DIR / "account"


@dataclass
class Message:
    id: int
    date: str
    sender: str
    text: str
    outgoing: bool
    unread: bool


@dataclass
class Chat:
    id: int
    title: str
    username: str | None
    kind: str
    unread_count: int
    muted: bool
    archived: bool
    last_message_date: str | None = None
    truncated: bool = False
    messages: list[Message] = field(default_factory=list)


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        data = json.loads(CONFIG_PATH.read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid config file: {CONFIG_PATH}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"invalid config file: {CONFIG_PATH}")
    return data


def save_config(api_id: int, api_hash: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"api_id": api_id, "api_hash": api_hash}, indent=2) + "\n"
    CONFIG_PATH.write_text(payload)
    CONFIG_PATH.chmod(0o600)


def resolve_api_credentials(api_id: str | None, api_hash: str | None) -> tuple[int, str]:
    cfg = load_config()
    raw_id = api_id or os.environ.get("TELEGRAM_API_ID") or cfg.get("api_id")
    raw_hash = api_hash or os.environ.get("TELEGRAM_API_HASH") or cfg.get("api_hash")
    if raw_id is None:
        raw_id = _prompt("API ID (from https://my.telegram.org)")
    if not raw_hash:
        raw_hash = _prompt("API hash")
    try:
        parsed_id = int(raw_id)
    except (TypeError, ValueError) as exc:
        raise SystemExit("api_id must be an integer") from exc
    raw_hash = str(raw_hash).strip()
    if not raw_hash:
        raise SystemExit("api_hash is required")
    return parsed_id, raw_hash


def _prompt(label: str) -> str:
    if not sys.stdin.isatty():
        raise SystemExit(
            f"{label} is required; pass --api-id/--api-hash or set "
            "TELEGRAM_API_ID and TELEGRAM_API_HASH"
        )
    return input(f"{label}: ").strip()


def _client(api_id: int, api_hash: str) -> TelegramClient:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return TelegramClient(str(SESSION_PATH), api_id, api_hash)


async def connect_authorized() -> TelegramClient:
    cfg = load_config()
    api_id = os.environ.get("TELEGRAM_API_ID") or cfg.get("api_id")
    api_hash = os.environ.get("TELEGRAM_API_HASH") or cfg.get("api_hash")
    if api_id is None or not api_hash:
        raise SystemExit("Not configured. Run: telegram-cli login")
    try:
        api_id = int(api_id)
    except (TypeError, ValueError) as exc:
        raise SystemExit("saved api_id is not an integer; run telegram-cli login") from exc
    client = _client(api_id, str(api_hash))
    try:
        await client.connect()
    except OSError as exc:
        raise SystemExit(f"could not start Telegram session ({exc})") from exc
    try:
        authorized = await client.is_user_authorized()
    except (AuthKeyUnregisteredError, SessionRevokedError) as exc:
        await client.disconnect()
        raise SystemExit("Session expired. Run: telegram-cli login") from exc
    if not authorized:
        await client.disconnect()
        raise SystemExit("Not logged in. Run: telegram-cli login")
    return client


async def login(api_id: str | None, api_hash: str | None) -> dict:
    parsed_id, parsed_hash = resolve_api_credentials(api_id, api_hash)
    save_config(parsed_id, parsed_hash)
    client = _client(parsed_id, parsed_hash)
    await client.start()
    try:
        me = await client.get_me()
    finally:
        await client.disconnect()
    return _user_payload(me)


async def whoami() -> dict:
    client = await connect_authorized()
    try:
        me = await client.get_me()
    finally:
        await client.disconnect()
    return _user_payload(me)


def logout(forget: bool) -> None:
    for path in (
        Path(str(SESSION_PATH) + ".session"),
        Path(str(SESSION_PATH) + ".session-journal"),
    ):
        path.unlink(missing_ok=True)
    if forget:
        CONFIG_PATH.unlink(missing_ok=True)


def _user_payload(me) -> dict:
    return {
        "id": me.id,
        "first_name": me.first_name or "",
        "last_name": me.last_name or "",
        "username": me.username,
        "phone": me.phone,
    }


def dialog_kind(dialog) -> str:
    if dialog.is_user:
        return "bot" if getattr(dialog.entity, "bot", False) else "user"
    if dialog.is_group:
        return "group"
    if dialog.is_channel:
        return "channel"
    return "unknown"


def is_muted(dialog) -> bool:
    settings = getattr(dialog.dialog, "notify_settings", None)
    mute_until = getattr(settings, "mute_until", None) if settings else None
    if mute_until is None:
        return False
    if isinstance(mute_until, datetime):
        if mute_until.tzinfo is None:
            mute_until = mute_until.replace(tzinfo=timezone.utc)
        return mute_until > datetime.now(timezone.utc)
    if isinstance(mute_until, (int, float)):
        return mute_until > datetime.now(timezone.utc).timestamp()
    return False


def matches_chat(dialog, needle: str) -> bool:
    needle = needle.strip()
    if needle.startswith("@"):
        needle = needle[1:]
    if needle.lstrip("-").isdigit() and str(dialog.id) == needle:
        return True
    username = getattr(dialog.entity, "username", None) or ""
    if needle.lower() == username.lower():
        return True
    return needle.lower() in (dialog.title or "").lower()


def message_text(message) -> str:
    text = (message.message or "").strip()
    if text:
        return text
    if message.photo:
        return "[photo]"
    if message.sticker:
        return "[sticker]"
    if message.voice:
        return "[voice]"
    if message.video_note:
        return "[video note]"
    if message.video:
        return "[video]"
    if message.document:
        name = message.file.name if message.file else None
        return f"[file: {name}]" if name else "[file]"
    if message.contact:
        return "[contact]"
    if message.geo or message.venue:
        return "[location]"
    if message.poll:
        return "[poll]"
    return "[media]"


def sender_name(message) -> str:
    if message.out:
        return "You"
    sender = message.sender
    if sender is None:
        return "Unknown"
    name = utils.get_display_name(sender)
    return name or "Unknown"


def local_stamp(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _read_max_id(dialog) -> int:
    return getattr(dialog.dialog, "read_inbox_max_id", 0) or 0


def _chat_from_dialog(dialog) -> Chat:
    return Chat(
        id=dialog.id,
        title=dialog.title or "",
        username=getattr(dialog.entity, "username", None),
        kind=dialog_kind(dialog),
        unread_count=dialog.unread_count,
        muted=is_muted(dialog),
        archived=bool(dialog.archived),
        last_message_date=local_stamp(dialog.date) if dialog.date else None,
    )


def _to_message(msg, read_max_id: int) -> Message:
    return Message(
        id=msg.id,
        date=local_stamp(msg.date) if msg.date else "",
        sender=sender_name(msg),
        text=message_text(msg),
        outgoing=bool(msg.out),
        unread=not msg.out and msg.id > read_max_id,
    )


async def _select_dialogs(
    client: TelegramClient,
    *,
    chat: str | None,
    dms_only: bool,
    include_muted: bool,
    include_archived: bool,
) -> list:
    """Dialogs to look at, newest activity first.

    An explicit --chat wins over the muted/archived/DM filters: if you name a
    chat you want it, whatever its notification settings are.
    """
    dialogs = await client.get_dialogs()
    if chat:
        matches = [d for d in dialogs if matches_chat(d, chat)]
        if not matches:
            raise SystemExit(f"no chat matched {chat!r}")
        if len(matches) > 1:
            names = ", ".join(f"{d.title} ({d.id})" for d in matches[:10])
            extra = " ..." if len(matches) > 10 else ""
            raise SystemExit(f"multiple chats matched {chat!r}: {names}{extra}")
        return matches
    selected = []
    for dialog in dialogs:
        if is_muted(dialog) and not include_muted:
            continue
        if dialog.archived and not include_archived:
            continue
        if dms_only and dialog_kind(dialog) not in {"user", "bot"}:
            continue
        selected.append(dialog)
    return selected


async def list_chats(
    *,
    dms_only: bool,
    include_muted: bool,
    include_archived: bool,
    limit: int | None,
) -> list[Chat]:
    client = await connect_authorized()
    try:
        dialogs = await _select_dialogs(
            client,
            chat=None,
            dms_only=dms_only,
            include_muted=include_muted,
            include_archived=include_archived,
        )
        chats = [_chat_from_dialog(d) for d in dialogs]
        return chats[:limit] if limit is not None else chats
    finally:
        await client.disconnect()


async def fetch_unread(
    *,
    include_messages: bool,
    dms_only: bool,
    include_muted: bool,
    include_archived: bool,
    chat: str | None,
    limit: int | None,
    per_chat: int,
) -> list[Chat]:
    client = await connect_authorized()
    try:
        dialogs = await _select_dialogs(
            client,
            chat=chat,
            dms_only=dms_only,
            include_muted=include_muted,
            include_archived=include_archived,
        )
        chats: list[Chat] = []
        for dialog in dialogs:
            if dialog.unread_count <= 0:
                continue
            item = _chat_from_dialog(dialog)
            if include_messages:
                cap = min(dialog.unread_count, per_chat)
                read_max_id = _read_max_id(dialog)
                raw = await client.get_messages(
                    dialog.input_entity, limit=cap, min_id=read_max_id
                )
                item.messages = [
                    _to_message(msg, read_max_id)
                    for msg in reversed(raw)
                    if not getattr(msg, "action", None)
                ]
                item.truncated = dialog.unread_count > cap
            chats.append(item)
            if limit is not None and len(chats) >= limit:
                break
        return chats
    finally:
        await client.disconnect()


async def fetch_history(
    *,
    chat: str | None,
    dms_only: bool,
    include_muted: bool,
    include_archived: bool,
    since: datetime | None,
    before: datetime | None,
    limit: int | None,
    per_chat: int,
) -> list[Chat]:
    """Recent messages per chat, read or not. Newest `per_chat` within the window."""
    client = await connect_authorized()
    try:
        dialogs = await _select_dialogs(
            client,
            chat=chat,
            dms_only=dms_only,
            include_muted=include_muted,
            include_archived=include_archived,
        )
        chats: list[Chat] = []
        for dialog in dialogs:
            if since is not None and dialog.date and _aware(dialog.date) <= since:
                continue  # last activity predates the window; skip the round trip
            raw, truncated = await _history(
                client, dialog, since=since, before=before, cap=per_chat
            )
            if not raw and not chat:
                continue
            item = _chat_from_dialog(dialog)
            read_max_id = _read_max_id(dialog)
            item.messages = [_to_message(msg, read_max_id) for msg in raw]
            item.truncated = truncated
            chats.append(item)
            if limit is not None and len(chats) >= limit:
                break
        return chats
    finally:
        await client.disconnect()


async def _history(
    client: TelegramClient,
    dialog,
    *,
    since: datetime | None,
    before: datetime | None,
    cap: int,
) -> tuple[list, bool]:
    """Walk newest-to-oldest from `before` down to `since`, keeping at most `cap`.

    Returns the kept messages oldest-first and whether older ones were left out.
    """
    messages: list = []
    truncated = False
    async for msg in client.iter_messages(dialog.input_entity, offset_date=before):
        if since is not None and msg.date and _aware(msg.date) <= since:
            break
        if getattr(msg, "action", None):
            continue
        if len(messages) >= cap:
            truncated = True
            break
        messages.append(msg)
    messages.reverse()
    return messages, truncated


def chats_to_json(chats: list[Chat]) -> dict:
    return {
        "unread_total": sum(c.unread_count for c in chats),
        "chats": [asdict(c) for c in chats],
    }
