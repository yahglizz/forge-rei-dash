# forge-telegram

Telegram alerts + tap-to-approve for **FORGE REI OS**. The dashboard pushes alerts
(hot lead, Marcus reply-ready, weekly missed sweep, handoffs/agency) to your phone, and
you tap inline buttons to **Approve & send**, **Dismiss**, or **Hand to Marcus** — without
opening the dashboard. It long-polls Telegram (no public port needed) and runs on the box.

Secrets live here, **outside** the web root (same pattern as `ghl.env`).

---

## Setup (3 steps)

1. **Get a bot token.** Message **@BotFather** on Telegram → `/newbot` → follow the prompts →
   copy the token it gives you into `TELEGRAM_BOT_TOKEN`.
2. **Get your chat id.** DM your new bot once (so it can message you back), then message
   **@userinfobot** — it replies with your numeric id. Put it in `TELEGRAM_CHAT_ID`.
   - For a **team group**: add the bot to the group and use the **group id** instead — it's a
     **negative** number.
3. **Fill the env file.** Copy `config/telegram.env.example` → `config/telegram.env` (same
   dir) and paste your token + chat id in.

## ALLOWED_IDS (who can tap the buttons)

`TELEGRAM_ALLOWED_IDS` is an optional comma-separated list of user/chat ids permitted to tap
the Approve/Dismiss/Hand-to-Marcus buttons. Leave it blank to default to `TELEGRAM_CHAT_ID`.
Set it when a group has multiple people but only some should be able to approve sends.

## Deploy

`deploy/push.sh` ships `config/telegram.env` to the box over SSH (Mac → droplet only),
exactly like `ghl.env`. The secret never travels through git or chat.

## NEVER commit the real telegram.env / token.

The real `config/telegram.env` is git-ignored (see `.gitignore` here and in `config/`).
Only `config/telegram.env.example` is tracked. Never paste the bot token in chat or commit it.
