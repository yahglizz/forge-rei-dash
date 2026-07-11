# CODEX_TASKS — FORGE REI OS

Punch list for Codex. Goal: after you finish these **and** the operator adds
Anthropic credits, the dashboard is fully working and the AI agents can be
operated like employees (told to do something → they do it).

Generated 2026-06-16 after an audit by Claude. Claude already made the safe
mechanical fixes (see "ALREADY DONE — do NOT redo" below). Your job is the
remaining items, with **Task A** (agents that execute commands) as the headline.

---

## 0. Context you need

- **App:** real-estate-wholesaling + AI-agency control center. Python-stdlib
  backend `connector.py` (port 7799) mirroring GoHighLevel (GHL) + running AI
  agents. Static React UI (React UMD + in-browser Babel, **no build step**):
  components are `window` globals via `Object.assign(window,{...})`, loaded as
  `<script type="text/babel" src="X.jsx">` in `FORGE REI OS.html`.
- **Working dir:** `~/forge rei dash/forge rei/`. Read `CLAUDE.md` and `AGENTS.md`
  in this dir first — they are the operating rules. Highlights:
  - **Additive edits only.** Don't remove existing features/code. Don't break
    what works.
  - **Propose → review → execute.** Agents never take irreversible/outward
    actions (texting sellers, moving pipeline, launching ads) autonomously —
    those are gated behind the operator's one-click/confirm approval.
    EXCEPTION already in place: internal+reversible tags + HOT-lead pipeline
    auto-apply without approval (see `scout_triage._autotag_hot`).
  - **Decide, don't quiz.** On small forks, pick the reasonable option and note it.
- **Validate before done:**
  - Python: `python3 -c "import ast; ast.parse(open('FILE').read())"`
  - JSX (if you touch any): `node /tmp/valjsx.js FILE` (Babel transform +
    computed-tag scan). JSX collision rules: every `.jsx` shares one global
    scope after Babel — use unique hook aliases + prefixed top-level names; no
    computed JSX tags (`<Icons[x] />` → resolve to a const first).
- **Backend patterns:**
  - GET routes: `ROUTES` dict (+ `NO_CACHE` for cache-exempt) near
    `connector.py:~1520`. Dispatch in `do_GET`.
  - POST routes: `do_POST` allowlist tuple + `elif` dispatch chain
    (`connector.py:~1720`). Handlers often delegate to `handle_marcus_post`.
  - JSON stores mirror `agency_io.py` (threading.Lock, `_load`/`_save`); state
    lives in `marcus_state/`.
- **DO NOT deploy.** After validating, STOP and leave changes for the operator
  to deploy with `./deploy/push.sh root@24.199.81.124` + SSH-verify. Do not run
  the push script yourself. Do not start the server.

---

## ALREADY DONE by Claude — do NOT redo

These are committed in the working tree; build on them, don't duplicate:

1. `review_agent._claude` (`review_agent.py`) — now reads the `HTTPError` body
   and raises `RuntimeError("Anthropic API error (<code>): <real message>")`.
   This covers Marcus/Scout/Atlas/Retell chat + screening + triage + deal-prep +
   Dyson (they all route through `_claude`).
2. `connector.do_POST` — added an `except urllib.error.HTTPError` branch that
   reads the GHL error body and returns `{"error": "GHL <code>", "detail": ...}`
   with status 502 (mirrors the existing `do_GET` handler). POST routes
   (tags/pipeline/sends) now surface the real GHL reason.
3. `marcus_engine.py` `_ai_draft` — reads the Anthropic `HTTPError` body into
   `self.last_error` (the legacy SMS responder; off unless `FORGE_MARCUS_SMS=1`).
4. `scout_triage.py` — three silent `except: pass` blocks now log + set
   `last_error`: the Scout→Marcus auto-handoff, the hot-lead bus alert, and the
   `_autotag_hot` GHL tag/pipeline writes.
5. `connector.py` — added `_qint(q, key, default)` helper and replaced all 8
   unguarded `int(q.get(...)[0])` query-param casts with it (bad input no longer
   500s the endpoint).

Root cause of the original "Hit an error reaching my brain: HTTP Error 400" =
the Anthropic account is out of credits (operator must add credits). No code
change fixes that; the fixes above just make the error message say so.

---

## TASK A — Agents that EXECUTE commands from chat (HEADLINE) ⭐

**Problem.** The agent chat path is read-only. When the operator messages Marcus
(Telegram or the in-app Agents chat) "Put Christopher Giles in the under-contract
section of the pipeline and tag him", nothing happens to GHL — Marcus only
replies with text. The write capabilities exist but are reachable only from
dashboard buttons / confirm-button taps / autonomous poll loops, never from the
conversational path.

**Path today (read-only):**
`telegram_io.py _handle_message` → `telegram_ops.py route()` (NL intent parser,
no pipeline/tag actions) → falls through → `connector._tg_agent_chat` →
`agents_chat.chat(ghl_get, ...)` (read handle only) → `marcus_chat.chat(...)`
(searches threads + calls Claude for a text reply). Same for the in-app Agents
tab via the `/api/agency/agents/chat` and Marcus chat endpoints.

**Existing write functions to reuse (do NOT reimplement):**
- Move pipeline stage: `connector.handle_move_opportunity` (≈`connector.py:1690`,
  `ghl_put /opportunities/{id} {pipelineStageId}`), and
  `scout_triage.add_to_pipeline(convId, stage=...)` (≈`scout_triage.py:1415`).
- Add/remove tag: `scout_triage.apply_tags(convId)` (≈`scout_triage.py:1283`,
  `ghl_post /contacts/{cid}/tags`); removal via `remove_lead`'s
  `ghl_delete /contacts/{cid}/tags`.
- The confirm-button pattern already used for gated SMS sends:
  `telegram_ops._queue_pending` + `telegram_ops.confirm` (the ✅/❌ inline
  buttons) — reuse this exact mechanism so the operator one-taps to approve.
- Pipeline stage config / stage-name → `pipelineStageId` mapping: reuse whatever
  the dashboard drag-and-drop and `add_to_pipeline` already use (find the
  pipeline/stage lookup Scout uses; e.g. `STAGE_BY_BUCKET` in `scout_triage.py`
  and any pipeline-config loader). Do not hard-code IDs.

**What to build:**

1. **Intent detection.** Extend the NL intent parser in `telegram_ops.py`
   (`_INTENT_SYS`, ≈`telegram_ops.py:396-414`, plus the routing in `route()`).
   Add two new actions:
   - `move_stage` → `{ "contact": "<name or phone>", "stage": "<stage name>" }`
   - `tag` → `{ "contact": "<name or phone>", "tags": ["<tag>", ...],
     "op": "add" | "remove" }`
   Keep the existing actions and the `chat` fallback. If no actionable intent is
   detected, behavior is unchanged (falls through to the read-only reply).

2. **Contact resolution.** Resolve the named contact to a GHL `contactId` (and,
   for `move_stage`, the `opportunityId`) by searching conversations/opportunities
   — reuse `marcus_chat`'s thread/contact search helpers and Scout's record map.
   - If **no match**: reply asking the operator to clarify (name/phone). Do not
     guess.
   - If **multiple matches**: reply listing the candidates (name + phone + last
     message snippet) and ask which one. Do not guess.

3. **Execution, confirm-gated per the rules:**
   - `move_stage` is an outward/irreversible-ish action → **queue a confirm
     proposal** via `telegram_ops._queue_pending`; on ✅ call
     `handle_move_opportunity` / `add_to_pipeline`. On ❌ discard.
   - `tag` add/remove is internal + reversible → per CLAUDE.md it MAY auto-apply
     without a confirm (same precedent as `_autotag_hot`). Default: auto-apply
     tags, but still send a receipt. (If you prefer symmetry, gating tags too is
     acceptable — match the HOT-lead auto-tag precedent and note your choice.)
   - Wire the in-app Agents chat (`agents_chat.chat`) to the same intent →
     resolve → (confirm or execute) flow, so it works from the dashboard too,
     not just Telegram. The in-app path will need a write handle (`ghl_post`/
     `ghl_put`) or to call the existing `connector` handlers — thread that
     through (`agents_chat.chat` currently only receives `ghl_get`).

4. **Receipt.** After execution send a Telegram message + log on the agent bus,
   e.g. "Moved Christopher Giles → Under Contract; tagged ✓ (motivated)".

5. **Safety / correctness:**
   - Never move/tag a contact you couldn't unambiguously resolve.
   - Reuse the operator two-factor auth already enforced in `telegram_io`
     (`from_id == TELEGRAM_CHAT_ID` or in `TELEGRAM_ALLOWED_IDS`) — do not add a
     new unauthenticated action path.
   - Surface any GHL write failure to the operator (the do_POST/`_req` error
     surfacing already reads the body; make sure your new path reports it, not
     a silent pass).

**Acceptance:** From a Telegram message to Marcus "move <known contact> to under
contract and tag him motivated", the operator gets a ✅ confirm for the stage
move, and on tap the GHL opportunity moves + the tag is applied, with a receipt.
An ambiguous/unknown name produces a clarifying question, not a wrong write.

---

## TASK B — Surface real error bodies in the remaining API helpers

Same fix Claude applied to `review_agent._claude` and `connector.do_POST`: read
the `HTTPError` body so the operator sees the real reason. Apply to the helpers
that still bare-`raise` or stringify without reading `e.read()`:

1. `connector.py` `GHLClient._req` (≈line 96-121): on the **final non-retryable**
   `HTTPError` (the `raise` at ≈line 112), read `e.read()` and surface the GHL
   `message`/body to internal callers (e.g. `scout.apply_tags`'s `last_error`,
   poll-loop logs). **Caution:** `do_GET`/`do_POST` catch `urllib.error.HTTPError`
   to map GHL errors to 502 and they call `e.read()` themselves — do NOT consume
   the body in `_req` in a way that leaves those handlers with an empty body, and
   do NOT change the exception **type** those handlers catch (or the 502 mapping
   regresses). Safest approach: attach the parsed detail to the raised error
   while keeping it an `HTTPError` (e.g. stash `e._detail`), OR raise a custom
   subclass of `urllib.error.HTTPError`, and have the do_GET/do_POST handlers
   prefer the pre-read detail. Mirror the working `retell_io._req` pattern
   (`retell_io.py:76-85`) for the read, but preserve the type contract.
2. `agency_ads.py:~351` `create_ad` wrapper: replace
   `f"Meta API error: {type(e).__name__}"` with the real message + body; have
   `_live_create_ad` (≈379/403/430/449) and `_get` (≈104) read `e.read()`.
3. `docusign_io.py:~120/134` (`_api` + OAuth token): read `e.read()` so a bad
   template / JWT / consent error is visible in `send_contract`/`envelope_status`.
4. `agency_social.py:~98` (`_metricool_req`), `agency_workflows_io.py:~95`
   (n8n `_req`), `agency_deploy.py:~67` (GitHub `_gh_req`): read `e.read()` at the
   `HTTPError` branch for operator-visible detail.

**Acceptance:** triggering an error on each of these surfaces the upstream
provider's actual message, not "HTTP Error <code>" or a type name.

---

## TASK C — None-guards on two external write paths (low risk, do if quick)

1. `connector.py:~1014` — `/api/contract/send` does `if res.get("ok")` on
   `docusign_io.send_contract(...)`; guard against `res` being `None` (transient
   failure) before `.get`. It's a legally-binding e-sign path.
2. `connector.py:~1893` — `/api/agency/client/sync-ghl` indexes `_cl["services"]`
   and `_cl["id"]` directly; a client record saved before the `services` field
   existed → `KeyError` → 500. Use `.get` with sane defaults.

---

## Finish

- Run `python3 -c "import ast; ast.parse(open('FILE').read())"` on every file you
  touched. Report a per-file summary of what changed.
- If you touched `.jsx`, run `node /tmp/valjsx.js FILE`.
- **Do NOT** run `./deploy/push.sh` and do NOT start the server — leave the
  validated tree for the operator to deploy and SSH-verify.
