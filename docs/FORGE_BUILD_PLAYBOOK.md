# FORGE — Build Playbook (how builds are dispatched, reviewed, and shipped)

Written 2026-09-23 after wave 1 + wave 2. This is the operating procedure the lead (Claude)
follows when the owner asks for a build. It sits under `CLAUDE.md` (rules) and uses
`docs/FORGE_WAVE2_PLAN.md` (what to build) — this file is only HOW.

## 1. Read before any build

Every builder agent's prompt starts with: read `CLAUDE.md` (§2 rules, §7 build/validate +
JSX collision rules), the plan item it owns in `docs/FORGE_WAVE2_PLAN.md`, and the matching
section of the master spec `~/Downloads/FORGE_AI_MASTER_SPEC.md`. Daycare work also reads the
brand-kit context (`~/Desktop/A Touch of Blessings — Brand Kit/`). Code is truth: a builder
greps the code before trusting any doc.

## 2. Model selection

| Work | Who |
|---|---|
| Every Claude subagent (builders, audits, docs, gap checks) | **Opus 5.5** (`model: opus`) — owner's standing instruction since 2026-09-22 |
| Independent second-opinion review of risky diffs (send paths, Claude call sites, deploy scripts, auth) | **Codex CLI** — `codex exec -s read-only "<review prompt>"` |
| Lead: plan, split work, review every diff, merge, test, deploy, verify live | Main session |

*History:* wave 1 used Fable for cross-cutting / hard packages, Opus for medium features,
Sonnet for mechanical fixes. The owner replaced that with Opus-for-all on 2026-09-22.

## 3. Dispatch rules

- One agent per plan item, each in its **own git worktree** (`isolation: worktree`).
- Items run in parallel only when their files don't overlap. Shared hot files
  (`connector.py`, `owner_actions.py`, `marcus_engine.py`, `scout_triage.py`) get one owner per
  batch; anything else that needs them describes the change in its report instead.
- Builders never edit `CLAUDE.md` / `docs/` (a single docs agent or the lead does, after merge)
  → no doc merge conflicts.
- Builders never deploy, push, SSH, read `*.env`, or run `node --test`. They commit on their
  worktree branch and report: files, test output, doc notes, what they skipped.
- Hard rules carried into every prompt: additive only; never make an outward action
  autonomous; never touch secrets; never change ACE / autopilot defaults.

## 4. Review → merge → ship

1. Lead reads the report + diff. Anything touching a send path, a Claude call site, a deploy
   script, or an auth gate also goes to Codex CLI. Findings are verified, not blindly applied
   (wave 2: Codex caught timeout-retry blocking and three action-log issues — all fixed first).
2. Merge into `main`, then the full offline suite from `forge rei/`
   (`docs/FORGE_TEST_PLAN.md` §1 — skip the 4 connector-importing tests; set
   `FORGE_ACTION_LOG` to a temp file) + `node deploy/valjsx.js *.jsx mobile/*.jsx`.
3. Deploy: `git push` (box autopull) or `./forge rei/deploy/quick-deploy.sh` for now. Chain
   deploy commands with `&&`, never `;`.
4. Verify live: `/opt/forge/.deployed_sha` == pushed SHA, service active, touched routes 200,
   new write routes reject unauthenticated calls, secrets/state 404, no new tracebacks, and a
   read-only look at the dashboard (never mutate live UI state to test).

## 5. Agent readiness check (run after any agent-facing change)

On the box, for every agent in `/api/agents/registry`: file a `[system check]` task via
`/api/hub/task`, confirm it shows in `/api/hub/tasks`, close it, and send one chat via
`/api/hub/chat`. Then cancel the mirrored Dyson/Eco rows in `/api/agency/agents/tasks`.
Last run 2026-09-23 on `36560a8`: 12/12 task round-trip OK; chat reaches every brain and
returns the Anthropic "credit balance is too low" error until credits are topped up.

## 6. Git gotchas seen in practice

- The Mac's `com.forge.autosync` commits + pushes the main checkout every 60 s and rebases, so
  merge commits come back as linear commits and `git branch -d` reports "not fully merged".
  Confirm with `git diff <branch> main -- <files>` (empty = merged) before `branch -D`.
- Leave nothing uncommitted in the main checkout you don't want live within a minute.
