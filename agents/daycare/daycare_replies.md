# Reply Desk — Family Reply Drafts (no brain of its own)

> Code refs are relative to `forge rei/`. Verified against code 2026-09-23.

## 1. Identity

| | |
|---|---|
| Business | Daycare · hub id `daycare_replies` · emoji 💬 · `chatVia: "solomon"` |
| Job | Every 5 min: drafts the next text back to any parent/guardian owed a reply, in the center's real texting voice, grounded in the verified fact sheet. Sends nothing itself. |
| Engine | `forge rei/daycare_replies.py` (no engine object — pure functions + a state file), self-check `forge rei/test_daycare_replies.py` |

## 2. Triggers

**Scheduled loop**

| Field | Value |
|---|---|
| Thread | `daycare_replies` (`connector.py`, started next to the Lead Desk thread) |
| Gate | `FORGE_MARCUS` != `0` **and** `FORGE_DAYCARE_REPLIES` != `0` (default on; `0` retires the heartbeat) |
| Interval | `FORGE_DAYCARE_REPLIES_INTERVAL`, default 300 s |
| Clock-out | whole sweep skipped on `forge_ops.paused()` |
| Heartbeat | `daycare_replies` |
| Knobs | `FORGE_DAYCARE_REPLY_MODEL` (`claude-sonnet-5`) · `FORGE_DAYCARE_REPLY_GRACE_MIN` (5) · `FORGE_DAYCARE_REPLY_MAX` (8 Claude calls/sweep) |

**Telegram:** no `/replydesk` command and no name trigger — Solomon answers for it (`solomon, …`).

**HTTP** — daycare router, every route needs the secure check + a daycare session:

| Method | Routes |
|---|---|
| GET | `/api/daycare/replies` |
| POST | `/api/daycare/replies/run` (sweep now, sends nothing) · `/replies/approve` (the owner's send tap) · `/replies/dismiss` |

**Handoffs:** none in — it reads the daycare GHL location directly, the same account the Lead Desk and the speed-to-lead website workflow use.

**UI:** no page yet — visible as the Agent Control Center row `daycare_replies` (chats through Solomon) and via the routes above. `pixel_office.py`'s roster does not include it (only the 7 chat characters).

## 3. Reads, in order

`daycare_replies._system()`:
1. `agent_creed.block("daycare")` — the creed outranks everything below it.
2. `daycare_context.context_block()` — `forge-daycare/skills/daycare-context.md` [:6000].
3. `forge-daycare/skills/daycare-parent-reply.md` — the decision rubric + the verified fact sheet (addresses, phones, hours, offer status, what to answer vs. confirm vs. escalate). Facts here win over the context brief if they ever disagree.
4. `forge-daycare/skills/daycare-voice.md` — how ATOB actually texts, built from 136 real outbound SMS.

Per-thread user prompt: last 15 messages of the conversation, parent/child first names, which of the three centers, current ET time. Missing either skill file raises rather than drafting blind.

## 4. Outputs / writes

- `marcus_state/daycare_replies.json` — one row per contact: `pending` (needs the owner's tap), `sent`, `dismissed`, `stale` (someone answered in GHL since), `opted_out`, `no_reply`.
- Nothing else. No bus messages, no vault writes, no GHL writes on the read path.

## 5. Autonomy & gates — this is the part that matters

- **Draft-only.** Every row is a proposal; nothing sends without `/api/daycare/replies/approve`.
- **Yields to the GHL automations first** (`gate()`, pure, no Claude): a thread is skipped when —
  - the last message is already outbound (a workflow or a person answered);
  - the parent sent STOP/HELP/START/etc. — the carrier/GHL keyword auto-replies own those words;
  - the parent has opted out or is DND — permanent, never revisited;
  - a fresh website lead is still inside the speed-to-lead window (3-min workflow send, or the overnight `speed-to-lead-queued` → 8am flush) — the workflow owns that first text, not this;
  - the inbound is younger than `FORGE_DAYCARE_REPLY_GRACE_MIN` — lets a workflow's stop-on-response or live staff typing back go first;
  - the thread isn't SMS, or the inbound is older than 7 days (the Lead Desk's job, not this one's).
- **Code-level draft flags** (`flags()`, always run, never bypassable by the model): a phone number not on the fact sheet (`unverified_phone`), a dollar figure (`money`), an emoji, or a draft over ~3 SMS segments (`long`).
- **`approve()` re-checks the live thread**, not the cached draft: refuses outside 8am–9pm ET, refuses and retires the draft if anyone (staff or a workflow) replied since it was written, refuses if the parent opted out in the meantime. Logs the send via `action_log`.
- **`escalate`** category (safety, custody, medical, complaint, billing dispute) never gets a substantive draft — only a short holding line; the owner calls.
- Kill: `FORGE_DAYCARE_REPLIES=0`, clock out, `FORGE_MARCUS=0`, or no Anthropic key. A billing/auth error from Anthropic aborts the sweep mid-way (shows on the heartbeat) rather than silently drafting nothing.

## 6. Self-improvement

None. `daycare-voice.md` and `daycare-parent-reply.md` are owner-edited skill files (mtime hot-reload via `daycare_context.load_skill`), not a `learn()` loop — they don't drift on their own.

## 7. Chat & tasks

- `/api/hub/chat {agentId:"daycare_replies"}` → Solomon's brain (`_director_chat`) with the Reply Desk's live state injected the same way Follow-up's is injected into Marcus's chat.
- No dedicated task queue; a task filed for `daycare_replies` shows in Solomon's open-tasks block.

## 8. Cost

Claude: yes — up to `FORGE_DAYCARE_REPLY_MAX` (8) Sonnet 5 calls per 5-min sweep, only for threads that pass `gate()`. Bucket: thread name `daycare_replies` in `cost_tracker`.

## 9. Verify it's alive

```bash
curl -s localhost:7799/api/agents/registry | jq '.agents[]|select(.id=="daycare_replies")|{status,pendingApprovals,lastRun,lastError}'
curl -s localhost:7799/api/system/health | jq '.loops[]|select(.loop=="daycare_replies")'
curl -s localhost:7799/api/daycare/replies | jq '{lastRunAt,lastSweep,error,pending:[.pending[]|{center,category,flags}]}'
```
