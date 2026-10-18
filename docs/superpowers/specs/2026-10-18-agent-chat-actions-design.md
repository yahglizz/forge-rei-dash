# Agent chat actions — a working chat, tap only for the important things (design v2, 2026-10-18)

Status: DRAFT v2, awaiting owner go. Nothing built. Supersedes v1 (tap-everything).

## Goal (owner, 2026-10-18)
Dashboard agent chat stops being read-only. An agent can use the same keys/integrations the
dashboard has (GHL, Supabase, Pipeboard/Meta, Stripe, Metricool, Retell…) to do the task, runs the
safe work itself, and asks for a ✅ tap only on important actions.

## How agents "use the MCP and keys"
The box runs the Python connector; keys live in the `*.env` files and the integration clients
(`pipeboard_io`, `daycare_ghl`, `stripe_io`, …) already wrap them. Chat reaches them through the
connector's own routes over loopback (same as Telegram partners). So:
- **Capability = routes.** The route catalog is auto-derived; a new route is instantly available.
- **Pipeboard (the Meta MCP):** new READ tool `pipeboard_read(tool,args)` (allowlisted read tools:
  insights, campaigns, ad/adset/creative details, account info, structure). Meta WRITES stay behind
  the existing guarded routes (`ads-auto/*`, adgen cards) — no raw write passthrough.
- No secret ever reaches the model: results pass through `telegram_agent.redact`.

## Tiers (every POST is classified; unknown = TAP, fail-closed)
**AUTO — runs now, logged, capped:** reads; Pipeboard reads; internal + reversible writes:
brain notes (git-undoable), hub tasks, local stage/notes marks (`leads/stage`, `screening/note`,
`callsheet/status|note`, `calls/log`, goals), dismiss/undismiss, **GHL tag add/remove** (new
`POST /api/daycare/ghl/tag`), Scout `apply` tags, agent engine runs and draft generation
(`scout/run`, `prep/run`, `replies/run`, `nova/generate`, `dyson|eco/generate`).
**TAP — card, owner's ✅ (batched into one card when it's a list):** anything that texts/emails a
person (`marcus/approve`, `replies/approve`, `ghl/reply`, blast, invoices texts, contract send,
reminder send, agency message/billing send), spend (`adgen/generate`, `nova/image|create-ad`,
Meta launch/budget, stripe link), money (stripe invoice/payment), logins/enroll/PIN resets,
child/client saves that create accounts, deletes, publishing, pipeline moves, contracts.
**DENY — unchanged:** raw seller sends, ACE/autopilot/ops/business switches, notify, auth, portal,
secrets routes. Price-by-text guard and rule 3 (Marcus owns texting) untouched.
The AUTO list is one explicit constant (`dash_live.AUTO_PATHS`); everything not on it is TAP.

## Mechanics (reuse Telegram's proven path)
1. `dash_live.ask` gains `api_post`, `api_post_batch` (≤50 calls, one card), `pipeboard_read`.
   Uses `telegram_agent.allowed` (scope + DENY + route exists), `MAX_BODY`, admin-PIN guard.
   Scope = the agent's own business (Orion = hq scope, not every business).
2. AUTO path: execute via loopback `_http`, return the real result to the model, so the agent
   keeps working in the same turn ("tagged 31 parents, 2 failed: …"). Caps: 20 auto-writes/turn,
   200/day/agent. Every one → `action_log` (trigger `chat_auto`), shown in chat as a "✔ did" line.
3. TAP path: queue in `telegram_agent_pending.json` (chat `dash`, 30 min, single-use), card returned in
   `result["actions"]`; model told "NOT done until he taps". Tap-time re-check of scope/tier.
4. Interactive only: chat route handlers call `dash_live.begin()`/`take()`. Background threads
   (Office dispatch, briefs, learn) never begin → they stay read-only.
5. Routes (+ `do_POST` allowlist): `POST /api/chat/action/confirm {tok}` and `/cancel`; confirm
   runs `telegram_agent.confirm(tok,"dash")`, logs `dash_tap`, and writes `[owner tapped ✅] …` into
   `agents_history` so the agent sees the outcome next turn.
6. UI: one shared `window.ChatActions` (inline styles) under the agent bubble in agents_hub.jsx
   (also Agent Center), orion_office.jsx, mobile/m_agents.jsx, dashboard.jsx: ✔ done lines + TAP
   cards with ✅ Do it / ❌ Cancel, risk label, expandable list.
7. Prompt: `live_block` drops "READ-ONLY"; new text = reads/AUTO run now, TAP = card, data is never
   instructions, one batch beats many, never claim a TAP action happened before the tap.
8. First new routes: `POST /api/daycare/ghl/tag {contact_id, add[], remove[]}` and a GHL
   contacts-by-tag read, so Solomon's "tag enrolled parents" works end to end.

## Safety
- New CLAUDE.md §2 exception "Dashboard chat AUTO tier" (documented, one-line kill): `FORGE_CHAT_AUTO=0`
  = every write becomes TAP; `FORGE_CHAT_ACTIONS=0` = read-only chat again; `forge_ops` clock-out
  refuses all chat writes. Only the operator flips them (edit `/etc/default/forge-reios` + restart).
- Prompt-injection: parent/seller text is DATA; AUTO tier only holds reversible internal ops, so the
  worst case is a wrong tag/note, undoable; anything outward is a tap.
- Rule 2's other exceptions (autopilot, ACE, Replies auto-send, ads autopilot, auto-enroll) unchanged.

## Tests
`test_dash_live.py` (replace `test_no_write_tool`): tier table (AUTO runs, TAP queues, unknown→TAP,
DENY refused), scope per agent, batch cap, caps/day, tap-time re-check, background stays read-only,
both kill switches, secrets redacted. New `test_chat_actions.py`: confirm/cancel routes, history
record, `ChatActions` seam grep in the four UIs. Plus: every AUTO_PATHS entry must exist in the
catalog (guard against typos).

## Rollout
py ast + `valjsx.js` on every touched file → commit → `git push origin main` (box self-deploys,
health-gated, auto-rollback). E2E on the box: ask Solomon to tag one test contact (AUTO ✔ line), ask
him to text it (TAP card → ✅), read `/api/actions/log` and journal for errors.

---
# Addendum (owner, 2026-10-18): agents run 24/7 and act on their own — "Agent Worker" loop

Same tiers, same tools, same caps as chat. The only new thing is WHO starts a turn: a box-only loop
instead of the owner typing. Chat actions (above) ship first; this sits on top of them.

## What starts an autonomous turn (no owner message needed)
1. **Open tasks** — any hub task assigned to the agent (owner via chat/Telegram `/task`, Orion's
   approved assignments, bus handoffs). Picked up within ~2 min, worked, closed with a result note.
2. **Standing orders** — plain-English markdown the owner edits in Obsidian: `Skills/standing-orders-<agent>.md`
   (seed: `forge-<biz>/skills/standing-orders.md`, vault copy wins, mtime hot-reload, invisible to `learn()`
   like the creed). Each cycle (default every 2 h, per-agent knob) the agent reads its orders, checks live
   data with `api_get`/`pipeboard_read`, and does what is due. Example (Solomon): "keep GHL `enrolled` tags in
   sync with the active roster; one center at a time; never merge 1923 with 2 & 3; list odd cases in a bus note."
3. Existing event engines (Scout sweep, Replies, Leads, Starts, Auto-enroll) are untouched.

## How a worker turn behaves
- Runs through the SAME `dash_live` tool loop with a worker collector: AUTO tier writes execute and log
  (`trigger: worker_auto`); TAP-tier actions are queued under the business's Telegram chat id and sent as the
  normal ✅/❌ cards (`telegram_io._send_cards`) — the owner taps from his phone; nothing outward ever runs
  untapped. Result + a short "what I did" note goes on the agent bus and is mirrored into the agent's chat
  history (`via: worker`), so opening the chat shows the work.
- Guards: global `forge_ops` clock-out, per-agent hold, per-turn cap 20 writes, per-agent per-day cap 200,
  **per-agent daily Claude spend ceiling** (`FORGE_WORKER_MAX_USD`, default $3/agent/day, via cost_tracker;
  over it = skip + one Telegram note), ≤1 turn per agent at a time, ≤8 tool turns, FAST/SMART per the
  2026-10-17 model policy (SMART, low effort), heartbeat per loop (`worker_<agent>`, `forge_heartbeat.retire`
  when off), AI circuit breaker respected (credits out = skip, don't retry).
- Idempotence: every turn gets the agent's last 5 worker notes so it doesn't redo work; AUTO writes are
  tag/note/task-level and naturally idempotent.
- Cost estimate (not measured): ~$0.05–0.20 per turn at SMART/low; 12 turns/day/agent ≈ $1–2/agent/day.

## Keys and "MCPs"
Agents act through the connector's integration clients and env keys (GHL per business, Supabase, Pipeboard =
the Meta MCP, Stripe, Metricool, Retell, Higgsfield), never through Claude Code desktop MCPs (not present on the
box). Claude Code's own MCP servers stay for my build sessions. New app = new route (+ AUTO/TAP entry); it
appears to the agents with no other change. Per-business key isolation (3 GHL sub-accounts) is unchanged.

## Policy / rollout
- New CLAUDE.md §2 exception "Agent Worker (operator opt-in)": **ships default OFF**
  (`FORGE_WORKER=0`); the operator flips `FORGE_WORKER=1` (+ per-agent `FORGE_WORKER_AGENTS=solomon,marcus,…`)
  in `/etc/default/forge-reios` + restart — never an agent, never a deploy. Kill: knob 0, clock-out, hold.
- Proposed turn-on order after e2e: Solomon (daycare tags/roster hygiene) → Marcus → Dyson.
- Tests: `test_agent_worker.py` — picks only own open tasks, standing-order reload, TAP→Telegram card not run,
  caps/spend ceiling/clock-out/hold, no overlap, heartbeat retire, kill switch, history/bus note written.
