# TASK BRIEF — Wholesale auto-reply: fix the known bugs, verify the wiring end to end

**For:** Codex (or any agent picking this up cold)
**Written:** 2026-07-30
**Repo:** `yahglizz/forge-rei-dash` · **Box:** `root@24.199.81.124` (systemd `forge-reios`)
**Read first:** `CLAUDE.md` (root) → `NORTH_STAR.md` → `forge rei/CLAUDE.md` → `forge rei/CODEX_REVIEW.md`

---

## 0. What the operator actually wants

> "My only job is to make phone calls."

A seller texts in. The system reads it, decides whether to ask one more qualifying
question or to pivot the seller onto a phone call, sends that text **itself**, and hands
the operator a call card with the facts already gathered. No approval taps in the loop for
routine replies.

That machine is **already built** (ACE — the Autonomous Conversation Engine, all 5 phases).
It is currently **`mode="off"`** because an end-to-end simulation on 2026-07-30 found real
defects in the layers ACE depends on. Your job is to fix them and prove the whole chain is
wired, so the operator can flip it on with confidence.

**You are not being asked to turn autonomy on.** Leave `ace.mode()` at `off` on the live
box. The operator flips it, not you. See §2.

---

## 1. Where the evidence came from

A harness now lives at **`forge-test-harness/e2e_seller_sim.py`**. It runs the REAL
pipeline — real Marcus screening (Claude), real drafting off the real vault playbook, the
real `sms_guard` stack with `autonomous=True`, real `legit_check` — and fakes exactly one
layer: the GoHighLevel HTTP transport. Nothing can text a real person. It copies
`forge rei/*.py` into a scratch dir first, so every `marcus_state/*.json` write is isolated
from production.

It also symlinks the out-of-repo classifier toolkit (see B1) into the scratch tree so
`marcus_engine`'s sibling-directory lookup resolves the same way it does in production, and
prints `usingProductionClassifier` in its `PROBE` line. **If that flag is `false`, the run is
using the weaker `_fallback_classify` and its classification results mean nothing** — fix the
link before drawing conclusions.

Run it (the Windows dev machine has only Microsoft Store python stubs — real python3 is on
the box):

```bash
scp -i ~/.ssh/forge_droplet forge-test-harness/e2e_seller_sim.py root@24.199.81.124:/tmp/ && ssh -i ~/.ssh/forge_droplet root@24.199.81.124 'set -a; . /etc/default/forge-reios >/dev/null 2>&1; set +a; export FORGE_VAULT=/opt/forge/vault FORGE_MARCUS=0 FORGE_SMS_DEDUPE_MINUTES=0; python3 /tmp/e2e_seller_sim.py'
```

`FORGE_VAULT` is **required** and is deliberately not in `/etc/default/forge-reios` — it
lives in the systemd unit. Without it the drafter silently loads a 0-byte playbook and every
draft you read is fake. The harness prints a loud warning if that happens.

### What the run produced (baseline — reproduce this before changing anything)

**Worked:** 5 auto-sends, **0 gate blocks, 0 errors**, 1 call-pivot, 1 call-ready card.
Every draft was in the operator's voice and none quoted a number. The drafter and
`sms_guard` are in good shape. Example pivot text:

> "appreciate that Dana, before i throw out a number i want to make sure i understand the
> property better so i can get you something real, you free for a quick call today or
> tomorrow?"

**Broke:** everything in §3.

---

## 2. Hard rules — violating any of these is worse than not doing the task

These come from `CLAUDE.md` and are non-negotiable.

1. **Never state, negotiate, hint at, or invent a price / offer / number in a text to a
   seller.** Not ever, under any mode. The offer is given by a human on a phone call. This
   is enforced in the prompt AND in code (`marcus_engine._no_price_over_text`,
   `sms_guard._quotes_price_or_offer`). Do not weaken either.
2. **Do not arm ACE or autopilot on the live box.** `ace.set_mode()` must stay `off` in
   production when you finish. Test only through the harness or a scratch state dir. Same
   for `test_mode` — leave the whitelist empty.
3. **Additive edits only.** Do not delete existing features or code paths.
4. **Secrets stay in `*.env` outside the web root**, git-ignored, must 404 over HTTP. Never
   paste a key into a commit, a log, or a chat. Do not rotate anything. When you need a var
   name from `/etc/default/forge-reios`, `grep` for it — never `cat` the file.
5. **Validate before deploy, never push a broken state.**
   ```bash
   python3 -c "import ast; ast.parse(open('FILE.py').read())"
   node deploy/valjsx.js FILE.jsx
   ```
6. **Agents propose; humans act outward.** Nothing you build may send, post, spend, or move
   a pipeline on its own beyond what ACE already does under its existing gates.

**Deploy:** `git push origin main` — the box autopulls within ~60s, validates, and
self-deploys. `./deploy/quick-deploy.sh` does it immediately. `./deploy/push.sh` is
Mac-only and the ONLY path that syncs secrets + the Obsidian vault.

---

## 3. The bugs

Ordered by cost. Each has a repro you can run in one command.

---

### B1 — The production classifier lives outside the repo (architecture; fix this first)

**Severity: high.** It shapes B2 and B3.

`marcus_engine.py:37-54` tries to import the real classifier from a sibling toolkit:

```python
_SCRIPTS_CANDIDATES = [
    HERE.parent / "marcus-wholesale-agent" / "scripts",
    Path.home() / "Desktop" / "marcus-wholesale-agent" / "scripts",
]
```

On the box that resolves to `/opt/forge/marcus-wholesale-agent/scripts/scan_missed_replies.py`.
**That file is not in git.** It is not in the repo, not tracked, not deployed by `git push`,
and not present on the Windows or Mac dev machines. Confirm:

```bash
git ls-files | grep -c scan_missed_replies   # -> 0
```

When the import fails, `marcus_engine.py:57-70` silently substitutes `_fallback_classify`,
which is a materially weaker classifier. So **dev and production run different code**:

| input | box (`scan_missed_replies`) | dev clone (`_fallback_classify`) |
|---|---|---|
| `what would you pay` | `PRICE` | `CONTINUE` |
| `what can you do for it` | `PRICE` | `CONTINUE` |

Any local test of reply behavior is meaningless, and the live classifier can never be code
reviewed or rolled back.

**Fix:** move the classifier's phrase lists and `classify()` into a version-controlled repo
module (suggest `forge rei/seller_classify.py`). Keep the external-toolkit import as an
optional *override* for backward compatibility, but make the repo copy the source of truth
and the fallback. Log at startup which implementation is live, and surface it in
`/api/marcus/status` so a silent divergence is visible.

**Acceptance:** `inspect.getsourcefile(marcus_engine.classify)` points inside the repo on
both the box and a fresh clone, and the table above returns identical results in both.

---

### B2 — `classify()` misses 9 of 14 real price asks

**Severity: high.** This is the trigger for the single most valuable action in the funnel.

`ace.decide()` (`forge rei/ace.py:281-284`) only pivots the seller onto a call when
`classify(last_seller_msg)` returns `PRICE` or `READY`. The live phrase list
(`scan_missed_replies.py:39`) is:

```python
PRICE_PHRASES = ["how much", "what would you", "your offer", "what can you", "price", "$"]
```

Measured misses — each one returns `CONTINUE`, so ACE does **not** pivot:

```
what kind of numbers are you thinking
what were you thinking
give me a ballpark
whats the most you can do
what are you offering
whats it worth to you
what number did you have in mind
send me your best
whats your range
```

Observed live in scenario B turn 4: the seller asked "what kind of numbers are you
thinking" and ACE replied with *another qualifying question* instead of pivoting to the call.

**Fix:** broaden the price-ask detection (after B1, in the repo module). Patterns worth
covering: `ballpark`, `range`, `numbers`, `what number`, `your best`, `most you can`,
`worth to you`, `what are you offering`, `what were you thinking`. Prefer regex with word
boundaries over substring matching so `price` doesn't fire inside `surprise`.

**Watch out:** widening PRICE also widens what trips the pivot. Pair this with B3 — pivoting
is a one-shot per thread (§B7), so a false PRICE burns it.

**Acceptance:** all 14 strings in `PRICE_ASKS` in the harness classify as `PRICE`, and the
harness's scenario B turn 4 shows `aceAction: "pivot"`.

---

### B3 — `READY_PHRASES` is too broad; ACE burns its one pivot on message 1

**Severity: high.**

`scan_missed_replies.py:40`:

```python
READY_PHRASES = ["yes", "interested", "open to", "let's talk", "lets talk",
                 "tell me more", "sure", "okay", "ok"]
```

Bare tokens `ok` / `okay` / `sure` / `yes` make almost any polite seller message `READY`.
Observed in scenario A turn 1: *"yes im still thinking about selling it, what did you have
in mind"* → `READY` → ACE fired its **one and only** call-pivot immediately, with **zero of
the five qualifying facts gathered**. Turns 2–5 were then permanently silent (correct per
§B7), so the operator got a call card that started empty. The whole qualifying-question lane
never ran on that thread.

Note the interaction: `_do_pivot` force-sets state `CALL_READY` and writes `callPivotAt`, so
this is irreversible for the thread.

**Fix — decide the policy, then implement.** Two defensible options; recommend one to the
operator rather than picking silently:

* **(a) Tighten READY.** Require a commitment signal (`im ready`, `lets do it`, `send the
  contract`, `when can you come`), not mere acknowledgement. "yes im still thinking about
  it" becomes `CONTINUE`, so ACE qualifies first and pivots later with a full card.
* **(b) Gate the pivot on facts.** Keep READY broad, but in `ace.decide()` require at least
  N known facts before a `READY`-triggered pivot; an explicit `PRICE` ask still pivots
  immediately regardless (a seller asking for a number will not tolerate another question).

(b) is probably closer to what the operator means by "pop the home seller to just call"
while still filling the card. Confirm before building.

**Acceptance:** scenario A turn 1 no longer pivots on a merely-interested opener; the pivot
lands on turn 4 (the explicit price ask) with `condition`/`timeline`/`motivation`/`occupancy`
already true in `facts`.

---

### B4 — `_is_denial()` false-positives on 7 normal seller sentences, silently killing the lead

**Severity: high. This is costing leads right now, under manual approval, independent of ACE.**

`forge rei/marcus_engine.py:179-183`:

```python
_IDENTITY_DENIAL_RE = re.compile(
    r"(?i)\b(?:i\s*am\s*not|i'?m\s*not|this\s*is\s*not|this\s*isn'?t|that'?s\s*not)\s+"
    r"(?!interested|selling|sure|ready|available|looking|able|going|going\s*to)"
    r"[a-z]{2,}\b"
)
```

The negative lookahead whitelists a few continuations but not the common ones (`in`, `the`,
`at`, `against`, `a`, `really`). Anything else after "im not" is treated as a wrong-number /
mistaken-identity reply. Confirmed false positives:

```
im not in a huge rush              -> denial
im not in a position to sell yet   -> denial
im not the only owner              -> denial
im not at the house right now      -> denial
im not really sure what its worth  -> denial
im not against selling             -> denial
im not in town till friday         -> denial
```

Every one of those is a motivated seller. Consequence chain: `Screener.screen()` returns
`{"skipped": "wrong number / not the seller — not entertaining"}` → no screening record →
`connector._ace_update_from_screening` finds no `convId` and returns → **no report, no ACE,
no call card, no Do Today task**. The lead goes dark with no error anywhere.

Repro:

```bash
ssh -i ~/.ssh/forge_droplet root@24.199.81.124 'cd /opt/forge/forge-rei && python3 -c "import marcus_engine as m; print(m._is_denial(\"im not in a huge rush\"))"'
```

**Fix:** invert the logic. A blanket "anything after *im not*" rule cannot be made safe with
a whitelist of exceptions — match the actual identity-denial shapes instead
(`im not the owner`, `im not the seller`, `you have the wrong`, `i dont own`, `never owned`,
`thats not me`, `who is this`). Keep true denials working: `wrong number` and
`thats not my house anymore` must still return `True`.

**Acceptance:** all 8 strings in the harness's `NOT_DENIALS` list return `False`; the true
denials still return `True`; add these as cases in `forge rei/test_sms_guard.py` or a new
`test_marcus_filters.py` so it cannot regress.

---

### B5 — Skill loaders are vault-only with no seed fallback; a wrong path silently disarms the drafter

**Severity: medium-high (silent).**

`marcus_engine.py:510` (`_load_playbook`) and `marcus_engine.py:530` (`_load_reply_rubric`)
read exclusively from `brain_io.VAULT`. If `FORGE_VAULT` is unset or wrong, both return `""`
and the drafter runs with **no seller-reply rubric and no voice playbook** — no exception, no
log line, no UI signal. Drafts still generate; they are just generic.

Proven: the first harness run without `FORGE_VAULT` reported
`replyRubricBytes: 0, playbookBytes: 0`. With it set: `10640` and `15403`.

Seed copies already exist in the repo at `forge-marcus/skills/` (`seller-reply-playbook.md`,
`yahjair-voice.md`, `marcus-playbook.md`, `closing-plays.md`) and are **never read**.

**Fix:** mirror the pattern `agent_creed.py` already uses (`_SEED_DIRS` — seed first, vault
last so the vault wins when present). Load the seed if the vault copy is missing, and expose
a `skill_sources()` helper reporting which file each skill came from and its byte count.

Surface it: add a **DEGRADED PROMPT** chip to `AcePanel` in `forge rei/ace.jsx` when any
skill resolves to 0 bytes, and include the same signal in `/api/ace/status`. A drafter
running blind must be visible, not silent.

**Acceptance:** deleting/renaming the vault copy still yields non-zero `replyRubricBytes`
(from the seed), and the harness's `CONFIG` line reports the seed as the source.

---

### B6 — Drafts drift off the qualifying fact ACE assigned, and re-ask answered questions

**Severity: medium (quality).**

`ace.py:534` builds a hint naming exactly one fact:

```python
hint = ("Ask the seller, in your voice, ONE short natural question to learn their "
        f"{d['fact']}: \"{d['question']}\". Do not quote a price or make an offer.")
```

Observed in scenario B:

* turn 2 — assigned `qualify:timeline`, draft asked for a call instead of the timeline.
* turn 3 — assigned `qualify:price`, draft asked for a call instead.
* turn 4 — draft asked *"what condition is the basement in"* when the seller had described
  the basement two messages earlier.

Driving to a call is not a wrong instinct, but ACE thinks it gathered a fact it did not, and
re-asking an answered question reads as not listening.

**Fix:** put the already-known facts into the hint explicitly ("You already know: condition
= …, occupancy = …. Do NOT ask about these again."), and have the drafter's grounding
include the screening report's known values, not just the raw thread. Consider a cheap
post-draft check: if the draft is assigned fact X and contains no question about X, either
re-prompt once or let `ace` record the turn as a pivot rather than a fact-gathering reply, so
`facts` stays honest.

**Acceptance:** across a harness run, every `aceAction: "reply"` turn produces a draft that
asks about its assigned `aceReason` fact, and no draft asks about a fact already `true` in
`facts`.

---

### B7 — After the pivot, ACE is permanently silent, with no safety net

**Severity: policy — get the operator's decision before building.**

`ace.py:271` — once `callPivotAt` is set, every later decision returns
`escalate: "call-pivot sent — operator's call"`, forever. That is deliberate and correct:
one pivot per thread, then the human owns it.

But observed in scenario A: after the pivot the seller sent **four more messages**, including
an explicit price ask and *"ok i can talk tomorrow after 5"* — and received nothing. If the
operator does not call promptly, an engaged seller is ghosted mid-conversation.

**Proposed fix (needs sign-off):** do **not** resume texting the seller. Instead, when a
pivoted thread receives ≥1 new inbound and the call-ready card has not been `ack`ed within N
hours, re-ping the operator on Telegram with the new message quoted, escalating urgency. The
seller-facing silence contract stays intact; only the operator nudge changes.

---

### B8 — Two gates are still unverified

* **Send-ledger dedupe.** The harness sets `FORGE_SMS_DEDUPE_MINUTES=0` to compress days
  into seconds, which disables the `send_ledger.touched_within` check at
  `sms_guard.py:173-176`. **That gate has never been exercised end to end.** Write a
  dedicated test: two ACE sends on one thread inside the window, assert the second is
  blocked with `gate: "send_ledger"`.
* **Telegram receipts.** `telegram_io` resolves creds relative to the app dir, so from the
  harness's scratch tree it silently no-ops — meaning the `📣 ACE call-pivot` receipt and its
  `acestop:` / `aceundo:` inline buttons were never exercised. Verify the callback handlers
  actually reach `ace.hold()` and that a tap stops the thread.

---

### B9 — Half-finished items from the ACE rollout plan

Verify each is present and wired, or finish it:

* `GET /api/autopilot/status` + `POST /api/autopilot/toggle` HTTP routes — `autopilot.py`
  has `status()` / `set_enabled()` but check whether `connector.py` exposes them and whether
  `ace.jsx` has the toggle.
* Nurture check-back auto-send in `followup._scan_due_checkbacks` (the 4th auto lane; still
  approval-only).
* `skill_sources()` + the DEGRADED chip (see B5).

---

## 4. End-to-end wiring audit

Independent of the bugs, walk the chain and confirm each hop actually fires. Report any hop
you could not verify rather than assuming it works.

| # | Hop | Where | Verify |
|---|---|---|---|
| 1 | Seller texts in → GHL conversation | GHL | `/conversations/search` returns it with `lastMessageDirection: inbound` |
| 2 | Scout sweep picks it up | `scout_triage.py`, `FORGE_SCOUT_INTERVAL=180` | scores + buckets it (asap/warm/nurture/dead) |
| 3 | Scout auto-hands call-worthy leads | `SCOUT.on_scored` → `connector._auto_screen` | fires for asap+warm only |
| 4 | Marcus screens | `marcus_screening.Screener.auto_screen` | report with the 5 facts; **B4 can silently abort here** |
| 5 | Screening → conversation state | `connector._ace_update_from_screening` | `CONVO.update` derives `facts` + advances state |
| 6 | ACE decides | `ace.decide` | reply / pivot / escalate / stop — **B2, B3 land here** |
| 7 | Draft | `marcus_engine.make_proposal_for` → `_ai_draft` | loads the vault rubric — **B5**; obeys the hint — **B6** |
| 8 | Price scrub | `_no_price_over_text` | any leaked figure → call-pivot fallback |
| 9 | Central gate | `sms_guard.guard(autonomous=True)` | DNC, hours, clock-out, soft-no, our-message, price/offer, legit, dedupe (**B8**), daily cap |
| 10 | Send | `marcus_engine._send` → `POST /conversations/messages` | + `send_ledger.record` |
| 11 | Ledger | `convo.note_reply` / `note_call_pivot` | `callPivotAt` is the durable one-pivot dedupe |
| 12 | Call card | `ace.call_ready_upsert` | `marcus_state/call_ready.json` + Telegram 📞 ping, deduped by `pingedAt` |
| 13 | Receipt + kill switches | `telegram_io.send` with `acestop:` / `aceundo:` | **B8** — verify a tap reaches `ace.hold()` |
| 14 | Operator ack | `ace.ack` | → `HANDED_OFF`, thread terminal |
| 15 | Atlas underwrites | `deal_prep.py` | anchors land on the call card |
| 16 | Digest | `ace.digest` → `/api/ace/digest` | counts match what actually happened |

Kill switches that must work at every stage: `ace.set_mode("off")`, `forge_ops.paused()`
(clock-out), per-thread `held`, and `test_mode` scoping.

---

## 5. Definition of done

1. Baseline harness run reproduced **before** any code change (so your deltas are real).
2. B1, B2, B3, B4, B5, B6 fixed. B7 written up as a recommendation with the operator's
   decision recorded. B8 covered by new tests. B9 either verified present or finished.
3. New regression tests for every fixed bug — put classifier/filter cases in a
   `forge rei/test_marcus_filters.py`, ACE behavior in `forge rei/test_ace.py`.
4. Existing suites still green:
   ```bash
   cd "forge rei" && python3 test_ace.py && python3 test_sms_guard.py && python3 test_dropship_skills.py
   ```
   (Baseline before this task: `test_ace.py` 82/82.)
5. Post-fix harness run attached to your report, showing: 14/14 price asks classify as
   `PRICE`, 0 denial false positives, non-zero playbook bytes, scenario A pivoting on the
   price ask rather than the opener, and no draft re-asking an answered fact.
6. Validated and deployed via `git push origin main`; box health-checked
   (`systemctl status forge-reios` active, endpoints 200, `*.env` 404 over HTTP).
7. **`ace.mode()` is `off` and `test_mode` is empty on the live box when you finish.**
8. Anything reusable you learn becomes a skill update per `CLAUDE.md` §4 — do not leave a
   good pattern as a one-off.

## 6. Report back with

* What you changed, per bug, with `file:line`.
* Anything in §4 you could **not** verify, stated plainly rather than assumed.
* Your recommendation on B3 (a vs b) and B7, with reasoning.
* A straight go/no-go on whether the operator should flip ACE to `full`, and what you would
  watch for the first week.
