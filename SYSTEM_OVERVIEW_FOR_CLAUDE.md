# FORGE REI OS — System Overview for Architecture Evaluation

Use this document to evaluate whether the current custom Python setup should be
migrated to n8n (or a hybrid) for the agent workflows. Give a clear recommendation
with reasoning, tradeoffs, and a migration approach if you recommend n8n.

---

## What the system is

A 24/7 AI operations center for a real estate wholesaling business + a web agency,
running on a DigitalOcean box. Two sides:
- **REI side:** works seller leads through GoHighLevel (GHL) CRM
- **Agency side:** manages web/code client work + Meta ads

Stack: Python stdlib backend (`connector.py`) on port 7799, static React UI
(no build step, in-browser Babel), DigitalOcean box, Anthropic Claude API,
GoHighLevel API, Telegram Bot API, Meta Ads API, Retell AI (voice), DocuSign,
n8n (already connected for roofing lead workflow), Metricool (social scheduling).

---

## The 5 AI Agents ("employees")

### 1. Scout — Lead Triage Agent (REI)
**Job:** Reads every GHL seller SMS conversation every 3 minutes. Scores each seller
0-100 for motivation. Buckets them: `asap / warm / nurture / dead`. Finds who to
text back FIRST (speed to lead).

**What it does autonomously (no approval needed):**
- Scores + ranks all seller threads
- Auto-tags hot (asap) leads in GHL: `triage: asap`, `motivated: high`
- Auto-moves hot leads into the "Hot" pipeline stage
- Hands call-worthy leads to Marcus for screening (auto-handoff)
- Runs a weekly deep audit of missed leads (scans last 7 days of threads)
- Rewrites its own scoring playbook from what it learns (self-improvement loop)
- Posts alerts on the agent bus

**What needs operator approval (tap ✅ in Telegram or dashboard):**
- Warm/nurture tags
- SMS replies to sellers
- Pipeline moves for non-hot leads

**Files:** `scout_triage.py`, `forge-scout/skills/`

---

### 2. Marcus — Lead Screening + SMS Coordinator (REI)
**Two modes:**

**Mode A — Screening (main job):** When Scout hands off a call-worthy lead,
Marcus reads the full GHL conversation thread, produces a call-ready report:
motivation score, what info is missing, red flags, call prep, path-to-contract.
Also drafts a nurture/check-back SMS in the operator's voice for "not ready yet"
sellers. Operator one-taps to send.

**Mode B — SMS auto-responder (legacy, off by default):** When `FORGE_MARCUS_SMS=1`,
Marcus polls GHL for unread inbound seller texts and drafts replies in real time
using Claude (Haiku). These are gated — never auto-send without approval.

**Marcus is the "lead agent" / coordinator:** Scout, Atlas, and other agents
consult Marcus via the agent bus. In the Agents chat tab, Marcus answers from
live GHL threads (not generic knowledge).

**What it does autonomously:** drafts text replies, screening reports, calls Claude
**What needs approval:** every outbound SMS send

**Files:** `marcus_engine.py`, `marcus_chat.py`, `marcus_screening.py`,
`marcus_lead.py`, `forge-marcus/skills/`

---

### 3. Atlas — Deal Underwriter (REI)
**Job:** Every time Marcus flags a seller as "interested", Atlas auto-preps a
deal card within 15 minutes. Reads the GHL thread, extracts facts, derives offer
anchors (opening / target / walkaway) from the seller's own stated ask, writes
the MAO math, flags unknowns, produces a negotiation call card.

**Fully internal — never contacts anyone.** Numbers stay inside the dashboard.
Reports to Marcus.

**Files:** `deal_prep.py`

---

### 4. Dyson — Website/Code Agent (Agency)
**Job:** Plans and ships client website edits, new pages, code changes.
Operator assigns a task (edit request) → Dyson plans it → operator approves
plan → Dyson executes. Self-improves from completed tasks.

**What needs approval:** every live code change before it ships
**Files:** `agency_agents.py`, `forge-agency/skills/`

---

### 5. Eco — Ads Strategy Agent (Agency)
**Job:** Analyzes Meta ad performance, proposes strategy changes, writes ad
concepts. Operator approves before anything launches.

**What needs approval:** every ad change / launch
**Files:** `agency_agents.py`, `agency_ads.py`

---

## Shared Infrastructure

- **Brain (Obsidian vault):** all agents read/write markdown playbooks to a
  shared vault (`~/Desktop/Agentic-OS/vault/` local, `/opt/forge/vault` on box).
  Every write is git-committed. Agents hot-reload their playbook on each run.
  Brain tab in the dashboard shows the vault live.
- **Agent bus (`agent_bus.py`):** inter-agent message bus. Scout → Marcus handoffs,
  hot-lead alerts, learning broadcasts. Visible in the dashboard Comms tab.
- **Review agent (`review_agent.py`):** shared Claude caller. One function
  (`_claude`) used by all agents. Single place to change model, error handling, etc.
- **Self-improvement loop:** every agent has a `learn()` that rewrites its own
  playbook after N encounters (Scout: every 25 scorings; agency: every 12 tasks).
  Playbooks committed to brain vault. Loop runs automatically on the box.

---

## Telegram Integration (operator control channel)

Telegram is how the operator runs the whole system from a phone. Two channels:

### Channel 1 — Alerts + Approvals (the main DM)
- **Hot lead ping:** when Scout finds an `asap` lead → Telegram alert with name,
  phone, motivation score, last message
- **Inline approve buttons:** every pending action has ✅/❌ inline buttons
  - ✅ "Send text" → Marcus SMS fires to the seller
  - ✅ "Apply tags" → Scout pushes triage tags to GHL
  - ✅ "Move pipeline" → Scout moves GHL opportunity stage
  - ✅ "Screen this lead" → Marcus runs a screening report
  - ❌ dismisses without action
- **Weekly missed-leads sweep alert:** Scout's weekly deep audit fires → Telegram
  summary of leads with real signal that went cold
- **Autopilot mode** (`/autopilot on/off`): when on, routine no-response
  re-engage bumps auto-send (daily cap 10, 9am-8pm ET window, never first contact)

### Channel 2 — Agent Chat (separate group)
Operator can talk directly to agents:
- `/marcus` → sticky mode, all messages go to Marcus
- `/scout` → sticky mode, Scout answers from live triage data
- `/agents` → pick agent from menu
- Plain message → goes to last active agent

Marcus answers from live GHL threads (actually searches your seller conversations
to answer "who was asking $85k yesterday?"). Scout answers from live triage scores.
Atlas answers from live deal preps.

**Files:** `telegram_io.py`, `telegram_ops.py`

---

## Current workflow: how a lead moves through the system

```
Seller texts in
     ↓
GHL records inbound SMS
     ↓
Scout poll (every 3 min) — scores thread, buckets to asap/warm/nurture/dead
     ↓ (if asap or warm)
Scout auto-tags + auto-pipes to Hot stage (no approval)
     ↓
Telegram alert fires to operator with ✅ buttons
     ↓
Scout auto-hands lead to Marcus for screening
     ↓
Marcus reads full GHL thread → screening report → drafted SMS check-back
     ↓
Telegram sends: "🔍 Marcus screened [Name]: [score] — [call-ready?] [drafted text]"
     ↓
Operator one-taps ✅ "Send text" → SMS fires
     ↓
Atlas auto-underwrites (if interested) → deal card in dashboard
     ↓
Operator calls seller armed with Atlas call card
```

---

## Known gaps / current problems

1. **Agents can advise but can't execute from chat.** If the operator texts Marcus
   "Move Christopher to Under Contract and tag him", Marcus replies with words only —
   no GHL write. The write functions exist but aren't wired into the chat path.
   (This is the headline build in `CODEX_TASKS.md`.)
2. **Billing dependency.** All AI brains dead when Anthropic account is out of credits.
   The error now surfaces the real reason (fixed), but there's no fallback brain.
3. **Custom Python = custom maintenance.** Every workflow is hand-coded in Python.
   Adding a new trigger or step requires code.
4. **No retry / dead-letter queue.** If a Telegram approve fires but GHL is down,
   the action is lost. No queuing.
5. **Single box.** Everything runs on one DigitalOcean droplet. If it crashes,
   everything stops.

---

## What n8n already does in this system

There is one active n8n workflow today: the **roofer speed-to-lead** pipeline
(separate from the main system). When a prospect submits an estimate request →
n8n triggers a Retell AI phone call → books to Google Calendar → sends Gmail
confirmation. Workflow ID: `ZnzuJSrgpdIjMB4S`. It works and is production.

The n8n instance is already connected (credentials in `agency.env`).

---

## The evaluation question

Should the agent workflows above (Scout → Marcus → Atlas pipeline, Telegram
approvals, self-improvement loops, GHL tag/pipeline writes) be rebuilt or wrapped
in n8n — or is the current custom Python setup the right tool?

Evaluate specifically:
1. What does n8n do better for these workflows?
2. What does the custom Python do better?
3. Where is a hybrid the right answer (some in n8n, some in Python)?
4. What would actually break or get harder if moved to n8n?
5. Clear recommendation: rebuild in n8n / stay in Python / go hybrid?
6. If hybrid or full n8n: what moves first, what stays, rough migration path?

Be specific about these workflows — not generic "n8n is good for automation".
The operator wants to be able to give agents commands from Telegram and have them
execute GHL actions. Does n8n help or hurt that specific goal?
