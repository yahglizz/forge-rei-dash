# Codex-Review Fixes — Missed-Leads Feature — Implementation Plan

> **For agentic workers:** Execute task-by-task. Each task names ONE file (single-file
> ownership → safe to run the 4 tasks in parallel). Apply the exact old→new code shown.
> No fix touches any `.jsx` file → **zero white-screen / dashboard-layout risk**.

**Goal:** Fix every Codex-review finding for the Missed-Leads deep-audit feature EXCEPT the
auto-send invariant (explicitly out of scope per operator).

**Architecture:** Backend-only Python. Defensive hardening of `scout_triage.retro_audit`
(date normalization, single-flight, weekly retry accounting, candidate quotas, keyless
weekly run, parse validation) + small safety fixes in `marcus_engine.py`, `connector.py`,
`agents_chat.py`. No behavior the dashboard depends on is removed — all additive/defensive.

**Tech stack:** Python stdlib (http.server connector, threading.Lock), GHL v2 API, Anthropic.

**Repo reality:** This folder is NOT a git repo. So: no `git commit`, no `pytest`. Validation
per task = `python3 -c "import ast; ast.parse(open('FILE').read())"` + the smoke harness in
Task V + a final Codex re-review. Deploy with `./deploy/push.sh root@24.199.81.124`.

**Out of scope (do NOT change):** Marcus `auto_send` behavior; the `_is_our_message` bypass
when `hint` is present (intentional re-engage); any `.jsx`.

---

## File ownership (parallelizable)

| Task | File | Findings fixed |
|------|------|----------------|
| A | `scout_triage.py` | dates/daysCold, single-flight, weekly accounting, candidate quotas, keyless weekly, parse validation |
| B | `marcus_engine.py` | exact conversation-ID match |
| C | `connector.py` | days validation (no 500), best-effort bus send |
| D | `agents_chat.py` | tighter audit-intent + duration parsing |

---

## Task A — `scout_triage.py` (owner: Agent A)

### A1 — Normalize message dates (fixes `daysCold=0` / `lastSellerDate=null`)
Root cause: conversation `lastMessageDate` is epoch-ms, but message `dateAdded` (from
`/conversations/{id}/messages`) is an **ISO-8601 string**; `int(...)` on it fails → `lsd=0`.

**Step A1a — add a module-level helper** (place right after the `_parse_json` function, before `_RULE`):
```python
def _to_ms(v):
    """Normalize a GHL timestamp (epoch int/str OR ISO-8601 string) to epoch ms, or None.
    Conversation lastMessageDate is epoch-ms; message dateAdded is ISO-8601 — unify them."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip()
    if s.isdigit():
        return int(s)
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        return None
```

**Step A1b — use it in `_thread_transcript`** (the `"date"` field), old:
```python
            {
                "direction": m.get("direction"),
                "body": m.get("body") or "",
                "date": m.get("dateAdded") or m.get("date"),
            }
```
new:
```python
            {
                "direction": m.get("direction"),
                "body": m.get("body") or "",
                "date": _to_ms(m.get("dateAdded") or m.get("date")),
            }
```

**Step A1c — simplify lsd in `retro_audit`** (dates are now already ms or None), old:
```python
                if not last_seller_date:
                    # Fall back to the conversation summary fields.
                    if inbound_last:
                        last_seller_said = (c.get("lastMessageBody") or "").strip()
                    last_seller_date = c.get("lastMessageDate")
                try:
                    lsd = int(last_seller_date) if last_seller_date else 0
                except (ValueError, TypeError):
                    lsd = 0
```
new:
```python
                if not last_seller_date:
                    # Fall back to the conversation summary fields.
                    if inbound_last:
                        last_seller_said = (c.get("lastMessageBody") or "").strip()
                    last_seller_date = c.get("lastMessageDate")
                lsd = _to_ms(last_seller_date) or 0
```

### A2 — Single-flight guard (no concurrent sweeps)
Old (start of `retro_audit`):
```python
        with self.lock:
            self.audit_state["running"] = True
            self._save()
        now = int(time.time() * 1000)
```
New:
```python
        with self.lock:
            if self.audit_state.get("running"):
                # Already sweeping — don't launch a second fan-out of GHL+Claude calls.
                latest = dict(self.audits[0]) if self.audits else self._audit_default()
                latest["running"] = True
                latest["summary"] = "A sweep is already running — showing the last result."
                return latest
            self.audit_state["running"] = True
            self._save()
        now = int(time.time() * 1000)
```
(The existing `finally` already resets `running=False`. Because we `return` BEFORE setting
running ourselves in that branch, we must NOT hit the finally with a false reset — but the
finally runs on every return inside the try. The early return above is OUTSIDE the try, so
the finally does not run for it. Verify: the `with self.lock:` block is before `try:`. ✔)

### A3 — Weekly retry accounting (don't suppress retries for 7 days on failure)
**Step A3a — add a constant** next to `WEEKLY_AUDIT_MS`:
```python
WEEKLY_RETRY_MS = int(os.environ.get("FORGE_SCOUT_AUDIT_RETRY_MIN", "360")) * 60 * 1000  # 6h
```

**Step A3b — track fetch success in `retro_audit`.** Old:
```python
            try:
                convos = self._fetch_conversations_since(cutoff)
            except Exception as e:  # noqa: BLE001
                self.last_error = str(e)
                convos = []
            scanned = len(convos)
```
New:
```python
            fetch_ok = True
            try:
                convos = self._fetch_conversations_since(cutoff)
            except Exception as e:  # noqa: BLE001
                self.last_error = str(e)
                convos = []
                fetch_ok = False
            scanned = len(convos)
```

**Step A3c — only mark weekly SUCCESS when the fetch worked.** In the report dict, old:
```python
                "lastWeeklyAt": now if auto else self.audit_state.get("lastWeeklyAt"),
```
New:
```python
                "lastWeeklyAt": (now if (auto and fetch_ok)
                                 else self.audit_state.get("lastWeeklyAt")),
```
In the `with self.lock:` state write, old:
```python
                self.audit_state["lastRanAt"] = now
                if auto:
                    self.audit_state["lastWeeklyAt"] = now
```
New:
```python
                self.audit_state["lastRanAt"] = now
                if auto:
                    self.audit_state["lastWeeklyAttemptAt"] = now
                    if fetch_ok:
                        self.audit_state["lastWeeklyAt"] = now
```

**Step A3d — rewrite `_maybe_weekly_audit`** so success → ~weekly, failure → retry after
`WEEKLY_RETRY_MS` (not every poll, not 7 days), and keyless runs are allowed (A5). Old:
```python
    def _maybe_weekly_audit(self):
        """Run a weekly auto-sweep if due. Self-rate-limited, safe every loop."""
        try:
            if not _scout_key():
                return
            if self.audit_state.get("running"):
                return
            last = self.audit_state.get("lastWeeklyAt") or 0
            now = int(time.time() * 1000)
            if (now - last) >= WEEKLY_AUDIT_MS:
                self.retro_audit(7, auto=True)
        except Exception as e:  # noqa: BLE001
            self.last_error = f"weekly audit: {e}"
```
New:
```python
    def _maybe_weekly_audit(self):
        """Run a weekly auto-sweep if due. Self-rate-limited, safe to call every loop.
        Success cadence ~weekly; on failure it retries after WEEKLY_RETRY_MS (not every
        poll, not a 7-day blackout). Runs even with no Anthropic key (deterministic
        degrade in retro_audit)."""
        try:
            if self.audit_state.get("running"):
                return
            now = int(time.time() * 1000)
            last_ok = self.audit_state.get("lastWeeklyAt") or 0
            last_try = self.audit_state.get("lastWeeklyAttemptAt") or 0
            if (now - last_ok) >= WEEKLY_AUDIT_MS and (now - last_try) >= WEEKLY_RETRY_MS:
                self.retro_audit(7, auto=True)
        except Exception as e:  # noqa: BLE001
            self.last_error = f"weekly audit: {e}"
```

### A4 — Candidate quotas (don't let soft-nos crowd out cold-after-signal leads)
Old candidate-build + sort block:
```python
            candidates = []   # list of conv dicts that had seller engagement in window
            for c in convos:
                cid = c.get("id")
                contact_id = c.get("contactId")
                if not cid or not contact_id:
                    continue
                body = c.get("lastMessageBody") or ""
                # Skip dead / DNC ("said stop / not interested").
                if marcus_engine.classify(body) == "DNC":
                    continue
                last_dir = c.get("lastMessageDirection")
                inbound_last = (last_dir == "inbound"
                                and not marcus_engine._is_our_message(body))
                # Skip our-own-outreach-only: outbound-last AND our own text inbound.
                if not inbound_last and last_dir != "inbound":
                    # outbound-last is fine as a candidate (could've gone cold after
                    # a positive signal) — keep it. Only the deep read decides.
                    pass
                candidates.append((c, inbound_last))
            # Prefer inbound-last (waiting on us), then most recent. Cap deep-reads.
            candidates.sort(key=lambda t: (0 if t[1] else 1,
                                           -(t[0].get("lastMessageDate") or 0)))
            candidates = candidates[:AUDIT_CANDIDATES]
            n_candidates = len(candidates)
```
New:
```python
            inbound_c, outbound_c = [], []   # split so soft-nos can't eat the whole budget
            for c in convos:
                cid = c.get("id")
                contact_id = c.get("contactId")
                if not cid or not contact_id:
                    continue
                body = c.get("lastMessageBody") or ""
                # Skip dead / DNC ("said stop / not interested").
                if marcus_engine.classify(body) == "DNC":
                    continue
                last_dir = c.get("lastMessageDirection")
                inbound_last = (last_dir == "inbound"
                                and not marcus_engine._is_our_message(body))
                if inbound_last:
                    # Inbound-last that's an explicit soft-no isn't a MISSED lead — it's
                    # nurture. Don't let it consume a deep-read slot.
                    if marcus_engine._is_soft_no(body):
                        continue
                    inbound_c.append((c, True))
                else:
                    # Outbound-last (our follow-up went unanswered) — the classic
                    # cold-after-a-reply case. Keep for the deep read to decide.
                    outbound_c.append((c, False))
            inbound_c.sort(key=lambda t: -(t[0].get("lastMessageDate") or 0))
            outbound_c.sort(key=lambda t: -(t[0].get("lastMessageDate") or 0))
            # Reserve ~1/3 of the budget for cold-after-reply (outbound-last) leads so a
            # wave of fresh inbound replies can't crowd them out, then backfill.
            out_quota = max(1, AUDIT_CANDIDATES // 3)
            picked = outbound_c[:out_quota] + inbound_c
            picked = picked[:AUDIT_CANDIDATES]
            # Backfill any unused outbound budget with more inbound (and vice-versa).
            if len(picked) < AUDIT_CANDIDATES:
                extra = outbound_c[out_quota:]
                picked = (picked + extra)[:AUDIT_CANDIDATES]
            candidates = picked
            n_candidates = len(candidates)
```
(Downstream loop `for c, inbound_last in candidates:` is unchanged — tuple shape preserved.)

### A5 — Weekly works without an Anthropic key
Already handled by A3d (the `if not _scout_key(): return` line was removed). `retro_audit`
already degrades to deterministic scoring when `key` is falsy. No extra change.

### A6 — Parse validation (bound-check verdict index, validate `missed`)
Old verdict-collection inner loop:
```python
                    if isinstance(parsed, list):
                        for obj in parsed:
                            if isinstance(obj, dict) and "i" in obj:
                                try:
                                    verdicts[int(obj["i"])] = obj
                                except (ValueError, TypeError):
                                    pass
```
New:
```python
                    if isinstance(parsed, list):
                        for obj in parsed:
                            if not isinstance(obj, dict) or "i" not in obj:
                                continue
                            try:
                                vi = int(obj["i"])
                            except (ValueError, TypeError):
                                continue
                            if 0 <= vi < len(enriched):   # ignore out-of-range indices
                                verdicts[vi] = obj
```
The build-found loop already guards `if not v.get("missed"): continue` and wraps `int(score)`
— that correctly treats a missing/false/non-bool `missed` as "not a missed lead". No change.

**Validate A:** `python3 -c "import ast; ast.parse(open('scout_triage.py').read())"` → no error.

---

## Task B — `marcus_engine.py` (owner: Agent B)

### B1 — Exact conversation-ID match (no silent wrong-thread draft)
In `make_proposal_for`, old:
```python
                cands = scoped.get("conversations", []) or []
                c = (next((x for x in cands if x.get("id") == conversation_id), None)
                     or (cands[0] if cands else None))
```
New:
```python
                cands = scoped.get("conversations", []) or []
                # Require the exact conversation — never silently draft against a
                # different thread for the same contact.
                c = next((x for x in cands if x.get("id") == conversation_id), None)
```
**Validate B:** `python3 -c "import ast; ast.parse(open('marcus_engine.py').read())"`.

---

## Task C — `connector.py` (owner: Agent C)

### C1 — `days` validation on `/api/scout/audit/run` (no 500 on junk)
Old dispatch:
```python
            elif parsed.path == "/api/scout/audit/run":
                result = SCOUT.retro_audit(days=int(body.get("days", 7) or 7),
                                           query=body.get("query"))
```
New:
```python
            elif parsed.path == "/api/scout/audit/run":
                try:
                    _ad = int(body.get("days", 7) or 7)
                except (ValueError, TypeError):
                    _ad = 7
                result = SCOUT.retro_audit(days=_ad, query=body.get("query"))
```

### C2 — Best-effort bus send on `/api/scout/handoff` (a bus failure must not 500 after the proposal exists)
Old:
```python
                if _m.get("ok"):
                    _how = "re-engage draft" if _hint else "drafted a reply"
                    agent_bus.send("scout", "marcus", "handoff",
                                   f"Handed {_info['name']} to Marcus — {_how} for approval",
                                   {"conversationId": _conv, "contactId": _cid or _info.get("contactId"),
                                    "name": _info["name"], "reengage": bool(_hint)})
                result = {**_m, "name": _info["name"]}
```
New:
```python
                if _m.get("ok"):
                    _how = "re-engage draft" if _hint else "drafted a reply"
                    try:
                        agent_bus.send("scout", "marcus", "handoff",
                                       f"Handed {_info['name']} to Marcus — {_how} for approval",
                                       {"conversationId": _conv, "contactId": _cid or _info.get("contactId"),
                                        "name": _info["name"], "reengage": bool(_hint)})
                    except Exception:
                        pass   # notification is best-effort; the proposal already exists
                result = {**_m, "name": _info["name"]}
```
**Validate C:** `python3 -c "import ast; ast.parse(open('connector.py').read())"`.

---

## Task D — `agents_chat.py` (owner: Agent D)

### D1 — Tighter audit intent + unit-bound duration parsing
Replace the whole `_detect_audit_window` function with:
```python
def _detect_audit_window(message):
    """Detect a Missed-Leads audit intent + parse the day window from a Scout message.

    Intent uses specific phrases (not loose substrings like "dig"/"30") so ordinary
    Scout questions don't trigger the expensive deep audit. Durations are parsed only
    when attached to a time unit. Returns (intent: bool, window: int) clamped 1..60.
    """
    import re
    text = (message or "").lower()
    phrases = (
        "audit", "missed lead", "missed leads", "leads i missed", "lead i missed",
        "anyone i missed", "anything i missed", "deep dive", "deep-dive",
        "go through my messages", "comb through my messages", "review my messages",
        "go back through", "sweep my messages", "leads i may have missed",
        "potential leads i", "find leads i",
    )
    intent = any(p in text for p in phrases)

    window = 7  # default
    m = re.search(r"\b(\d+)\s*(day|days|week|weeks|month|months)\b", text)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit.startswith("week"):
            window = n * 7
        elif unit.startswith("month"):
            window = n * 30
        else:
            window = n
    elif "last month" in text or "past month" in text:
        window = 30
    elif "yesterday" in text:
        window = 1
    elif "last week" in text or "past week" in text or "this week" in text:
        window = 7

    window = max(1, min(60, window))
    return intent, window
```
**Validate D:** `python3 -c "import ast; ast.parse(open('agents_chat.py').read())"`.

---

## Task V — Integration validation (main thread, after A–D land)

- [ ] **V1 — Static:** all four files `ast.parse` clean; both JSX still `node /tmp/valjsx.js`
  clean (they weren't touched — confirm anyway).
- [ ] **V2 — Smoke harness** (local connector, `FORGE_MARCUS=0`, read-only on GHL):
  - `GET /api/scout/audit` → 200 default report.
  - `POST /api/scout/audit/run {"days":7}` → `found[]` rows now show **non-zero `daysCold`**
    and non-null `lastSellerDate` for cold leads (A1 proof).
  - `POST /api/scout/audit/run {"days":"abc"}` → 200 (defaults to 7, no 500) (C1 proof).
  - Fire two `audit/run` calls back-to-back → second returns "already running" without a
    second full fan-out (A2 proof). (Best-effort to observe; not required to be exact.)
  - Scout chat `"what's my hottest lead?"` → does NOT trigger an audit; Scout chat
    `"audit my messages from the last 2 weeks"` → triggers audit, window 14 (D1 proof).
- [ ] **V3 — Codex re-review** the four changed files (read-only) to confirm the High/Medium
  items are resolved and no regression introduced. If Codex flags a remaining real issue,
  call Codex (MCP, read-only is fine for diagnosis) to propose the precise patch, apply it,
  re-validate.
- [ ] **V4 — Deploy:** `./deploy/push.sh root@24.199.81.124`; SSH-verify service `active`,
  `/api/health` + `/api/scout/audit` = 200, secrets still 404.

---

## Self-review (coverage check)
- daysCold/ISO date → A1 ✔ · single-flight → A2 ✔ · weekly accounting/backoff → A3 ✔ ·
  candidate quotas → A4 ✔ · keyless weekly → A5 (via A3d) ✔ · parse bounds → A6 ✔ ·
  exact convo match → B1 ✔ · days 500 → C1 ✔ · bus best-effort → C2 ✔ · intent/duration → D1 ✔.
- Auto-send invariant → intentionally OUT of scope (operator decision).
- No `.jsx` touched → dashboard layout/render cannot regress from these fixes.
