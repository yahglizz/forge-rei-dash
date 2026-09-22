# ACE — Autonomous Conversation Engine

**Business:** Wholesale (REI) · **Emoji:** ♠️ · **Roster id:** `ace`
**Role:** per-thread conversation state machine.

Tracks where every seller conversation is and which qualifying facts are known,
decides reply-vs-escalate, and builds the call-ready queue.

## Autonomy — where the line sits

Modes `off` / `shadow` / `supervised` / `full`, **default `off`**. In `supervised`
and `full` it auto-texts sellers (capped per day, through `sms_guard`). The Agent
Control Center shows the mode **read-only** — it never flips it. Mode changes are
the operator's call only.

It has no brain of its own — in chat and tasks, **Marcus answers for it** with its
live status as context.

## Where it lives

- **Engine:** `forge rei/ace.py` + `forge rei/conversation_engine.py`
- **State:** `marcus_state/ace.json`, `conversations.json`, `call_ready.json`

## Routes

`/api/ace/state` · `/api/ace/status` · `/api/ace/callready` · `/api/ace/digest`
