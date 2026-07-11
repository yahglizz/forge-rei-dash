# Marcus — 24/7 Autonomous Responder

Marcus lives inside the dashboard connector. He watches GoHighLevel for **unread
inbound seller texts** and, only when one exists, classifies it, drafts a reply,
and queues it for your approval. Idle otherwise — "trigger only when needed."

## How it works
1. Every 60s the connector polls GHL conversations.
2. Any conversation with `lastMessageDirection=inbound` + `unreadCount>0` is a trigger.
3. Marcus classifies it with the wholesale toolkit's own classifier
   (`scan_missed_replies.classify`): **DNC › HELP › NRN › PRICE › READY › CONTINUE**.
4. **DNC ("stop"/"remove me")** → auto-suppressed: contact tagged `DNC`, never
   replied to (compliance). Logged in the activity stream.
5. Everything else → a **proposal**: seller's message + suggested reply + action.
   It waits in the **Agent Command Center** inbox.
6. You **Approve & Send** (edit first if you want) or **Dismiss**. Approve sends
   the SMS via GHL and tags the contact (HOT/PRICE/WARM/etc.).

Nothing texts a real seller until you approve — your propose → review → execute rule.

## Controls (Agent Command Center page)
- **Active** toggle — pause/resume Marcus.
- **Auto-send** toggle — when ON, Marcus sends without asking (default OFF).
- **Check now** — force a poll immediately.

## Keys
- **GHL** — reused from `marcus-wholesale-agent/config/ghl.env`. ✅
- **ANTHROPIC_API_KEY** (optional) — add to that same `ghl.env`
  (`ANTHROPIC_API_KEY=sk-ant-...`) to upgrade replies from fixed templates to
  Claude-written, context-aware drafts (model `claude-haiku-4-5`). Restart the
  connector after adding. Status badge shows `claude` vs `templates`.

## Run 24/7
```bash
./install_service.sh     # LaunchAgent: auto-start at login + auto-restart
```
Holds while the Mac is awake. To keep it from sleeping: `caffeinate -s`, or
System Settings → Battery/Lock Screen. For true always-on (Mac off), move the
connector to an always-on host later.

Manual run instead: `./start.sh`.

## API
`/api/marcus/status` · `/api/marcus/proposals`
POST `/api/marcus/approve {id,message?}` · `/dismiss {id}` · `/toggle {enabled?,autoSend?}` · `/poll`

State persists in `marcus_state/*.jsonl` (append logs — no database). `handled.jsonl`
prevents re-proposing the same message; `proposals.jsonl` survives restart.

## Limits / next
- Polling = up to 60s latency. Instant requires a GHL webhook → public URL (tunnel).
- Classifier matches substrings ("stop" → DNC); audit the activity feed for the
  rare false positive (e.g. "stop by"). It only *tags*, easily reversed in GHL.
- Marcus only handles inbound replies today — not new outbound drips (those stay
  in your GHL workflows / blast scripts).
