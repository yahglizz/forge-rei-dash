# Vendored: instagram-agent-skill

- **Source:** https://github.com/Jakeschincariol/instagram-agent-skill (MIT, see `LICENSE`)
- **Commit:** `d03c56bb598be770c60b201f94237e5d1a4268a6` (2026-09-13), vendored 2026-10-31
- **Scope:** AGENCY Instagram only (`@forgelabsphiladelphia`). Not wired to the daycare, wholesale or dropship. See `docs/META_ACCOUNTS.md`.
- **Reviewed before vendoring:** the five Python tools use the stdlib only; no network, no subprocess, no file writes outside `--out`.

## Local changes (everything else is byte-identical upstream)

1. State paths in every `SKILL.md` (and one `swipe.py` docstring) moved off the global `~/.claude/instagram/`:
   - `voice.md` -> `forge-agency/instagram/voice.md` (committed, owner-edited)
   - `swipe.md`, `log.md`, `plan.md` -> `forge-agency/data/instagram/` (runtime, git-ignored)
   Reason: the global folder is shared by every account on this Mac; the agency's voice, swipe file and log must not mix with the daycare's.
2. `README.upstream.md` is the upstream README, kept for reference. `templates/voice.md` became `voice.md` (filled in for the agency).

## Updating

Re-clone upstream, diff against this folder, re-apply change 1, bump the commit above. Do not edit the vendored tools in place.

## How the dashboard uses it

`forge rei/agency_instagram.py` runs the five tools (`hookscore`, `beats`, `caption`, `humanize`, `detect`, `swipe`) as stdlib subprocesses behind `/api/agency/instagram/*`. Agents learn the tools from `forge-agency/skills/agency-instagram-tools.md`. Nothing here posts: drafts land in the Social queue as `draft`, and publishing stays approval-gated.
