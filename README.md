# telegram-cli

List unread Telegram chats and dump their messages. Messages are **not** marked read.

This logs in as you via Telegram's user API (MTProto). A bot cannot see your private unreads, and the desktop app's local files are not usable as a database.

```bash
python3 -m pip install -e .
# or, from this repo with no install:
python3 -m telegram_cli --help
```

## Setup

1. Open [my.telegram.org](https://my.telegram.org) → **API development tools** → create an app. Copy `api_id` and `api_hash`.
2. Put them in `~/.config/telegram-cli/config.json` (create the directory if needed):

```json
{
  "api_id": 12345678,
  "api_hash": "your-api-hash"
}
```

`chmod 600` that file. Do not put these values in the git repo. `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` override the file if set.
3. Log in (phone number, then the code Telegram sends you):

```bash
telegram-cli login
```

The session is stored next to the config as `account.session`. That file is equivalent to being logged in — do not share it. Override the directory with `TELEGRAM_CLI_HOME`.

## Usage

```bash
telegram-cli whoami

# unread chats (muted and archived are skipped)
telegram-cli unread

# message text, grouped by chat — feed this to an LLM to summarize
telegram-cli summarize
telegram-cli unread --messages

telegram-cli summarize --json
telegram-cli summarize --dms
telegram-cli summarize --chat Alice
telegram-cli summarize --include-muted --include-archived
telegram-cli summarize --limit 10 --per-chat 20

telegram-cli logout
telegram-cli logout --forget   # also drop saved api_id/api_hash
```

Secret chats are not included. Re-run `login` if the session expires.
