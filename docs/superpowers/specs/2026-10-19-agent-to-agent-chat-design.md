# Agent ⇄ agent chat — any agent can call another, visibly (design v1, 2026-10-19)

Status: DRAFT, awaiting owner go. Nothing built. Builds on chat actions (`2026-10-18-agent-chat-actions-design.md`)
and the cross-business READ widening (CLAUDE.md §5 "Agents are not restricted from one another").

## Goal (owner, 2026-10-19)
Agents talk to each other whenever they need, or when the owner asks ("ask Marcus what he thinks").
The conversation is VISIBLE in the chat. Information moves across all businesses.

## What exists (reuse, don't duplicate)
- `agent_collab.py`: Marcus ⇄ Scout only, `[ASK X]` marker, depth 1, "🤝 consulted X" text trace, bus-logged.
- `agents_hub.send_task` / hub tasks / `agent_bus` / `agent_coach`: async, one-way hand-offs.
- `agents_hub._chat(ghl_get, location_id, agent_id, message, …)`: routes to every agent's REAL brain
  (creed + playbook + live tools). This is the engine a consult calls — no new persona code.
- `dash_live` tool loop + `begin()/take()` collector → `done` / `actions` on the reply → `window.ChatActions`.

## Design

### 1. Tool `ask_agent {agent, question}` (dash_live, offered in INTERACTIVE chats only)
Any of the five interactive chats (a collector is open). Not in background runs, briefs, Telegram (phase 2).
- `agent` = a main agent id or a lane id (`agents_hub.main_agent` resolves it): marcus · scout→marcus · dyson ·
  eco→dyson · solomon · orion · midas (refused while its business is archived, with a one-line pointer).
  Not yourself. Unknown id → error listing the valid ones.
- The target answers with its **own brain** through `agents_hub._chat`, called with `consult=True`:
  - **read-only**: a sub-collector `{ro: True}` is installed for the call, so `writes_on()` is False and the
    target gets `api_get`/`route_help`/`find_people` only — no `api_post`, no `pipeboard_read` writes, **no
    `ask_agent`** (depth 1: a consulted agent cannot consult back, no loops).
  - **commands off**: `consult=True` forces `enable_commands=False` in `agents_chat.chat` (Marcus parses
    commands from the message text — a teammate's text must never be a command).
  - the question is wrapped: `[A teammate agent — <Asker> (<business>) — asks you, not the owner. Answer from
    your own data and playbook, short, read-only. Take no action. Attribute facts to their source.]`.
- Answer returned to the asker as a normal tool result (`<data>`, PIN-redacted, clipped 2000 chars), labeled
  `{consultedFrom: "<Target> (<business>)", answer}` so it is attributed, never reported as the asker's own.

### 2. Security
- Consult answer = DATA, not instructions (existing `_DATA_RULE`). It cannot cause an AUTO write by itself:
  **taint propagates** — if the target's sub-collector read anything that taints (anything off `NO_TAINT_PREFIXES`,
  or `thirdPartyText`), the ASKER is tainted for 30 min (all its writes become ✅ cards). The target itself is NOT
  persistently tainted by being asked (sub-collector flag only; no `chat_taint.json` write for the target).
- Writes stay in each agent's own business, tiers unchanged. A consult never writes. To make another agent DO
  something the asker files a hub task (exists; cross-business = ✅ card). The prompt says so.
- Caps: ≤3 consults per owner message; ≤30 per asker per ET day (`marcus_state/chat_auto_counts.json` key
  `consult:<agent>`); refused when `cost_tracker.over_ceiling(asker)`, on `forge_ops` clock-out, or while the AI
  circuit is open. Each consult is one SMART call (+ its tool turns) billed to the operator thread, est. $0.02–0.10.
- Kill: `FORGE_CHAT_CONSULT=0` (tool removed; `[ASK X]` marker path untouched), `FORGE_CHAT_ACTIONS=0`, clock-out.
  Only the operator flips them.
- CLAUDE.md §2 gets a one-paragraph exception "Dashboard agent consults (ON by default)": read-only, internal,
  zero outward effect, so rule 2 holds.

### 3. Visible in the chat
- `take()` returns a third list `consults: [{from, fromId, to, toId, business, q, a, ok, error?, ms, tainted}]`;
  `_chat_with_actions` merges it (condition widened). Each consult is added the moment it finishes.
- `window.ChatActions` gains a `consults` prop: under the asker's bubble, a labeled thread — `🤝 Solomon → Marcus`
  question bubble, then `Marcus → Solomon` answer bubble (agent-name chips in the existing agent colours),
  long answers collapse behind "show all", a failed consult shows the reason. Inline styles, dark + light,
  mobile-safe. Wired where `actions/done` already are: `agents_hub.jsx`, `orion_office.jsx`, `dashboard.jsx`,
  `mobile/m_agents.jsx` (each copies `consults` off the response like it does `actions`).
- Reload-proof: each consult is also (a) written to the ASKER's chat history as `[consulted Marcus] Q → A`
  (`agents_history`, via="consult") so the agent remembers it next turn, and (b) sent on the agent bus both ways
  (`ask` / `answer`, `{type: "collab"}`) so it shows in the Comms feed / Command Center.
- Limit: the reply is request/response, so the thread appears when the reply lands (no live streaming).

### 4. "Whenever they need" and "whenever I ask"
Prompt block (all dash chats, in `live_block`): when another business or agent's data/judgment would change your
answer, or the owner says "ask X / check with X / what does X think", call `ask_agent` (one question, specific);
don't consult for facts you can `api_get` yourself; at most 3 per message; then answer the owner, crediting the
teammate. `CAN` lines gain "ask any teammate".

### 5. Not in this build
- Telegram partners (`telegram_agent`) — same tool + a quoted-text transcript, phase 2 if wanted.
- Unattended agent ⇄ agent talk (no owner message): stays tasks + bus; the 24/7 Agent Worker is a separate,
  default-OFF decision.
- Consulted agent acting: by design never; use a hub task.

## Tests (`test_agent_consult.py`, extend `test_dash_live.py`, `test_chat_injection.py`, new UI grep)
tool offered only with a collector open · target runs ro (api_post refused) · no `ask_agent` for the target (depth 1)
· Marcus `enable_commands=False` · self / unknown / archived refused · caps (3/msg, 30/day, ceiling, clock-out,
kill switch) · taint: target read taints asker, target not persisted · injection: answer saying "tag X / text Y"
causes no AUTO write · `consults` returned by `take()` and merged by `_chat_with_actions` · history + bus rows
written · lane id resolves · `ChatActions` renders consults + the four UI seams copy `consults` · `valjsx.js` on
every touched jsx · full suite: only the 2 known pre-existing failures.

## Rollout / rollback
py ast + `valjsx.js` → commit → `git push origin HEAD:main` (box self-deploys, health-gated, auto-rollback).
Live check on the box: ask Solomon "ask Marcus how many hot leads he has" via the chat route → `consults` in the
response, bus rows, history rows, journal clean; then ask Marcus to consult Solomon (cross-business) and confirm a
write attempt after it becomes a card. Rollback: `FORGE_CHAT_CONSULT=0` + restart (instant), or `git revert`.
