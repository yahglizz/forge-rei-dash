# Cross-Agent Coaching Network — Spec & Subagent Brief (2026-07-14)

**Status:** APPROVED (owner Yahjair, 2026-07-14). This file is BOTH the design spec
AND the coordination brief every subagent reads before touching code. If you are a
subagent on this build, read this whole file first, then do ONLY your lane.

---

## The goal (why)

Make all 8 FORGE agents able to **coach each other and learn from each other** across
the three businesses — live and functional, not for show. Example the owner gave:
the agency ad agent (Eco) sees a creative angle crushing it for a client, and that
insight flows to the daycare ad agent (Nova) so Nova's next enrollment ad builds on
it. And vice versa. Plus a unified **Agent Network** surface where the owner can chat
any agent, run tasks, and watch the agents coach each other in a live feed.

## The one invariant that cannot break

**Coaching moves INSIGHTS — plain text (lessons, questions, answers). It NEVER moves a
credential, GHL client object, API token, or location id. It NEVER performs an
autonomous outward action (SMS, ad launch, invoice, spend, social post).**

We verified (2026-07-14) that the 3 GHL sub-accounts (`WHOLESALE` / `AGENCY` /
`DAYCARE_GHL` in `connector.py:178-180`) are fully isolated — each built from a LOCAL
dict, never merged into global `os.environ`. **That isolation stays byte-for-byte
intact.** The coach layer passes strings only. If any lane finds itself passing a
client/token/env value between businesses, STOP — that's a bug, not the design.

Autonomy: insight-sharing + absorption is AUTONOMOUS (internal, reversible,
git-committed to the brain — same class as the existing `learn()` self-improve loop,
allowed under root CLAUDE.md rule 2). Outward actions stay tap-gated. The owner can
also trigger coaching manually from the Agent Network tab.

---

## What already exists (do NOT rebuild — extend)

- `forge rei/agents_hub.py` — ALREADY the unified backend: `AGENTS` roster (all 8,
  3 businesses), `roster(business=None)` (None = everyone), `chat()`, `send_task()`,
  `bus()`, `tasks()`. Creed-aware. Routes: `/api/hub/{roster,tasks,bus,chat,task,
  task/update,history}` (see `connector.py:2327-2331, 2697-2700, 2857-2861`).
- `forge rei/agents_hub.jsx` → `window.HubAgentsPage`, already rendered in ALL THREE
  workspaces (`app.jsx:15,36,53` as `<HubAgentsPage ws="rei|agency|daycare"/>`).
- `forge rei/agent_bus.py` — `send(frm,to,kind,text,data)`, `inbox(agent)`,
  `recent(limit)`, `register_notifier()`. One-way postbox. Eco already broadcasts on
  ad-ship (`agency_eco._broadcast_ad_created`).
- `forge rei/brain_io.py` — `write_note(rel, body, reason)` (git-committed),
  `VAULT` path, read helpers. The durable shared learning substrate.
- Each agent's `learn()` reflects on recent encounters + `_load_skills()` (creed +
  playbook) → Claude rewrites playbook → `brain_io.write_note(PLAYBOOK_REL, ...)` →
  recipient mtime-reloads next run.

## The 8 agents (id · engine file · business)

| id | engine `learn()` lives in | business |
|----|---------------------------|----------|
| scout | `scout_triage.py` (`SCOUT.learn`) | wholesale |
| marcus | `review_agent.py` (weekly review) / `style_agent.py` (voice) | wholesale |
| atlas | `deal_prep.py` | wholesale |
| dyson | `agency_agents.py` | agency |
| eco | `agency_eco.py` / `agency_agents.py` | agency |
| solomon | `daycare_director.py` (`SolomonEngine.learn`) | daycare |
| nora | `daycare_family.py` | daycare |
| nova | `daycare_adops.py` | daycare |

---

## THE INTERFACE (pinned — every lane builds against this exact API)

New module: `forge rei/agent_coach.py`. Stdlib only. Pure functions, no connector
import (avoids circular import — connector imports it, not vice versa).

```python
# agent_coach.py — cross-agent coaching. INSIGHTS ONLY (text), never creds/outward.

BUSINESS_OF = {"scout":"wholesale","marcus":"wholesale","atlas":"wholesale",
               "dyson":"agency","eco":"agency",
               "solomon":"daycare","nora":"daycare","nova":"daycare"}

def broadcast(frm: str, insight: str, to: str = "all", tags: list[str] | None = None) -> dict:
    """`frm` agent shares a transferable lesson. `to` = a peer id, a business name,
    or "all". Writes a dated entry to vault Coaching/feed.md (git-committed) AND posts
    agent_bus.send(frm, to, kind="coach", text=insight, data={"tags":...}).
    Returns {"ok":True,"id":...}. Rejects empty insight. NEVER accepts a payload that
    looks like a secret (guard: refuse if insight matches a key/token regex)."""

def insights_for(agent: str, business: str | None = None, limit: int = 12,
                 since_ms: int | None = None) -> list[dict]:
    """Recent coaching entries ADDRESSED to `agent` (to==agent, to==business,
    or to=="all"), newest first. Each: {id, from, to, insight, tags, ts}.
    Excludes the agent's own broadcasts. This is what learn() folds in."""

def insights_block(agent: str, business: str | None = None, limit: int = 8) -> str:
    """insights_for() rendered as a prompt-ready text block, or "" if none. This is
    the ONE-LINER each learn() appends to its reflection prompt:
        prompt += agent_coach.insights_block(<id>, <business>)
    Returns "" when the feed is empty → zero behavior change when nothing to coach."""

def ask(frm: str, to: str, question: str, chat_fn=None) -> dict:
    """Agent-to-agent Q&A. Routes `question` to target agent via chat_fn (injected by
    connector = agents_hub.chat bound to ghl_get/location) so agent_coach stays
    connector-free. Logs Q+A to the feed. Returns {"ok":True,"answer":...,"from":to}."""

def feed(limit: int = 40) -> list[dict]:
    """The whole coaching feed, newest first — powers the Live Coaching Feed panel."""
```

Storage: `vault/Coaching/feed.md` (human-readable, git-committed via brain_io) is the
source of truth; a mirror in `marcus_state/coach.json` for fast reads is OPTIONAL —
prefer parsing the bus (`agent_bus.recent()` filtered to `kind=="coach"`) so there's
one source of truth. Pick the simplest that works; document the choice in the module
docstring.

Secret-guard: `broadcast()` must refuse any `insight` containing something that looks
like a live key (`sk-ant-`, `pit-`, `rk_live`, `sk_live`, `key_`, bearer-ish 32+ hex,
`AC[0-9a-f]{32}`, JWT `eyJ...`). Log + drop, never write it to the brain.

---

## LANES (parallel — each subagent owns ONE, no file overlap)

### Lane A — `agent_coach.py` core  [OWNER: main thread, built FIRST]
Build the module above. Unit-test the secret-guard + insights_for filtering inline.

### Lane B — wire coaching into all 8 `learn()` methods
Files: `scout_triage.py`, `review_agent.py`, `deal_prep.py`, `agency_agents.py`,
`agency_eco.py`, `daycare_director.py`, `daycare_family.py`, `daycare_adops.py`.
For EACH agent's reflection/learn prompt build, add exactly one additive line:
`prompt += agent_coach.insights_block("<agent_id>", "<business>")` right after its own
encounters are assembled, guarded by `try/except` (never break learn() if coach fails).
Do NOT touch creed/playbook loading order otherwise. Import `agent_coach` at top.
Validate each file: `python3 -c "import ast; ast.parse(open('FILE').read())"`.
**Touches NONE of Lane C's files.**

### Lane C — Agent Network tab + routes
Files: `agents_hub.py` (add thin `coach_*` wrappers calling agent_coach), `connector.py`
(add GET `/api/coach/feed`, POST `/api/coach/{ask,broadcast}` — mirror existing
`/api/hub/*` registration in the ROUTES dict + do_POST allowlist tuple + elif dispatch;
inject `agents_hub.chat` bound closure as `chat_fn` into `agent_coach.ask`),
`agents_hub.jsx` (cross-business roster view when ws is the network view + a
**Live Coaching Feed** panel polling `/api/coach/feed` + a "coach/ask a peer"
affordance in the chat box). Use unique hook aliases + prefixed globals; NO computed
JSX tags. Validate: `node deploy/valjsx.js agents_hub.jsx`.
**Touches NONE of Lane B's files.**

### Lane D — complete master env draft  [FOLD INTO MAIN — already ~done]
All 6 real `*.env` already inventoried in `keys-master-draft.env`. Verify no key
missing, keep staging-only (never wired). Higgsfield slot already present.

### Lane E — update agent docs
Add a "Cross-Agent Coaching" section to root `CLAUDE.md` + `AGENTS.md` and a short note
in each agent-folder `CLAUDE.md` (marcus-wholesale-agent, forge-scout, forge-agency,
forge-solomon, forge-nora, forge-nova, forge-daycare): agents may ask peers questions,
broadcast transferable insights, and absorb peer insights on `learn()` — KNOWLEDGE
ONLY, never creds/outward; outward stays tap-gated. Additive only.

### Lane G — dashboard key audit (all 3 businesses)
Hit the live connector's own health endpoints (not just raw curl) for every connected
system per business; report which keys are DOWN. Deliver a table: business · system ·
status · reason.

---

## Testing (main thread integrates)
1. Isolation: assert `agent_coach` never returns/accepts a cred; secret-guard drops a
   planted `sk-ant-...` insight.
2. Round-trip: `broadcast("eco", "...", to="nova")` → `insights_block("nova","daycare")`
   contains it; `insights_block("scout","wholesale")` does NOT (not addressed).
3. Ask: `ask("nova","eco","what creative is winning?")` returns a non-empty answer.
4. Validate every touched `.py` (ast) + `.jsx` (valjsx).

## Deploy (main thread, once, at end)
Additive. Validate all → `./deploy/quick-deploy.sh` (SSH key present) → SSH-verify:
service active, `/api/coach/feed` 200, `/api/hub/roster` 200, secrets still 404.
Live-verify the tab renders + a broadcast shows in the feed. NOT for show — confirm
a real coaching entry survives a round-trip on the box.
