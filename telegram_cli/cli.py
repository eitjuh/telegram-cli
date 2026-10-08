"""CLI for reading Telegram messages: unread chats, or any chat's history."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timedelta, timezone

from telegram_cli import __version__

_RELATIVE = re.compile(r"^(\d+)\s*([mhdw])$")
_UNITS = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="telegram-cli",
        description=(
            "Read Telegram messages from your account: unread chats, or any "
            "chat's recent history. Never marks anything read."
        ),
    )
    parser.add_argument("--version", action="version", version=f"telegram-cli {__version__}")
    sub = parser.add_subparsers(dest="command")

    login = sub.add_parser("login", help="log in (api_id, api_hash, phone code)")
    login.add_argument("--api-id", help="Telegram API ID from https://my.telegram.org")
    login.add_argument("--api-hash", help="Telegram API hash")

    whoami = sub.add_parser("whoami", help="show the logged-in account")
    whoami.add_argument("--json", action="store_true", help="print JSON")

    logout = sub.add_parser("logout", help="delete the local session")
    logout.add_argument(
        "--forget",
        action="store_true",
        help="also delete saved api_id/api_hash",
    )

    unread = sub.add_parser("unread", help="list unread chats")
    unread.add_argument(
        "--messages",
        action="store_true",
        help="include unread message text (does not mark messages read)",
    )
    add_filter_flags(unread)

    summarize = sub.add_parser(
        "summarize",
        help="dump unread message text, grouped by chat (alias for unread --messages)",
    )
    add_filter_flags(summarize)

    chats = sub.add_parser("chats", help="list your chats, read or not")
    add_filter_flags(chats, chat=False, per_chat=False)

    messages = sub.add_parser(
        "messages",
        help="dump recent messages from a chat (or all chats), read or not",
    )
    messages.add_argument(
        "--since",
        type=parse_when,
        metavar="WHEN",
        help="only messages after WHEN: 2026-10-01, '2026-10-01 14:00', or 2d/12h/30m ago",
    )
    messages.add_argument(
        "--before",
        type=parse_when,
        metavar="WHEN",
        help="only messages before WHEN (same formats as --since)",
    )
    add_filter_flags(messages)
    return parser


def add_filter_flags(
    parser: argparse.ArgumentParser, *, chat: bool = True, per_chat: bool = True
) -> None:
    parser.add_argument("--json", action="store_true", help="print JSON")
    parser.add_argument("--dms", action="store_true", help="only direct messages and bots")
    parser.add_argument("--include-muted", action="store_true", help="include muted chats")
    parser.add_argument(
        "--include-archived",
        action="store_true",
        help="include archived chats",
    )
    if chat:
        parser.add_argument(
            "--chat",
            metavar="NAME",
            help="one chat, by title, @username, or id (ignores the muted/archived/dms filters)",
        )
    parser.add_argument("--limit", type=positive_int, metavar="N", help="max number of chats")
    if per_chat:
        parser.add_argument(
            "--per-chat",
            type=positive_int,
            default=50,
            metavar="N",
            help="max messages per chat when dumping text (default: 50)",
        )


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected an integer, got {value!r}") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed


def parse_when(value: str) -> datetime:
    """A point in time: ISO date/datetime in local time, or an age like 2d/12h/30m."""
    raw = value.strip()
    relative = _RELATIVE.match(raw)
    if relative:
        amount = int(relative.group(1))
        unit = _UNITS[relative.group(2)]
        return datetime.now(timezone.utc) - timedelta(**{unit: amount})
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"expected a date like 2026-10-01, '2026-10-01 14:00', or an age like "
            f"2d/12h/30m, got {value!r}"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def print_whoami(payload: dict, as_json: bool) -> None:
    if as_json:
        json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return
    name = f"{payload['first_name']} {payload['last_name']}".strip() or "unknown"
    username = f" @{payload['username']}" if payload.get("username") else ""
    print(f"{name}{username}  id={payload['id']}")


def print_json(chats) -> None:
    from telegram_cli.client import chats_to_json

    json.dump(chats_to_json(chats), sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def print_message(msg) -> None:
    text = msg.text.replace("\n", " ").strip()
    print(f"{msg.date}  {msg.sender}  {text}")


def print_unread(chats, *, as_json: bool, include_messages: bool) -> None:
    if as_json:
        print_json(chats)
        return
    if not chats:
        print("No unread messages.")
        return
    if not include_messages:
        width = max(len(str(c.unread_count)) for c in chats)
        for chat in chats:
            print(f"{chat.unread_count:>{width}}  {chat.title}")
        return
    total = sum(c.unread_count for c in chats)
    print(f"{len(chats)} chats, {total} unread")
    print()
    for i, chat in enumerate(chats):
        if i:
            print()
        shown = f", showing {len(chat.messages)}" if chat.truncated else ""
        print(f"{chat.title}  ({chat.unread_count} unread{shown})")
        if not chat.messages:
            print("  (no message text)")
            continue
        for msg in chat.messages:
            print_message(msg)


def print_chat_list(chats, *, as_json: bool) -> None:
    if as_json:
        print_json(chats)
        return
    if not chats:
        print("No chats.")
        return
    width = max(len(str(c.unread_count)) for c in chats)
    for chat in chats:
        handle = f"  @{chat.username}" if chat.username else ""
        print(f"{chat.unread_count:>{width}}  {chat.kind:<7}  {chat.title}{handle}")


def print_history(chats, *, as_json: bool) -> None:
    if as_json:
        print_json(chats)
        return
    if not chats:
        print("No messages.")
        return
    for i, chat in enumerate(chats):
        if i:
            print()
        unread = sum(1 for m in chat.messages if m.unread)
        older = ", older not shown" if chat.truncated else ""
        print(f"{chat.title}  ({len(chat.messages)} messages, {unread} unread{older})")
        if not chat.messages:
            print("  (no messages)")
            continue
        for msg in chat.messages:
            print_message(msg)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    if args.command == "messages" and args.since and args.before and args.before <= args.since:
        parser.error("--before must be later than --since")
    try:
        return asyncio.run(_dispatch(args))
    except KeyboardInterrupt:
        return 130


async def _dispatch(args: argparse.Namespace) -> int:
    from telegram_cli import client as tg

    if args.command == "login":
        payload = await tg.login(args.api_id, args.api_hash)
        print_whoami(payload, as_json=False)
        print(f"Session saved to {tg.SESSION_PATH}.session")
        return 0
    if args.command == "whoami":
        print_whoami(await tg.whoami(), as_json=args.json)
        return 0
    if args.command == "logout":
        tg.logout(forget=args.forget)
        print("Logged out.")
        return 0
    if args.command == "chats":
        chats = await tg.list_chats(
            dms_only=args.dms,
            include_muted=args.include_muted,
            include_archived=args.include_archived,
            limit=args.limit,
        )
        print_chat_list(chats, as_json=args.json)
        return 0
    if args.command == "messages":
        chats = await tg.fetch_history(
            chat=args.chat,
            dms_only=args.dms,
            include_muted=args.include_muted,
            include_archived=args.include_archived,
            since=args.since,
            before=args.before,
            limit=args.limit,
            per_chat=args.per_chat,
        )
        print_history(chats, as_json=args.json)
        return 0

    include_messages = True if args.command == "summarize" else args.messages
    chats = await tg.fetch_unread(
        include_messages=include_messages,
        dms_only=args.dms,
        include_muted=args.include_muted,
        include_archived=args.include_archived,
        chat=args.chat,
        limit=args.limit,
        per_chat=args.per_chat,
    )
    print_unread(chats, as_json=args.json, include_messages=include_messages)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
