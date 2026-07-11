# Analytics, AI Weekly Review & Brain

Three features that turn FORGE's live GoHighLevel feed into insight, and feed it
back into Marcus. All read-only against GHL; the only writes go to the Obsidian
brain. Same connector, no new service, no database.

## Messages Analytics tab

Deterministic message metrics (no LLM). The connector pulls ~4 pages of recent
conversations, samples ~25 threads for reply timing, folds in Marcus's logs +
the pipeline, and returns one bundle. Cached 45s like the rest of `/api/*`.

What the tab shows:
- **Response Rate** — `100 × (1 − inbound-last / total)`; share of conversations
  where you (not the seller) had the last word.
- **Unanswered** — inbound-last conversations with `unreadCount > 0`.
- **Hot Signals** — `READY + PRICE` count from the classifier (sellers ready to
  talk or asking about money).
- **Median Reply** — median seller→reply latency, sampled from ~25 recent threads.
- **What sellers are saying** — classification mix run through **Marcus's own
  classifier** (`scan_missed_replies.classify`: READY/PRICE/NRN/HELP/DNC/CONTINUE),
  so the buckets match what Marcus acts on.
- **Channel mix** — last-message type per conversation (SMS, etc.).
- **Top markets** — conversations grouped by market-ish contact tags (`market-`,
  Ohio, Delaware, Wilmington, Toledo, area codes…), ranked, top 12.
- **Inbound by day** — when sellers text back, by weekday.
- **Conversion** — open opportunities, pipeline value, total opportunities (from
  the live pipeline).
- Footer tiles: outbound-last, inbound-last, avg turns/thread, Marcus sent count.

Endpoint: `GET /api/analytics?days=30` (the tab requests 30; the weekly review
requests 7). Window filters by `lastMessageDate`; if nothing falls in-window it
falls back to the full pull so the tab is never empty.

## AI Weekly Review

A parallel analyst panel. `POST /api/review/run` fans out **5 Claude analysts
concurrently** — *response, messaging, markets, conversion, marcus* — each given
the full metrics bundle but focused on one lens and returning strict JSON. A
**synthesizer** (Chief of Staff) merges them into one markdown report:
TL;DR · What's working · What to fix this week · Marcus playbook.

It then writes two notes into the brain vault:
- **`Log/forge-review-<date>.md`** — the full report (with frontmatter + scope).
- **`Skills/marcus-playbook.md`** — the "Marcus playbook" section, extracted and
  rewritten each run. This is the living playbook (see Learning loop).

Both write through `brain_io.write_note`, which git-commits if the vault is a repo.

Keys: needs **`ANTHROPIC_API_KEY`** in `ghl.env`. Without it, `run` returns
`{needsKey: true}` and the Analytics tab prompts you to add the key and restart.
Report model defaults to `claude-sonnet-4-5` (override `FORGE_REVIEW_MODEL`).

`GET /api/review/latest` returns the last run (report, scope, elapsed, paths,
git-committed flag, per-analyst finding counts) — or `{hasReview:false, needsKey}`.
The tab's "Run analysis now" button calls `run` with `{days:7}` and refreshes.

## Learning loop

Marcus's `_ai_draft` calls `_load_playbook()`, which reads
`Skills/marcus-playbook.md` from the vault (cached, reloaded only when the file's
mtime changes) and injects up to ~1500 chars into his reply-draft system prompt
as "WEEKLY PLAYBOOK (learned from past messages — follow it)". So each weekly
review rewrites the playbook and Marcus's replies adapt without a restart.

Only active in **Claude-draft mode** (key present). In template mode `_ai_draft`
returns the fixed template before any playbook is consulted.

## Brain tab

Connects FORGE to the existing **Agentic-OS Obsidian vault** — default
`~/Desktop/Agentic-OS/vault`, override with `FORGE_VAULT`. All paths are jailed
inside the vault root. Browse the folder tree (Skills / Agents / Feedback /
Projects / Log…), read any note, and search.

Read endpoints:

| Endpoint | Returns |
|---|---|
| `GET /api/brain/tree` | folders + `.md` files (skips `.obsidian`/`.git`/`.trash`) |
| `GET /api/brain/note?path=` | one note's content (vault-jailed) |
| `GET /api/brain/search?q=` | semantic if the brain server is up, else text scan |
| `GET /api/brain/recent?n=20` | most-recently-modified notes |

Search prefers the brain's own semantic index — it proxies the brain server at
`:7878` (`BRAIN_URL`); if that's down it falls back to a substring scan over
titles + bodies (`mode: "text"`). FORGE never depends on `:7878` being up.

Writes (the weekly review, and Marcus playbook updates) go through
`brain_io.write_note`, which git-commits when the vault — or its parent — is a repo.

## Weekly schedule

```bash
./install_review_schedule.sh    # LaunchAgent: Mondays 8:00 AM
```

Installs `com.forge.reios.weekly-review`, which `curl`s `POST /api/review/run`
with `{days:7}` every Monday at 8am. The **connector must already be running**
(`install_service.sh`) for the POST to land. Logs in `marcus_state/review.*.log`.
Stop: `launchctl unload ~/Library/LaunchAgents/com.forge.reios.weekly-review.plist`.

## API

`GET /api/analytics?days=30`
`GET /api/review/latest` · POST `/api/review/run {days?}`
`GET /api/brain/tree` · `/api/brain/note?path=` · `/api/brain/search?q=` · `/api/brain/recent?n=`

Review + analytics-latest endpoints are never served from the 45s cache.

## Limits / notes

- **Analytics is sampled.** Latency comes from ~25 threads and the pull is ~4
  pages — directional, not a full-account census. Cached 45s.
- **Markets are tag-heuristic.** Only conversations whose tags match the market
  keyword list are counted; untagged leads won't appear.
- **Review needs a key.** No `ANTHROPIC_API_KEY` → no review and no playbook, so
  the learning loop stays dormant (Marcus runs templates).
- **Playbook is best-effort.** If a run produces no `## Marcus playbook` section,
  the file records "No playbook guidance this week."
- **Brain writes need a repo for git.** No `.git` in the vault (or its parent) →
  notes still save, just uncommitted (`committed:false`).
- **Schedule needs the connector up.** The LaunchAgent only POSTs; it doesn't
  start the connector.
