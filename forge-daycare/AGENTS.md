# forge-daycare/ — instructions for Codex (and any non-Claude agent)

Business config + the business brief + the Supabase schema. **Not an agent engine.** Canonical
rules: `../CLAUDE.md` §10, `../NORTH_STAR.md`. Solomon's contract: `../forge-solomon/AGENTS.md`.

- `skills/daycare-context.md`, `daycare-parent-reply.md` (the verified fact sheet Solomon's
  Replies lane texts from), `daycare-voice.md`, `enrollment-ad-agent.md` are **live agent inputs**
  (mtime hot-reload). Editing a fact here changes what parents are told — verify it against
  https://www.atouchofblessing.com first and keep the "verified on <date>" line current.
- Do not change licensing / pricing / offer terms without the owner. CCIS wording: "we help
  families through the process" — never "we handle the paperwork".
- Migrations in `supabase/migrations/` must stay byte-identical to the parent/staff app's.
- Secrets only in `config/daycare.env` (git-ignored). Never paste a value into a file here.
