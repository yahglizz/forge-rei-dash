# FORGE REI OS — The Dashboard

*The front door. What this whole thing is, how the pieces fit, and where to look
next. Start here, then follow the links.*

*Last updated: 2026-07-15.*

---

## What it is

**One control center for one operator (Yahjair) running three businesses** — a
real-estate wholesaling operation, an AI agency, and a childcare company — with a
team of AI agents doing the employee-work and a human approving anything that goes
out the door.

- **Frontend:** static React (React UMD + in-browser Babel, **no build step**).
  Each `.jsx` file is a `window` global, loaded by `FORGE REI OS.html`.
- **Backend:** one Python stdlib connector (`connector.py`, port 7799) — mirrors
  GoHighLevel, serves the API, and runs the agent loops.
- **Runs 24/7** on a DigitalOcean box (systemd `forge-reios`, `FORGE_MARCUS=1`).
  Your PC/Mac are UI + editing workspaces (`FORGE_MARCUS=0`) so sellers are never
  double-contacted.
- **Brain:** an Obsidian vault the agents read their skills from and write their
  learned playbooks back to (git-committed).

---

## The three workspaces (profile switcher)

| Workspace | Business | What's in it |
|---|---|---|
| **REI** | Wholesale — A Touch of Blessings Home Buyers | Dashboard, Leads, Conversations, Pipeline, Contracts, Agents, Brain, Command Center |
| **Agency** | ClientForge / Forge Labs | Clients, Edit Requests, Agents, Ads, Social, Approvals, Brain |
| **Daycare** | A Touch of Blessings Learning Academy | Solomon/Nora/Nova, Children, Billing, Growth (Ads/Social/Ideas), Brain |

---

## The map — where everything is documented

Four documents, each with a job. Read them in this order when you need the full
picture:

1. **[`NORTH_STAR.md`](NORTH_STAR.md)** — the **constitution**. Mission, identity,
   tone per business, cross-business principles, brains/skills/env map. This is
   what the agents actually read, and it **wins** over any learned playbook.
2. **[`BUSINESSES.md`](BUSINESSES.md)** — the **business bible**. The full "what we
   are and what we're going for" for daycare (addresses, goal, model), wholesale
   (with the beginner-wholesaling primer), and the agency (automations + web + ads).
3. **[`AGENTS.md`](AGENTS.md)** — the **agent roster**. All eight agents: role,
   engine file, chain of command, and exactly how much each may do on its own.
4. **[`CLAUDE.md`](CLAUDE.md)** — the **operating manual**. HOW to build: rules,
   the self-improvement loop, the creed doctrine, validate/deploy mechanics, the
   full technical sections (Daycare OS, Telegram, cost tracker, coaching network).

Per-business operational truth (owner-edited, agent hot-reloaded) lives in each
`forge-*/skills/*-context.md`. Folder-level "if you're stuck" notes live in each
`forge-*/CLAUDE.md` and `forge rei/CLAUDE.md`.

---

## How a lead actually flows (the spine)

**Wholesale:** seller texts → **Scout** triages + ranks + tags → hands call-worthy
leads to **Marcus** → Marcus screens + drafts the reply that drives to a call
(never a price by text) → operator calls + gives the offer → **Atlas** has already
underwritten the numbers internally → contract → assign/close.

Everything outward is a **proposal the operator taps to approve**. The agents
find, rank, screen, underwrite, and draft; the human sends, spends, and signs.

---

## Build / deploy in one breath

Static React, no build. Validate every change — Python `ast.parse`, JSX
`node deploy/valjsx.js` — then it reaches the live box. The PC auto-commits +
pushes ~every 60s and the box auto-deploys any commit that passes validation, so
**never leave the tree in a broken intermediate state.** Secrets stay in
git-ignored `*.env` files outside the web root (must 404 over HTTP). Full
mechanics + the three deploy paths: [`CLAUDE.md`](CLAUDE.md) §7.

---

## The standard, restated

Build like someone who already made it: run the proven playbook better, faster,
more honestly than the shop next door. Let the agents do the employee-work. Keep a
human hand on the wheel for anything that spends money, makes a promise, or goes
out the door. That's not a limitation we work around — it's the standard a
well-run company holds itself to.
