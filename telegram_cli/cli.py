"""CLI for unread Telegram messages."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from telegram_cli import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="telegram-cli",
        description="Read unread Telegram messages from your account. Does not mark them read.",
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
    add_unread_flags(unread, messages_flag=True)

    summarize = sub.add_parser(
        "summarize",
        help="dump unread message text, grouped by chat (alias for unread --messages)",
    )
    add_unread_flags(summarize, messages_flag=False)
    return parser


def add_unread_flags(parser: argparse.ArgumentParser, *, messages_flag: bool) -> None:
    if messages_flag:
        parser.add_argument(
            "--messages",
            action="store_true",
            help="include unread message text (does not mark messages read)",
        )
    parser.add_argument("--json", action="store_true", help="print JSON")
    parser.add_argument("--dms", action="store_true", help="only direct messages and bots")
    parser.add_argument("--include-muted", action="store_true", help="include muted chats")
    parser.add_argument(
        "--include-archived",
        action="store_true",
        help="include archived chats",
    )
    parser.add_argument("--chat", metavar="NAME", help="filter by title, @username, or id")
    parser.add_argument("--limit", type=positive_int, metavar="N", help="max number of chats")
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


def print_whoami(payload: dict, as_json: bool) -> None:
    if as_json:
        json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return
    name = f"{payload['first_name']} {payload['last_name']}".strip() or "unknown"
    username = f" @{payload['username']}" if payload.get("username") else ""
    print(f"{name}{username}  id={payload['id']}")


def print_unread(chats, *, as_json: bool, include_messages: bool) -> None:
    from telegram_cli.client import chats_to_json

    if as_json:
        json.dump(chats_to_json(chats), sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
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
            text = msg.text.replace("\n", " ").strip()
            print(f"{msg.date}  {msg.sender}  {text}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
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
