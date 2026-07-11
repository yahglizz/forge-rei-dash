# CODEX_N8N_TASKS — FORGE Task Bot (n8n Telegram worker)

> **MISSION.** This whole operation runs Yahjair's **wholesale real-estate agency**.
> The AI employees (Marcus = acquisitions/texting, Scout = triage) work **24/7 as if
> they were Yahjair himself** — so deals move forward while he's at his day job. Every
> seller-facing message must sound like him and follow the `wholesale-seller-texter`
> skill (warm, lowercase, patient, **call before any offer**). Reversible internal
> actions (tags, pipeline moves) auto-run; anything outward to a seller (SMS) waits
> for his ✅ tap.

> **BUILD STATUS (2026-06-19).** Live workflow `ncL3OnLs4ASfeqnp` = **34 nodes**, all
> 3 gaps now built IN n8n (hardened resolution, SMS confirm-staging + cleanup,
> pipeline move). Seller voice baked into the Marcus prompt. **Remaining:** bind the
> `GHL API Key` credential to the 3 new move HTTP nodes (Get Pipelines / Search Opp /
> Update Opp) — MCP can't attach creds to HTTP nodes, do it in the n8n UI — then
> verify that cred is the WHOLESALE PIT, and activate.

Finish wiring + test the n8n "FORGE Task Bot" so the operator can message Marcus
in Telegram and have GHL tasks executed 24/7. Claude built the core; you connect
the credentials, build the two gap features, test end-to-end, and flip it active.

**Do NOT touch the Python box / connector for this — the n8n worker is standalone
(hits GHL + Telegram + Anthropic public APIs).** Do NOT print or commit secrets.

---

## Design (locked with the operator)

Operator messages **Marcus** (one dedicated Telegram worker bot). Marcus = the
ONLY AI brain: one Anthropic call parses the command into a structured plan, then
cheap deterministic n8n nodes (the "workers") execute. Boss → workers.

**4 locked decisions:**
1. **Dedicated worker bot** (new, via BotFather) — separate from the existing
   Python alerts bot (no getUpdates conflict).
2. **Standalone GHL** — n8n calls GHL directly; no dependency on the firewalled box.
3. **Wholesale first, account-agnostic** — built for the wholesale GHL location;
   cloning to the agency account = swap credential + location + pipeline name.
4. **Auto the reversible, confirm the irreversible** — tags + pipeline moves
   auto-execute; an SMS to a seller waits for a ✅ tap.

---

## ALREADY DONE by Claude (do not rebuild)

- **n8n workflow:** "FORGE Task Bot" — id `ncL3OnLs4ASfeqnp`
  (https://yg4st.app.n8n.cloud/workflow/ncL3OnLs4ASfeqnp), 15 nodes, validated,
  **INACTIVE**. Personal project `6aGA0QntvqFa42Np`.
- **Data table:** `forge_pending_sms` — id `HlpfMFHC51umqmdT`
  (columns: `token`, `contactId`, `messageText`, `chatId`; plus auto id/createdAt).
- **Built graph:**
  - `Telegram Trigger` (updates: message + callback_query; userIds restricted to
    `8506156626`) → `Route Update` (Switch: case0 message, case1 callback)
  - **Message branch:** `Marcus (Anthropic)` (raw POST api.anthropic.com/v1/messages,
    model `claude-sonnet-4-6`, returns a JSON plan) → `Parse Plan` (Code, parses
    `{contactName,tags[],stageName,smsText,reply,chatId}`) → `Find Contact`
    (GHL GET /contacts/?locationId=&query=) → `Pick Contact` (Code, takes
    contacts[0], sets contactId/contactFound) → `Has Tags?` (IF) →
    onTrue `Apply Tags` (GHL POST /contacts/{id}/tags) → `Reply`; onFalse → `Reply`.
  - **Callback branch:** `Parse Callback` (Code, splits `ok:<token>`/`no:<token>`)
    → `Get Pending SMS` (DataTable get by token) → `Approved?` (IF decision==ok) →
    onTrue `Send SMS` (GHL POST /conversations/messages) → `Receipt`; onFalse →
    `Cancelled`.
- **Credentials — ALL 8 nodes now bound + verified (Claude did this 2026-06-18):**
  - `anthropicApi` → **"Anthropic account"** (id `CwiQQrMevejNLd14`) on Marcus ✓
  - `httpHeaderAuth` → **"GHL API Key"** (id `63U3PB9I9rHw6DDo`) on Find Contact /
    Apply Tags / Send SMS ✓
  - `telegramApi` → **"Telegram account"** (id `U58wSfY7I2r2GTuQ`) on Telegram
    Trigger / Reply / Receipt / Cancelled ✓ — holds the worker-bot token for
    `@Forgeworker23bot`; n8n "Connection tested successfully". (NOTE: planned name
    was "FORGE Worker Bot"; the rename didn't save so it kept the default name
    "Telegram account" — functionally identical, bound by id. Rename if you care.)
  - Anthropic account is FUNDED (operator added credits 2026-06-18).
  - Stray unused credential "Header Auth account 2" (id `eIjUkaOrMody0iJF`,
    httpHeaderAuth) exists from a misclick — not referenced by any node; ignore or
    delete.
  - **GHL API Key still needs a content check:** confirm it holds the WHOLESALE
    PIT (`Authorization: Bearer pit-...`), not agency. Can't read secrets via MCP.

---

## Operator prerequisites — ALL DONE (2026-06-18)

1. ✅ Worker bot created: `@Forgeworker23bot` (id `8929718316`). Token is in the
   "Telegram account" n8n credential (tested OK). Do NOT print it.
2. ✅ Anthropic credits funded.
3. ✅ Operator Telegram id confirmed = `8506156626` (matched via getUpdates: "Hi"
   from Zeek). Trigger `userIds` already locked to it. No change needed.

---

## v2 — MENU + COIN-SAFE ROUTING (Claude, 2026-06-18) — READ THIS

The workflow was upgraded so the **AI is opt-in** (save tokens) and the bot is
**button/menu driven**. New graph:

```
Telegram Trigger → Route Update (switch: message | callback)
 message  → Parse Command (Code, DETERMINISTIC, no AI) → Command Router (switch)
              ├ tag  → Find Contact → Pick Contact → Has Tags? → Apply Tags → Reply   (NO AI)
              ├ ask  → Marcus (Anthropic) → Parse Plan → Find Contact → … (the ONLY AI call)
              └ menu → Send Main Menu (inline-keyboard buttons)
 callback → Callback Kind (switch: sms-confirm | menu)
              ├ sms  → Parse Callback → Get Pending SMS → Approved? → Send SMS → Receipt/Cancelled
              └ menu → Menu Callback (Code) → Send Menu Reply
```

**Coin rule (do NOT regress):** plain text → menu (free). `tag <name> :: <tags>`
→ deterministic GHL tag (free). Buttons → instructional replies (free). AI runs
ONLY on `ask <question>` (and later, `text` drafting). Parse Command is the gate.

**Deterministic command grammar** (Parse Command Code node):
- `tag <name> :: motivated, hot` → applies tags (works now).
- `ask <question>` → Marcus AI (works now).
- `menu` / `/menu` / plain text → main menu (works now).
- `move <name> :: <stage>` and `text <name> :: <msg>` → currently fall through to
  the menu (NOT yet wired). **These are your build.**

**Main menu buttons** use `callback_data`: `emp:marcus`, `emp:scout`, `help:tag`,
`help:ask`. Callback Kind routes `ok`/`no` → SMS confirm; `emp`/`help` → Menu
Callback (returns instructional text). Telegram cred bound on Send Main Menu +
Send Menu Reply (id `U58wSfY7I2r2GTuQ`).

### Remaining v2 work (Codex)
1. **Wire `move <name> :: <stage>`** — add a Command Router case `move` →
   pipeline stage-move chain (see task 3 below). Parse Command already needs a
   branch that sets `action:'move'`, `contactName`, `stageName` (mirror the `tag`
   branch).
2. **Wire `text <name> :: <msg>`** — Command Router case `text` → Marcus drafts
   (1 AI call) OR skip AI and stage the literal msg → SMS confirm staging
   (task 2 below) → the existing `ok`/`no` callback already sends/cancels.
3. **Richer per-employee submenus** — Menu Callback currently returns text. Make
   `emp:marcus` / `emp:scout` send their OWN inline keyboards with action buttons
   (e.g. Scout `act:hot` → GHL search Hot stage → reply). Add the matching
   `act:*` cases to Callback Kind / Menu Callback.
4. (Optional) **Wizard state** — if you want tap-only flows (button → "who?" →
   reply), add a `forge_bot_state` data table (chatId, flow, step, payload) and a
   state check in Parse Command. Not required; the `<name> :: <args>` grammar
   already avoids needing state.

## YOUR TASKS (Codex)

### 1. Connect credentials — DONE by Claude; you just VERIFY the GHL secret
- ✅ Telegram credential ("Telegram account", id `U58wSfY7I2r2GTuQ`) created +
  bound to Telegram Trigger / Reply / Receipt / Cancelled. Connection tested OK.
- ✅ "Anthropic account" bound to Marcus. Account funded.
- ✅ "GHL API Key" bound to Find Contact / Apply Tags / Send SMS.
- ⚠️ **YOU MUST verify "GHL API Key" holds the WHOLESALE PIT**
  (`Authorization: Bearer pit-...`), not agency. Claude can't read secrets.
  The existing live workflows (`l6oqTk2nc4e79zjn`, `RqU55VsyxIt5Yatk`) used an
  INLINE header — if "GHL API Key" is empty/wrong, populate it from that PIT
  (copy via the n8n UI — **never print it**) or switch the 3 GHL nodes to the
  inline-header pattern. Confirm wholesale, not agency.

### 2. Build the SMS staging (feeds the already-built callback branch)
Currently nothing writes rows into `forge_pending_sms`, so the confirm flow has no
input. Add to the MESSAGE branch (off `Pick Contact`, gated when
`plan.smsText` is non-empty):
- generate a short token (e.g. `{{ $now.toMillis() }}`),
- **DataTable INSERT** into `forge_pending_sms` (`HlpfMFHC51umqmdT`):
  `{ token, contactId, messageText: smsText, chatId }`,
- **Telegram sendMessage** with an inline keyboard asking
  "Send this text to <name>? \n\n<smsText>" and two buttons:
  - ✅ Send → `callback_data: "ok:<token>"`
  - ❌ Cancel → `callback_data: "no:<token>"`
  Inline keyboard param shape (Telegram node v1.2):
  `additionalFields`/`replyMarkup: "inlineKeyboard"` →
  `inlineKeyboard.rows[].row.buttons[].{ text, additionalFields.callback_data }`.
- Wire so a command with both tags/stage AND smsText still runs the auto actions,
  then stages the SMS for confirm.

### 3. Build the pipeline stage move (auto, reversible)
When `plan.stageName` is non-empty (gate off `Pick Contact`), do the 3-call GHL
chain (no proven template existed — build fresh; all GHL calls use header
`Version: 2021-07-28`, base `https://services.leadconnectorhq.com`, the GHL cred):
1. `GET /opportunities/pipelines?locationId=8GuqpADet7ivY7wXWTpV` → pick the
   pipeline whose name contains "wholesal" → find the stage whose name matches
   `stageName` (case-insensitive) → capture `pipelineId` + target `stageId`.
2. `POST /opportunities/search?location_id=8GuqpADet7ivY7wXWTpV&contact_id={contactId}`
   → take the opportunity → `opportunityId`.
3. `PUT /opportunities/{opportunityId}` body
   `{ "pipelineId": <id>, "pipelineStageId": <stageId> }`.
Rejoin `Reply` and have the reply summarize what moved. If no opportunity exists
for the contact, reply saying so (optionally create one — operator's call).

### 4. Harden contact resolution
`Pick Contact` currently takes `contacts[0]`. Change to: 0 matches → reply
"couldn't find a contact named X" and stop; >1 matches → reply listing the
candidates (name + phone) and ask which, do NOT act on a guess.

### 5. Cleanup + (optional) memory
- Add a **DataTable deleteRows** (by token) at the end of BOTH callback paths
  (after Receipt, after Cancelled) so pending rows don't accumulate.
- Optional: add window memory / per-chat context so multi-turn commands work
  (currently each command is stateless). Keep it cheap.

### 6. Test end-to-end, then flip ACTIVE
Run the verification checklist below. Only set the workflow active once the
Telegram credential + Anthropic credits are in and a real command works.

---

## Verification checklist
- Message worker bot "tag <known contact> motivated" → tag appears in GHL, a
  Telegram reply confirms, **no** confirm prompt (auto).
- "move <known contact> to under contract" → opportunity stage changes in GHL,
  reply confirms, auto.
- "text <known contact>: just checking in on your timeline" → Marcus drafts →
  Telegram shows the draft + ✅/❌ → tap ✅ → SMS lands in the GHL conversation →
  "Sent." receipt; tap ❌ → "Cancelled", nothing sent.
- Unknown name → "couldn't find"; ambiguous (2 matches) → asks which, no write.
- A Telegram message from a non-operator id → ignored (trigger userIds guard).
- n8n execution log shows exactly ONE Anthropic call per command; GHL actions are
  plain HTTP nodes (no extra model calls) — confirms the cost model.

## Clone to the agency account later (account-agnostic)
Duplicate the workflow, then: swap `LOCATION` to `4JIvZEmkY5EjTsDRnjBN`, attach an
agency-PIT GHL credential, and change the pipeline-name filter from "wholesal" to
the agency pipeline name. Everything else is identical.

## Reference (so you don't re-research)
- GHL base: `https://services.leadconnectorhq.com` · wholesale location
  `8GuqpADet7ivY7wXWTpV`.
- Version header by endpoint: contacts/tags/opportunities = `2021-07-28`;
  conversations/messages = `2021-04-15`.
- Send SMS: `POST /conversations/messages` body `{type:"SMS", contactId, message}`
  (optional `fromNumber` E.164 for number rotation).
- Add tag: `POST /contacts/{id}/tags` body `{tags:[...]}`.
- Find contact: `GET /contacts/?locationId=&query=` → `{contacts:[{id,...}]}`.
- n8n node ids: HTTP tool/action `n8n-nodes-base.httpRequest` v4.4; Telegram
  `n8n-nodes-base.telegram` v1.2 (resource message / sendMessage); Telegram trigger
  `n8n-nodes-base.telegramTrigger` v1.3; Switch `n8n-nodes-base.switch` v3.4
  (rules.values); IF `n8n-nodes-base.if` v2.2; Data Table `n8n-nodes-base.dataTable`
  v1.1 (resource row; operations get/insert/deleteRows).
