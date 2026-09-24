"""daycare_replies.py — Solomon's family-comms lane: drafts replies to parent texts.

Why: parents text the daycare GHL number around the clock and the Lead Desk can only say
"someone needs to answer this". This loop writes the answer — in the center's real voice,
grounded in the verified fact sheet — so the owner's job at 6am is one tap, not a blank box.

Every 5 min on the box (FORGE_MARCUS gate lives in connector.main, knob FORGE_DAYCARE_REPLIES):
  1. One GET of the daycare location's 100 newest conversations; keeps threads whose last
     message is an inbound SMS.
  2. `gate()` (pure) decides whether a human reply is actually owed, and YIELDS to the GHL
     automations first: speed-to-lead owns the first touch (incl. the overnight queue),
     STOP/HELP keyword auto-replies own those words, anything already answered (by a
     workflow or a person) is done, and a fresh inbound gets a grace window so a workflow's
     stop-on-response or a staff member typing live is never raced.
  3. For threads that pass, one Claude call (Sonnet 5 by default) returns JSON:
     draft / escalate / no_reply + category + unknowns. Code then flags anything the owner
     must eyeball: a phone number not on the fact sheet, a dollar figure, emoji, length.
  4. Drafts land in marcus_state/daycare_replies.json. Nothing is sent.

Sending: POST /api/daycare/replies/approve is the owner's tap (CLAUDE.md rule 2, §10 —
family SMS is owner-initiated). It re-reads the live thread first and refuses if anyone
replied since the draft, if the parent opted out, or outside 8am–9pm ET.

Skills, in prompt order: daycare creed (agent_creed) → daycare-context.md →
daycare-parent-reply.md (rubric + fact sheet) → daycare-voice.md. Never caveman — this is
a family-facing message. Stdlib only.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import daycare_ghl
import daycare_leads
import forge_atomic
import forge_heartbeat
import forge_ops
import seller_classify

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "daycare_replies.json"
_LOCK = threading.Lock()

INTERVAL = int(os.environ.get("FORGE_DAYCARE_REPLIES_INTERVAL", "300"))
MODEL = os.environ.get("FORGE_DAYCARE_REPLY_MODEL", "claude-sonnet-5")
GRACE_SEC = int(os.environ.get("FORGE_DAYCARE_REPLY_GRACE_MIN", "5")) * 60
MAX_DRAFTS = int(os.environ.get("FORGE_DAYCARE_REPLY_MAX", "8"))   # Claude calls per sweep
MAX_READS = 40                         # thread GETs per sweep
STL_WAIT_SEC = 15 * 60                 # speed-to-lead tag on, nothing sent yet: workflow pending
LOOKBACK_SEC = 7 * 86400               # older unanswered texts are the Lead Desk's problem
KEEP_SEC = 30 * 86400                  # prune closed drafts after this

STL_TAGS = {"speed-to-lead-trigger", "speed-to-lead-trigger-amt"}
# Carrier / GHL keyword auto-replies own these words — never answer them.
KEYWORDS = {"stop", "stopall", "unsubscribe", "cancel", "end", "quit", "start", "unstop",
            "yes start", "help", "info"}
# Our own automated first-touch copy (enroll.js SMS_SIGNATURE + legacy wording).
OUR_SIGNATURES = ("this is management over at", "this is yahjair over at")
# The only numbers a draft may carry (fact sheet in daycare-parent-reply.md).
ALLOWED_PHONES = {"2152365439", "2157870100", "8884615437"}   # 1-888-461-KIDS
MAX_CHARS = 480                        # 3 SMS segments

_PHONE_RE = re.compile(r"(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?(?:\d{4}|KIDS)", re.I)
_MONEY_RE = re.compile(r"\$\s?\d")
_EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


# ── pure helpers ──────────────────────────────────────────────────────────────
def _events(messages):
    """GHL messages -> sorted [{id, t, dir, sms, auto, body}]. Activity rows skipped."""
    out = []
    for m in messages or []:
        t = daycare_leads._sec(m.get("dateAdded") or m.get("date"))
        d = m.get("direction")
        mtype = str(m.get("messageType") or m.get("type") or "").upper()
        if t is None or d not in ("inbound", "outbound") or "ACTIVITY" in mtype:
            continue
        body = str(m.get("body") or "")
        auto = (str(m.get("source") or "").lower() in daycare_leads.AUTO_SOURCES
                or any(s in body.lower() for s in OUR_SIGNATURES))
        out.append({"id": str(m.get("id") or ""), "t": t, "dir": d, "sms": "SMS" in mtype,
                    "auto": d == "outbound" and auto, "body": body})
    out.sort(key=lambda e: e["t"])
    return out


def _is_keyword(body):
    w = re.sub(r"[^a-z ]", "", (body or "").lower()).strip()
    return w in KEYWORDS


def gate(contact, messages, now):
    """Pure: does this thread owe a human reply right now? -> (True, None) or
    (False, code). Every False is a hold — the next sweep re-checks. `contact` may be {}
    when unknown (tag/DND rules then can't fire; the message rules still do)."""
    ev = _events(messages)
    if not ev:
        return False, "no_thread"
    last = ev[-1]
    if last["dir"] == "outbound":
        return False, "answered"                 # a workflow or a person already replied
    if not last["sms"]:
        return False, "not_sms"                  # webchat/call/email: Lead Desk alerts those
    ins = [e for e in ev if e["dir"] == "inbound"]
    if any(seller_classify.is_opt_out(e["body"]) for e in ins):
        return False, "opted_out"
    if _is_keyword(last["body"]):
        return False, "keyword"                  # GHL STOP/HELP auto-replies own it
    if contact.get("dnd"):
        return False, "dnd"
    age = now - last["t"]
    if age < GRACE_SEC:
        return False, "grace"                    # let workflows / live staff go first
    if age > LOOKBACK_SEC:
        return False, "stale"
    tags = {str(t).strip().lower() for t in (contact.get("tags") or [])}
    outs = [e for e in ev if e["dir"] == "outbound"]
    if not outs:
        if daycare_leads.QUEUED_TAG in tags:
            return False, "stl_queued"           # 8am flush sends the first touch
        created = daycare_leads._sec(contact.get("dateAdded")) or ins[0]["t"]
        if tags & STL_TAGS and now - created < STL_WAIT_SEC:
            return False, "stl_pending"          # workflow's 3-min first touch not out yet
    return True, None


def flags(draft):
    """Things the owner must eyeball before tapping send (and that would block any
    future auto-send)."""
    f = []
    for m in _PHONE_RE.findall(draft or ""):
        digits = re.sub(r"\D", "", m.upper().replace("KIDS", "5437"))
        if digits[-10:] not in {p[-10:] for p in ALLOWED_PHONES}:
            f.append("unverified_phone")
            break
    if _MONEY_RE.search(draft or ""):
        f.append("money")
    if _EMOJI_RE.search(draft or ""):
        f.append("emoji")
    if len(draft or "") > MAX_CHARS:
        f.append("long")
    return f


def _center(tags):
    loc = next((t for t in sorted(tags) if t.startswith("loc-")), "")
    label = daycare_leads.CENTER_LABEL.get(loc, "")
    brand = "A Mother's Touch" if "1923" in loc else ("A Touch of Blessings" if loc else "")
    return label, brand


def _parse(raw):
    s = (raw or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1].rsplit("```", 1)[0]
    a, b = s.find("{"), s.rfind("}")
    return json.loads(s[a:b + 1])


# ── the drafter (one Claude call) ─────────────────────────────────────────────
def _system():
    import agent_creed
    import daycare_context
    rubric = daycare_context.load_skill("daycare-parent-reply.md").strip()
    voice = daycare_context.load_skill("daycare-voice.md").strip()
    if not rubric or not voice:
        raise RuntimeError("daycare-parent-reply.md / daycare-voice.md missing — no draft")
    return ("You are Solomon's family-comms desk at A Touch of Blessings. You draft the next "
            "text back to a parent; the owner approves and sends it. Output JSON only."
            + agent_creed.block("daycare")
            + daycare_context.context_block(6000)
            + "\n\n=== PARENT REPLY RUBRIC + VERIFIED FACT SHEET (facts here win) ===\n" + rubric
            + "\n\n=== HOW ATOB TEXTS (voice) ===\n" + voice)


def _prompt(contact, ev, now):
    fam = daycare_ghl._family_from_contact(contact) if contact else {}
    tags = {str(t).strip().lower() for t in (contact.get("tags") or [])}
    label, brand = _center(tags)
    kind = ("enrolled family" if tags & daycare_leads.FAMILY_TAGS
            else "enrollment lead" if tags & daycare_leads.LEAD_TAGS else "unknown")
    lines = []
    for e in ev[-15:]:
        who = "PARENT" if e["dir"] == "inbound" else ("CENTER (automated)" if e["auto"] else "CENTER (staff)")
        when = datetime.fromtimestamp(e["t"], daycare_leads.ET).strftime("%a %b %d %I:%M%p")
        lines.append(f"[{when}] {who}: {e['body'][:600]}")
    return (f"Now: {datetime.fromtimestamp(now, daycare_leads.ET).strftime('%A %b %d %Y %I:%M%p ET')}\n"
            f"Contact type: {kind}\n"
            f"Parent first name: {fam.get('parent_first') or 'Unknown'}\n"
            f"Child first name: {fam.get('child_first') or 'Unknown'}\n"
            f"Center: {label or 'Unknown'} — sign as: {brand or 'Unknown (ask which center)'}\n\n"
            "Thread, oldest first (the last PARENT line is what you are answering):\n"
            + "\n".join(lines)
            + "\n\nReturn the JSON object from section 4 of the rubric. Nothing else.")


def draft_reply(contact, ev, now, key=None):
    """One Claude call -> {action, category, draft, why, unknowns, flags, model}."""
    import review_agent
    if key is None:
        import daycare_director
        key = daycare_director._solomon_key()
    if not key:
        raise RuntimeError("no Anthropic key for Solomon (SOLOMON_ANTHROPIC_API_KEY / ANTHROPIC_API_KEY)")
    raw = review_agent._claude(key, _system(), _prompt(contact, ev, now),
                               max_tokens=700, model=MODEL)
    out = _parse(raw)
    action = out.get("action") if out.get("action") in ("draft", "escalate", "no_reply") else "escalate"
    text = str(out.get("draft") or "").strip()
    if action == "draft" and not text:
        action = "escalate"
    return {"action": action, "category": str(out.get("category") or "other")[:30],
            "draft": text, "why": str(out.get("why") or "")[:300],
            "unknowns": [str(u)[:160] for u in (out.get("unknowns") or [])][:6],
            "flags": flags(text), "model": MODEL}


# ── state ─────────────────────────────────────────────────────────────────────
def _load():
    try:
        d = json.loads(STATE.read_text())
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001 — missing/corrupt = empty desk
        return {}


def _save(st):
    forge_atomic.atomic_write_json(STATE, st)


def view():
    """GET /api/daycare/replies — state only, no network."""
    st = _load()
    rows = sorted((st.get("drafts") or {}).values(), key=lambda d: -(d.get("inboundAt") or 0))
    pending = [d for d in rows if d.get("status") == "pending"]
    return {"ok": True, "model": MODEL, "pending": pending,
            "recent": [d for d in rows if d.get("status") != "pending"][:20],
            "lastRunAt": st.get("lastRunAt"), "lastSweep": st.get("lastSweep"),
            "error": st.get("error") or (None if st.get("lastRunAt") else
                     "Reply desk has not run yet — POST /api/daycare/replies/run, or it "
                     "sweeps every 5 min on the box.")}


# ── I/O ───────────────────────────────────────────────────────────────────────
def _contact(client, cid):
    data = client.get(f"/contacts/{cid}")
    c = data.get("contact") if isinstance(data, dict) else None
    return c if isinstance(c, dict) else {}


def run_once(client, now=None, drafter=None):
    """One sweep: read, gate, draft, save. Sends nothing. Returns a summary dict."""
    now = now or time.time()
    drafter = drafter or draft_reply
    if client is None or not getattr(client, "configured", False):
        err = "Daycare GHL not configured — add GHL_API_KEY + GHL_LOCATION_ID to daycare.env."
        with _LOCK:
            st = _load()
            st.update(lastRunAt=int(now * 1000), error=err)
            _save(st)
        return {"ok": False, "error": err}
    held, drafted, reads, errors, ai_err = {}, 0, 0, 0, None
    convs = client.get("/conversations/search", {
        "locationId": client.location_id, "limit": 100, "sortBy": "last_message_date"})
    with _LOCK:
        drafts = dict(_load().get("drafts") or {})
    for conv in (convs.get("conversations") if isinstance(convs, dict) else None) or []:
        cid = conv.get("contactId")
        last_at = daycare_leads._sec(conv.get("lastMessageDate")) or now
        if not cid:
            continue
        if (conv.get("lastMessageDirection") or "inbound") != "inbound":
            cur = drafts.get(cid)          # answered in GHL after we drafted -> retire it
            if cur and cur.get("status") == "pending" and last_at * 1000 > (cur.get("inboundAt") or 0):
                cur.update(status="stale", closedAt=int(now * 1000))
            continue
        if now - last_at > LOOKBACK_SEC:
            continue
        if reads >= MAX_READS or drafted >= MAX_DRAFTS:
            held["cap"] = held.get("cap", 0) + 1
            continue
        try:
            reads += 1
            msgs = daycare_leads._messages(client, conv)
            ok, why = gate({}, msgs, now)          # message rules first: zero extra GETs
            if ok:
                contact = _contact(client, cid)
                ok, why = gate(contact, msgs, now)
            if not ok:
                held[why] = held.get(why, 0) + 1
                cur = drafts.get(cid)
                if why in ("answered", "opted_out", "dnd") and cur and cur.get("status") == "pending":
                    cur.update(status="stale" if why == "answered" else why, closedAt=int(now * 1000))
                continue
            ev = _events(msgs)
            last_in = [e for e in ev if e["dir"] == "inbound"][-1]
            cur = drafts.get(cid)
            if cur and cur.get("inboundId") == last_in["id"]:
                held["already_drafted"] = held.get("already_drafted", 0) + 1
                continue
            res = drafter(contact, ev, now)
            drafted += 1
            label, brand = _center({str(t).strip().lower() for t in contact.get("tags") or []})
            fam = daycare_ghl._family_from_contact(contact)
            drafts[cid] = {
                "contactId": cid, "conversationId": conv.get("id"),
                "parentName": fam.get("parent_first") or "", "center": label, "brand": brand,
                "inboundId": last_in["id"], "inboundAt": int(last_in["t"] * 1000),
                "inboundText": last_in["body"][:300],
                "status": "pending" if res["action"] != "no_reply" else "no_reply",
                "createdAt": int(now * 1000), **res,
            }
        except Exception as e:  # noqa: BLE001 — one bad thread never kills the sweep...
            errors += 1
            print(f"[daycare_replies] {cid}: {type(e).__name__}: {str(e)[:160]}")
            if getattr(e, "code", None) == 429 or str(e).startswith("Anthropic API error"):
                ai_err = str(e)[:200] if str(e).startswith("Anthropic") else None
                break                             # ...but GHL 429 / Claude billing is account-wide
    cutoff = (now - KEEP_SEC) * 1000
    drafts = {k: v for k, v in drafts.items()
              if v.get("status") == "pending" or (v.get("createdAt") or 0) >= cutoff}
    summary = {"drafted": drafted, "read": reads, "held": held, "errors": errors}
    with _LOCK:
        st = _load()
        # merge: an approve/dismiss that landed mid-sweep wins over this sweep's copy
        live = st.get("drafts") or {}
        for k, v in live.items():
            if v.get("status") != "pending" and k in drafts and drafts[k].get("inboundId") == v.get("inboundId"):
                drafts[k] = v
        st.update(drafts=drafts, lastRunAt=int(now * 1000), lastSweep=summary,
                  error=ai_err or (f"{errors} thread(s) failed" if errors else None))
        _save(st)
    print(f"[daycare_replies] sweep: {drafted} drafted, {reads} read, held={held}")
    return {"ok": True, **summary, "error": ai_err}


def _close(cid, status, **extra):
    with _LOCK:
        st = _load()
        d = (st.get("drafts") or {}).get(cid)
        if d:
            d.update(status=status, closedAt=int(time.time() * 1000), **extra)
            _save(st)
    return d


def dismiss(contact_id):
    """Owner says 'not sending this' — internal + reversible (next inbound redrafts)."""
    cid = str(contact_id or "").strip()
    d = (_load().get("drafts") or {}).get(cid)
    if not d or d.get("status") != "pending":
        return {"ok": False, "error": "no pending draft for that contact"}
    _close(cid, "dismissed")
    return {"ok": True, "contactId": cid, "status": "dismissed"}


def approve(client, contact_id, text=None, now=None):
    """The owner's tap: re-check the LIVE thread, then send exactly one SMS."""
    now = now or time.time()
    cid = str(contact_id or "").strip()
    d = (_load().get("drafts") or {}).get(cid)
    if not d or d.get("status") != "pending":
        return {"ok": False, "error": "no pending draft for that contact"}
    body = (text if text is not None else d.get("draft") or "").strip()
    if not body:
        return {"ok": False, "error": "empty message"}
    if not daycare_leads.in_hours(now):
        return {"ok": False, "error": "outside 8am–9pm ET texting window — approve after 8am"}
    conv = daycare_leads._conversation(client, cid)
    ev = _events(daycare_leads._messages(client, conv))
    if any(e["dir"] == "outbound" and e["t"] * 1000 > (d.get("inboundAt") or 0) for e in ev):
        _close(cid, "stale")
        return {"ok": False, "error": "someone already replied in GHL — draft retired, not sent"}
    if any(e["dir"] == "inbound" and seller_classify.is_opt_out(e["body"]) for e in ev):
        _close(cid, "opted_out")
        return {"ok": False, "error": "parent opted out — not sent"}
    res = daycare_ghl.send_sms(client, contact_id=cid, message=body)
    try:
        import action_log
        action_log.record("solomon", "daycare_reply_send", business="daycare", trigger="owner_tap",
                          ref=cid, result="sent" if res.get("ok") else "failed",
                          ok=bool(res.get("ok")), approval_required=True)
    except Exception:  # noqa: BLE001 — the log never blocks a send
        pass
    if res.get("ok"):
        _close(cid, "sent", sentText=body, edited=body != d.get("draft"))
    return res


def run_forever(client):
    """Background loop (thread `daycare_replies` — its own Costs-tab bucket)."""
    last = (_load().get("lastRunAt") or 0) / 1000
    time.sleep(max(0, min(INTERVAL, last + INTERVAL - time.time())))
    while True:
        err = None
        try:
            if not forge_ops.paused():
                err = run_once(client).get("error")
        except Exception as e:  # noqa: BLE001
            err = type(e).__name__
        forge_heartbeat.beat("daycare_replies", INTERVAL, "Daycare Reply Desk", error=err)
        time.sleep(INTERVAL)
