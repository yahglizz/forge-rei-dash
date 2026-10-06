"""daycare_replies.py — Solomon's family-comms lane: drafts replies to parent texts.

Why: parents text the daycare GHL number around the clock and the Lead Desk can only say
"someone needs to answer this". This loop writes the answer — in the center's real voice,
grounded in the verified fact sheet — so the owner's job at 6am is one tap, not a blank box.

Every 60 s on the box (FORGE_MARCUS gate lives in connector.main, knob FORGE_DAYCARE_REPLIES):
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
  4. Drafts land in marcus_state/daycare_replies.json. By default nothing is sent.
  5. OPT-IN (FORGE_DAYCARE_REPLY_AUTO=1, default OFF): auto_send() texts only a clean,
     flag-free answer to an enrollment LEAD in the safe categories — capped, receipted on
     Telegram, action-logged, stopped by forge_ops clock-out or any staff reply in GHL.

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
import daycare_family_confirm
import daycare_leads
import forge_atomic
import forge_heartbeat
import forge_ops
import review_agent
import seller_classify

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "daycare_replies.json"
_LOCK = threading.Lock()

# Speed-to-lead target: a parent who texts gets a real answer inside ~5 min — never instant
# (a bot tell), never the old 5-10 min. Sweep every 60 s; a fresh inbound waits GRACE_SEC so a
# GHL workflow's stop-on-response or a person typing live is never raced.
INTERVAL = int(os.environ.get("FORGE_DAYCARE_REPLIES_INTERVAL", "60"))
MODEL = os.environ.get("FORGE_DAYCARE_REPLY_MODEL", review_agent.SMART_MODEL)
GRACE_SEC = int(os.environ.get("FORGE_DAYCARE_REPLY_GRACE_SEC", "90"))
MAX_DRAFTS = int(os.environ.get("FORGE_DAYCARE_REPLY_MAX", "8"))   # Claude calls per sweep
MAX_READS = 40                         # thread GETs per sweep
STL_WAIT_SEC = 6 * 60                  # speed-to-lead tag on, nothing sent yet: workflow pending
LOOKBACK_SEC = 7 * 86400               # older unanswered texts are the Lead Desk's problem
KEEP_SEC = 30 * 86400                  # prune closed drafts after this

# AUTO-SEND (operator opt-in, default OFF — CLAUDE.md rule 2 exception). When on, ONLY a
# plain enrollment-lead question/answer that passes every check below goes out by itself;
# everything else stays a draft for the owner's tap.
AUTO = os.environ.get("FORGE_DAYCARE_REPLY_AUTO", "0") == "1"
AUTO_CAP = int(os.environ.get("FORGE_DAYCARE_AUTO_CAP", "30"))            # auto sends per ET day
AUTO_PER_CONTACT = 3                                                      # per contact per 24 h
AUTO_MAX_AGE_SEC = 12 * 3600                                              # don't text a stale draft
AUTO_SAFE_CATEGORIES = {"tour", "subsidy", "availability", "enroll", "pricing"}

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
    # A "YES" to the Family Contact Form confirmation text needs no human answer —
    # daycare_family_confirm.py tags the family confirmed. A hedged reply still drafts.
    ftags = {str(t).strip().lower() for t in (contact.get("tags") or [])}
    if ftags & {"family-confirm-pending", "family-confirmed"} \
            and daycare_family_confirm.classify(last["body"]) == "yes":
        return False, "family_confirm"
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


def notify_owner(d):
    """Telegram the owner when Solomon needs a human: a question he can't answer from the
    verified fact sheet (`unknowns`) or an escalation topic (safety/custody/medical/billing
    dispute/complaint). Deduped per inbound message. Never raises, never sends to the parent."""
    try:
        if d.get("action") == "no_reply":
            return False
        unknowns = [u for u in (d.get("unknowns") or []) if u]
        if d.get("action") != "escalate" and not unknowns:
            return False
        import html
        import telegram_io
        e = lambda x: html.escape(str(x or ""))          # Telegram message is HTML
        head = "🚨 Solomon · needs you NOW" if d.get("action") == "escalate" else "🙋 Solomon · a parent asked something he doesn't know"
        who = d.get("parentName") or "A parent"
        parts = [f"{head}\n{e(who)}" + (f" · {e(d['center'])}" if d.get("center") else "") + f" texted:\n“{e((d.get('inboundText') or '')[:300])}”"]
        if unknowns:
            parts.append("He didn't state: " + e("; ".join(u[:120] for u in unknowns[:4])))
        if d.get("draft"):
            parts.append(("Holding line " + ("auto-sent" if d.get("autoEligible") and AUTO else "drafted")
                          + f": “{e(d['draft'][:240])}”"))
        parts.append("Step in: Messages tab (or reply in GHL — he stops as soon as you do).")
        telegram_io.send_biz("daycare", "\n".join(parts),
                             dedupe_key=f"dcreply:{d.get('contactId')}:{d.get('inboundId')}")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[daycare_replies] notify_owner: {type(e).__name__}: {str(e)[:120]}")
        return False


def auto_eligible(res, kind):
    """Pure: may this draft go out without the owner's tap? Only a clean, plain answer to
    an enrollment LEAD — never an escalation, an enrolled family, a flagged draft
    (phone/$/emoji/long), or a category outside the safe set (no safety/billing/custody)."""
    return bool(kind == "lead" and res.get("action") == "draft" and (res.get("draft") or "").strip()
                and res.get("category") in AUTO_SAFE_CATEGORIES and not res.get("flags"))


def _et_day(ts):
    return datetime.fromtimestamp(ts, daycare_leads.ET).strftime("%Y-%m-%d")


def auto_send(client, now=None):
    """Send pending auto-eligible drafts through approve() — the same live re-check,
    opt-out, DND-window gates as the owner's tap. Returns {sent, skipped}. Every send is
    capped, per-contact limited, action-logged and Telegram-receipted; forge_ops.paused()
    or FORGE_DAYCARE_REPLY_AUTO=0 stops it instantly."""
    now = now or time.time()
    if not AUTO or forge_ops.paused() or not daycare_leads.in_hours(now):
        return {"sent": 0, "skipped": "off_or_outside_hours"}
    st = _load()
    log = [t for t in (st.get("autoLog") or []) if now - t["t"] < 86400]
    today = _et_day(now)
    sent = 0
    for cid, d in list((st.get("drafts") or {}).items()):
        if d.get("status") != "pending" or not d.get("autoEligible"):
            continue
        if now * 1000 - (d.get("createdAt") or 0) > AUTO_MAX_AGE_SEC * 1000:
            continue                                         # stale — owner decides
        if sum(1 for t in log if _et_day(t["t"]) == today) >= AUTO_CAP:
            break
        if sum(1 for t in log if t["cid"] == cid) >= AUTO_PER_CONTACT:
            continue
        ct = _contact(client, cid)
        if ct.get("dnd"):
            continue
        res = approve(client, cid, now=now, auto=True)
        if res.get("ok"):
            sent += 1
            log.append({"t": now, "cid": cid})
            try:
                import telegram_io
                who = d.get("parentName") or "a parent"
                telegram_io.send_biz("daycare", f"🤖 Solomon texted {who} ({d.get('center') or 'center ?'}) "
                                     f"{int(now - (d.get('inboundAt') or 0) / 1000)}s after their message:\n"
                                     f"“{(d.get('draft') or '')[:300]}”\nReply in GHL to take over — "
                                     f"auto-send respects it.")
            except Exception:  # noqa: BLE001 — a receipt failure never blocks
                pass
    with _LOCK:
        st = _load()
        st["autoLog"] = log
        _save(st)
    return {"sent": sent}


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


def _form_facts(contact, now):
    """What the enrollment form already told us — so the desk never re-asks it."""
    cf = daycare_ghl._cf_map(contact or {})
    out = []
    dob = str(cf.get(daycare_ghl.CF_CHILD_DOB) or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            b = datetime.strptime(dob[:10], fmt).date()
            t = datetime.fromtimestamp(now, daycare_leads.ET).date()
            m = (t.year - b.year) * 12 + (t.month - b.month) - (t.day < b.day)
            if 0 <= m < 240:
                out.append(f"Child age: {m} months" if m < 36 else f"Child age: {m // 12} years")
            break
        except ValueError:
            continue
    try:
        import daycare_starts
        f = daycare_starts.form_date(contact or {}, now)
        if f:
            out.append(f"Desired start date (form): {f['date']}")
    except Exception:  # noqa: BLE001
        pass
    return out


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
            f"Center: {label or 'Unknown'} — sign as: {brand or 'Unknown (ask which center)'}\n"
            + ("Already known from the enrollment form (NEVER ask these again): "
               + "; ".join(_form_facts(contact, now)) + "\n" if _form_facts(contact, now) else "")
            + f"Texts we have already sent this family: {sum(1 for e in ev if e['dir'] == 'outbound')}\n\n"
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


def view(now=None):
    """GET /api/daycare/replies — state only, no network."""
    st = _load()
    rows = sorted((st.get("drafts") or {}).values(), key=lambda d: -(d.get("inboundAt") or 0))
    pending = [d for d in rows if d.get("status") == "pending"]
    today = _et_day(now or time.time())
    return {"ok": True, "model": MODEL, "pending": pending,
            "auto": {"on": AUTO, "cap": AUTO_CAP,
                     "sentToday": sum(1 for t in (st.get("autoLog") or []) if _et_day(t["t"]) == today)},
            "recent": [d for d in rows if d.get("status") != "pending"][:20],
            "lastRunAt": st.get("lastRunAt"), "lastSweep": st.get("lastSweep"),
            "error": st.get("error") or (None if st.get("lastRunAt") else
                     "Reply desk has not run yet — POST /api/daycare/replies/run, or it "
                     "sweeps every minute on the box.")}


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
    if drafter is draft_reply and review_agent.ai_blocked():
        # AI circuit open (credits/auth out): skip the whole sweep — no GHL reads, no doomed
        # Sonnet calls. Not a lane failure (heartbeat stays green); the state says why. A probe
        # slot reopens every FORGE_AI_PROBE_SEC and the next sweep then tries for real.
        msg = ("Drafting paused — Anthropic credits/key out (AI circuit open). Resumes on its "
               "own once credits are back; no parent texts are lost.")
        with _LOCK:
            st = _load()
            st.update(lastRunAt=int(now * 1000), error=msg,
                      lastSweep={"drafted": 0, "read": 0, "held": {"ai_down": 1}, "errors": 0})
            _save(st)
        return {"ok": True, "skipped": "ai_down", "error": None}
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
        done = drafts.get(cid)
        if done and not done.get("revive") and (done.get("inboundAt") or 0) >= int(last_at * 1000) - 2000:
            held["already_drafted"] = held.get("already_drafted", 0) + 1
            continue                          # same inbound already drafted/closed — no GETs
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
            if cur and not cur.get("revive") and cur.get("inboundId") == last_in["id"]:
                held["already_drafted"] = held.get("already_drafted", 0) + 1
                continue
            res = drafter(contact, ev, now)
            drafted += 1
            label, brand = _center({str(t).strip().lower() for t in contact.get("tags") or []})
            fam = daycare_ghl._family_from_contact(contact)
            kind = ("family" if {str(t).strip().lower() for t in contact.get("tags") or []}
                    & daycare_leads.FAMILY_TAGS else "lead")
            drafts[cid] = {
                "kind": kind, "autoEligible": auto_eligible(res, kind),
                "contactId": cid, "conversationId": conv.get("id"),
                "parentName": fam.get("parent_first") or "", "center": label, "brand": brand,
                "inboundId": last_in["id"], "inboundAt": int(last_in["t"] * 1000),
                "inboundText": last_in["body"][:300],
                "status": "pending" if res["action"] != "no_reply" else "no_reply",
                "createdAt": int(now * 1000), **res,
            }
            notify_owner(drafts[cid])
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
    try:
        summary["auto"] = auto_send(client, now)
    except Exception as e:  # noqa: BLE001 — auto-send failing must never fail the sweep
        print(f"[daycare_replies] auto_send: {type(e).__name__}: {str(e)[:160]}")
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


def approve(client, contact_id, text=None, now=None, auto=False):
    """The owner's tap (or, with auto=True, auto_send()): re-check the LIVE thread, then
    send exactly one SMS."""
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
        action_log.record("solomon", "daycare_reply_send", business="daycare",
                          trigger="auto_safe" if auto else "owner_tap",
                          ref=cid, result="sent" if res.get("ok") else "failed",
                          ok=bool(res.get("ok")), approval_required=not auto)
    except Exception:  # noqa: BLE001 — the log never blocks a send
        pass
    if res.get("ok"):
        _close(cid, "sent", sentText=body, edited=body != d.get("draft"), auto=bool(auto))
    return res


# ── Messages tab (owner console): live GHL inbox, one thread, owner-typed reply ──
MANUAL_MAX_CHARS = 640                 # 4 SMS segments


def _not_configured():
    return {"ok": False, "connected": False,
            "error": "Daycare GHL not configured — add GHL_API_KEY + GHL_LOCATION_ID to daycare.env."}


def inbox(client, limit=60):
    """GET /api/daycare/ghl/conversations — newest daycare threads (one GHL GET) with
    the Reply Desk's pending-draft flag. Read-only."""
    if client is None or not getattr(client, "configured", False):
        return _not_configured()
    try:
        limit = max(1, min(int(limit), 100))
    except (TypeError, ValueError):
        limit = 60
    data = client.get("/conversations/search", {
        "locationId": client.location_id, "limit": limit, "sortBy": "last_message_date"})
    drafts = {k for k, v in (_load().get("drafts") or {}).items() if v.get("status") == "pending"}
    rows = []
    for c in (data.get("conversations") if isinstance(data, dict) else None) or []:
        cid = c.get("contactId")
        if not cid:
            continue
        label, _ = _center({str(t).strip().lower() for t in c.get("tags") or []})
        at = daycare_leads._sec(c.get("lastMessageDate"))
        rows.append({
            "contactId": cid, "conversationId": c.get("id"),
            "name": c.get("fullName") or c.get("contactName") or c.get("phone") or "Unknown",
            "phone": c.get("phone") or "", "center": label,
            "lastMessage": str(c.get("lastMessageBody") or "")[:160],
            "lastAt": int(at * 1000) if at else None,
            "direction": c.get("lastMessageDirection") or "",
            "type": str(c.get("lastMessageType") or c.get("type") or "").replace("TYPE_", "").lower(),
            "unread": int(c.get("unreadCount") or 0),
            "draft": cid in drafts,
        })
    return {"ok": True, "connected": True, "conversations": rows,
            "pendingDrafts": len(drafts), "inHours": daycare_leads.in_hours(time.time())}


def thread(client, contact_id, now=None):
    """GET /api/daycare/ghl/thread — one family's messages (oldest first), who they are,
    whether a reply can go out right now, and the pending draft if any. Read-only."""
    now = now or time.time()
    cid = str(contact_id or "").strip()
    if not cid:
        return {"ok": False, "error": "contact_id required"}
    if client is None or not getattr(client, "configured", False):
        return _not_configured()
    conv = daycare_leads._conversation(client, cid)
    msgs = []
    for m in daycare_leads._messages(client, conv):
        t = daycare_leads._sec(m.get("dateAdded") or m.get("date"))
        d = m.get("direction")
        mtype = str(m.get("messageType") or m.get("type") or "").upper()
        if t is None or d not in ("inbound", "outbound") or "ACTIVITY" in mtype:
            continue
        body = str(m.get("body") or "")
        msgs.append({"id": str(m.get("id") or ""), "at": int(t * 1000), "dir": d, "body": body,
                     "kind": mtype.replace("TYPE_", "").lower() or "sms",
                     "auto": d == "outbound" and (
                         str(m.get("source") or "").lower() in daycare_leads.AUTO_SOURCES
                         or any(s in body.lower() for s in OUR_SIGNATURES))})
    msgs.sort(key=lambda e: e["at"])
    contact = _contact(client, cid)
    fam = daycare_ghl._family_from_contact(contact) if contact else {}
    label, brand = _center({str(t).strip().lower() for t in contact.get("tags") or []})
    opted = any(e["dir"] == "inbound" and seller_classify.is_opt_out(e["body"]) for e in msgs)
    block = ("parent opted out" if opted
             else "on Do Not Disturb in GHL" if contact.get("dnd")
             else None if daycare_leads.in_hours(now)
             else "outside the 8am–9pm ET texting window")
    d = (_load().get("drafts") or {}).get(cid)
    name = " ".join(x for x in (contact.get("firstName"), contact.get("lastName")) if x) \
        or contact.get("contactName") or contact.get("phone") or "Unknown"
    return {"ok": True, "contactId": cid, "conversationId": conv.get("id"),
            "name": name, "parentName": fam.get("parent_name") or fam.get("parent_first") or "",
            "phone": contact.get("phone") or "", "center": label, "brand": brand,
            "tags": sorted(str(t) for t in contact.get("tags") or [])[:20],
            "messages": msgs[-80:], "canSend": block is None, "blockReason": block,
            "draft": d if d and d.get("status") == "pending" else None}


def send_block(client, contact_id, now=None):
    """Why a text to this contact would be refused right now (window, opt-out, DND), or None.
    Side-effect free: the login queue asks this BEFORE minting a PIN it couldn't deliver."""
    now = now or time.time()
    cid = str(contact_id or "").strip()
    if client is None or not getattr(client, "configured", False):
        return "Daycare GHL not configured"
    if not daycare_leads.in_hours(now):
        return "outside 8am–9pm ET texting window — send after 8am"
    ev = _events(daycare_leads._messages(client, daycare_leads._conversation(client, cid)))
    if any(e["dir"] == "inbound" and seller_classify.is_opt_out(e["body"]) for e in ev):
        return "parent opted out — not sent"
    if _contact(client, cid).get("dnd"):
        return "contact is on Do Not Disturb in GHL — not sent"
    return None


def send_manual(client, contact_id, text, now=None, close_draft=True):
    """POST /api/daycare/ghl/reply — the owner typed this and tapped send; that tap IS the
    approval (rule 2). Same gates as approve(): texting window, opt-out, DND.
    close_draft=False (the Create-login text, which carries a PIN): leaves any pending
    Reply-Desk draft untouched and never writes the body to disk."""
    now = now or time.time()
    cid = str(contact_id or "").strip()
    body = (text or "").strip()
    if not cid or not body:
        return {"ok": False, "error": "contact and message are required"}
    if len(body) > MANUAL_MAX_CHARS:
        return {"ok": False, "error": f"message too long — keep it under {MANUAL_MAX_CHARS} characters"}
    if client is None or not getattr(client, "configured", False):
        return _not_configured()
    block = send_block(client, cid, now)
    if block:
        return {"ok": False, "error": block}
    res = daycare_ghl.send_sms(client, contact_id=cid, message=body)
    try:
        import action_log
        action_log.record("operator", "daycare_manual_send" if close_draft else "daycare_login_text",
                          business="daycare", trigger="owner_tap",
                          ref=cid, result="sent" if res.get("ok") else "failed",
                          ok=bool(res.get("ok")), approval_required=True)
    except Exception:  # noqa: BLE001 — the log never blocks a send
        pass
    d = (_load().get("drafts") or {}).get(cid) if close_draft else None
    if res.get("ok") and d and d.get("status") == "pending":
        _close(cid, "sent", sentText=body, edited=True, manual=True)
    return res


def run_forever(client):
    """Background loop (thread `daycare_replies` — Solomon's Replies lane; bills to Solomon)."""
    last = (_load().get("lastRunAt") or 0) / 1000
    time.sleep(max(0, min(INTERVAL, last + INTERVAL - time.time())))
    while True:
        err = None
        try:
            if not forge_ops.paused():
                err = run_once(client).get("error")
                try:                      # Solomon · Revive shares this thread: no drafts-file race
                    import daycare_revive
                    daycare_revive.run_once(client)
                except Exception as e:  # noqa: BLE001 — revive never fails the Replies lane
                    print(f"[daycare_revive] {type(e).__name__}: {str(e)[:160]}")
        except Exception as e:  # noqa: BLE001
            err = type(e).__name__
        forge_heartbeat.beat("daycare_replies", INTERVAL, "Solomon · Replies", error=err)
        time.sleep(INTERVAL)
