# skill_forge — skill proposer (worker, not a roster agent)

> Code refs are relative to `forge rei/`. Verified against code 2026-09-22.

## 1. Identity

| | |
|---|---|
| Business | Cross-business · not in `agents_hub.AGENTS` (no hub id, no chat) |
| Job | Watches bus traffic for a recurring topic and drafts a proposed skill for the operator to adopt. |
| Engine | `forge rei/skill_forge.py` |

## 2. Triggers

**Scheduled:** none — no thread, no timer.

**Event:** bus notifier `agent_bus.register_notifier(skill_forge.on_bus_message)` (`connector.py:2198`) — fires on every bus message, on any host (not `FORGE_MARCUS`-gated).

| Knob | Default | Meaning |
|---|---|---|
| `FORGE_SKILLFORGE_MIN_AGENTS` | 2 | distinct agents mentioning a topic |
| `FORGE_SKILLFORGE_MIN_ENCOUNTERS` | 8 | or this many mentions |
| `FORGE_SKILLFORGE_INTERVAL_MIN` | 360 | ≤1 proposal per window |
| `FORGE_CLAUDE_SKILLS` | `~/.claude/skills` | skip topics already covered |

The draft runs on an unnamed thread. No `forge_ops.paused()` check.

**Telegram:** taps `skillgo` / `skillno` (`connector.py:2206`) on the `skill_proposal` alert.

**HTTP**

| Method | Route |
|---|---|
| GET | `/api/skillforge/pending` |
| POST | `/api/skillforge/act {action: approve\|dismiss, pid}` |

**UI:** Command page (`marcus.jsx:668`) · Owner Actions REVIEW rows.

## 3. Reads

Every bus message · vault `Skills/*.md` · `~/.claude/skills/*/SKILL.md` (coverage check).

## 4. Outputs / writes

- `marcus_state/skill_forge.json`.
- Vault `Skills/proposals/<pid>.md`; on approve `Skills/<slug>.md`.
- Bus alert `skill_proposal` (forwarded to Telegram).

## 5. Autonomy & gates

Proposes only; adoption is a tap. NORTH_STAR proposals are never auto-written.

## 6. Self-improvement

None (it is the improvement engine for others).

## 7. Chat & tasks

None.

## 8. Cost

Claude: one call per proposal (1200 tok) when a key exists, else a template. Bucket `operator`.

## 9. Verify it's alive

```bash
curl -s localhost:7799/api/skillforge/pending | jq .
```
No heartbeat.
