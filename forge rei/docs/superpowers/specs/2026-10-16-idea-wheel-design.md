# Idea Wheel — design adaptation (LOCAL TEST ONLY, not deployed)

Source spec: `~/Downloads/forge_dash_idea_wheel_feature.md` (user's, authoritative for behavior).
This file only records how the spec maps onto the real FORGE REI OS stack and the calls made so far.

## Decisions (from user, 2026-10-16)
- **Placement:** Agency workspace, **Personal lens** (`"p"` in `data.jsx` AGENCY_NAV). User words: "personal agency side of the daycare".
- **Stack:** Python engine + JSON files + `/api/ideawheel/*` routes + JSX UI. No TypeScript, no SQL DB.
- **Codex CLI assets:** wheel SVG/CSS, segment art, icons, motion CSS (code assets only). Codex MCP is down; use `codex exec` via Bash.
- **Builder:** Opus agent (`opus-worker`) is main builder.
- **Scope:** local only. No push, no deploy to the box (24.199.81.124), no changes to live state.

## Repo rules that bind the builder (from root `CLAUDE.md`)
- **Rule 1 "auto-deploy after any edit" is SUSPENDED for this feature** by the user (local test). Never run `deploy/push.sh`, `quick-deploy.sh`, or `git push origin main` (the box self-deploys from main within 60 s).
- Additive only; unique hook aliases + prefixed globals per `.jsx`; no computed JSX tags; validate with `node deploy/valjsx.js FILE.jsx` and `python3 -c "import ast..."`.
- Backend: GET via `ROUTES`, POST via `do_POST` allowlist + `elif`; JSON store idiom = `agency_io.py` (`forge_atomic`, lock, `_load/_save`, state in `marcus_state/`).
- Operator-facing text is caveman-terse where an AI chat is involved; Idea Wheel is deterministic so N/A. Content-kit copy is customer/social-facing: normal prose, with the disclosure line from the spec.
- Agency evidence discipline: no invented metrics, testimonials, or client claims in any generated copy.

## Stack mapping
| Spec says | Here |
|---|---|
| TS `Idea` type | JSON schema + `validate_idea()` in Python (same fields) |
| `idea_catalog` etc. tables | `idea_wheel_catalog/*.json` (sectors, niches, workflows, styles) + `marcus_state/idea_wheel.json` (ideas, events, kits, prefs) via `forge_atomic` + lock (same idiom as `business_scope.py`) |
| Auth / workspace scope | Agency workspace routes only; follow existing agency route auth |
| Unit/integration/smoke tests | flat self-check scripts `test_idea_wheel*.py` run as `python3 test_x.py` (repo convention, e.g. `test_agency_lens.py`) |
| Nav entry | tuple in `AGENCY_NAV` with lens `"p"`; page in `app.jsx`; script tag in `FORGE REI OS.html`; icon in `icons.jsx` |

## Known trap: Personal lens is archived by default
`business_scope.py` DEFAULT_ARCHIVED includes `agency:p`; with no `businesses.json` the Personal lens is hidden and a stale `"p"` is forced to `"b"` (`app.jsx:227`). Local test must unarchive `agency:p` in the **test worktree's** `marcus_state/businesses.json` only. Do **not** change DEFAULT_ARCHIVED. If the user wants the wheel visible regardless of that toggle, give the tab no lens (shows in both) — one-line change.

## Reuse check (builder must do first)
`daycare_growth.py`, `daycare_ads_studio.py`, `agency_social.py` mention ideas/content. Reuse content-kit/caption helpers if they fit; do not duplicate.

## Isolation for local test
- New git worktree + branch off `tours-booking` (e.g. `idea-wheel`), never edit the dirty `tours-booking` tree.
- Run `FORGE_PORT=7811 python3 connector.py` with `FORGE_MARCUS` unset (loops OFF, no seller contact). Idea Wheel needs no external API.
- Rollback = delete worktree + branch.

## Deviations from spec (my calls)
- No AI enrichment in v1 (spec says optional); deterministic generator only. Hook left for later.
- Research of ≥100 niches / ≥20 workflows done by builder via web where possible; entries without a source are flagged `unverified`, no invented citations.
- Screenshots via built-in browser pane at localhost:7811.

## Test plan
1. `python3 test_idea_wheel.py` — seeded determinism, compatibility rules (no HIPAA/real-child-data claims, no fake integrations), filters, repeat avoidance + exhaustion message, schema validation, ≥100 niches / ≥20 patterns present.
2. `python3 test_idea_wheel_api.py` — save/retrieve/status transitions/duplicates/prefs via a temp state dir.
3. `python3 test_agency_lens.py` + existing nav self-checks still pass (regression).
4. Browser smoke: Personal lens → Idea Wheel loads, spin lands on displayed segment, reduced-motion path, keyboard, mobile width, all 7 buttons work, existing tabs unaffected.
5. Read connector log for errors after the run; fix what it finds before reporting done.
