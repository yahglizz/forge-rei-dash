"""daycare_revive.py — Solomon · Revive: win back paid-for leads that went quiet.

Why: Solomon · Replies only looks back 7 days (daycare_replies.LOOKBACK_SEC), and the Lead
Desk only says "needs a human". Leads from paid Meta ads that stalled 2-5 weeks ago had NOBODY
drafting a follow-up — the owner saw a stale "call overdue" row and nothing to tap. This lane
drafts the check-in text so reviving a cold lead is one tap, not a blank box.

How: runs right after each Replies sweep (same thread, so it never races the shared drafts
file). Picks leads from the Lead Desk state — contacted, not enrolled/lost/opted-out, quiet
>= 7 days (or, while the AI circuit is open, a parent text left unanswered at any age) — max
5 pending, 3 new per sweep, 2 attempts per contact ever, 14 days apart. Drafts land in the
SAME drafts store as Replies (category "revive"), so the Messages tab, Owner Actions and the
approve() gates (live thread re-check, opt-out, DND, 8am-9pm ET) all apply unchanged.

Draft: one Claude call in the family-comms voice when the AI is up; a plain voice-matched
template when it is down — a revival text must never wait on credits. Never auto-sent
(autoEligible is always False), never claims a seat, a rate, a date or an offer: the creed.
Kill: FORGE_DAYCARE_REVIVE=0 or forge_ops clock-out. Stdlib only.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
import time
from pathlib import Path

import daycare_ghl
import daycare_leads
import daycare_replies
import forge_atomic
import forge_ops
import review_agent
import seller_classify

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "daycare_revive.json"
_LOCK = threading.Lock()

ENABLED = os.environ.get("FORGE_DAYCARE_REVIVE", "1") != "0"
MIN_QUIET_DAYS = 7          # younger than this is the Replies lane's job
MAX_AGE_DAYS = 90           # older than this left the Lead Desk anyway
GAP_DAYS = 14               # between attempts on one contact
MAX_ATTEMPTS = 2            # a third nudge is pestering, not reviving
MAX_PENDING = 5             # owner's queue never floods
PER_SWEEP = 3               # drafts (and GET bursts) per sweep
STOP_LINE = "Reply STOP to opt out."

_TASK = (
    "TASK — REVIVE. This family has gone quiet. Write ONE short text that re-opens the "
    "conversation. {why}\n"
    "Rules: own it FIRST, plainly, if their last text went unanswered. One question only: "
    "are they still looking for childcare. Use 'first come, first served' / 'top of the "
    "list' as the only urgency. NEVER state or imply an open seat, a start date, a rate, a "
    "deadline or an offer the fact sheet / daycare-context.md does not give as live with its "
    "expiry. No emoji, no phone number. End with exactly: " + STOP_LINE + "\n"
    'Return JSON only: {{"action":"draft","category":"revive","draft":"...","why":"...","unknowns":[]}}')


def _load():
    try:
        d = json.loads(STATE.read_text())
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001 — missing/corrupt = fresh lane
        return {}


def _save(st):
    forge_atomic.atomic_write_json(STATE, st)


# ── pure: who gets a revival draft ────────────────────────────────────────────
def _touch(lead):
    return max(lead.get("lastInboundAt") or 0, lead.get("lastOutboundAt") or 0) / 1000


def _waiting(lead):
    """The parent texted last and nobody answered."""
    return bool(lead.get("lastInboundAt")) and lead["lastInboundAt"] > (lead.get("lastOutboundAt") or 0)


def pick(leads, drafts, st, now, ai_down=False):
    """Pure: Lead Desk rows (apply_stages output) -> candidates, best first. Unanswered
    parent texts lead, then the warmest (most recently touched)."""
    contacts = st.get("contacts") or {}
    out = []
    for lead in leads or []:
        cid = lead.get("contactId")
        if not cid or lead.get("stage") in daycare_leads.CLOSED or lead.get("optedOut"):
            continue
        touch = _touch(lead)
        if not touch:
            continue                                   # never texted either way: not a revival
        days = (now - touch) / 86400
        waiting = _waiting(lead)
        if days > MAX_AGE_DAYS or (days < MIN_QUIET_DAYS and not (ai_down and waiting)):
            continue
        seen = contacts.get(cid) or {}
        if (seen.get("attempts") or 0) >= MAX_ATTEMPTS \
                or now - (seen.get("lastAt") or 0) / 1000 < GAP_DAYS * 86400:
            continue
        cur = drafts.get(cid) or {}
        if cur.get("status") == "pending" \
                or now - (cur.get("closedAt") or 0) / 1000 < GAP_DAYS * 86400:
            continue                                   # a draft is open, or the owner just handled it
        out.append(dict(lead, _touch=touch, _waiting=waiting, _days=int(days)))
    out.sort(key=lambda l: (not l["_waiting"], -l["_touch"]))
    return out


# ── drafting ──────────────────────────────────────────────────────────────────
def template(contact, ev, now):
    """Voice-matched check-in with zero Claude (daycare-voice.md register 2, own-the-miss
    first when the parent's text sat). Facts: none beyond the center name — nothing to invent."""
    fam = daycare_ghl._family_from_contact(contact or {})
    tags = {str(t).strip().lower() for t in (contact or {}).get("tags") or []}
    _label, brand = daycare_replies._center(tags)
    first, child = (fam.get("parent_first") or "").strip(), (fam.get("child_first") or "").strip()
    hi = f"hey {first}" if len(first) >= 2 else "hey"      # no time-of-day: a draft may sit overnight
    for_kid = f" for {child}" if len(child) >= 2 and child.lower() != first.lower() else ""
    who = f"this is management over at {brand or 'A Touch of Blessings'}"
    keep = "we do first come first served so i want to make sure we keep you at the top of the list, thank you"
    if ev and ev[-1]["dir"] == "inbound":
        body = (f"{hi} {who}, im sorry for the slow reply, i know you reached out and we dropped "
                f"the ball, are you still looking for childcare{for_kid}? {keep}")
    else:
        body = (f"{hi} {who}, just checking back in to see if youre still looking for "
                f"childcare{for_kid}, {keep}")
    return {"action": "draft", "category": "revive", "draft": f"{body}. {STOP_LINE}",
            "why": "template — AI unavailable", "unknowns": [], "model": "template"}


def draft_revive(contact, ev, now, key=None):
    """One Claude call (family-comms prompt + REVIVE task) -> same dict shape as template()."""
    if key is None:
        import daycare_director
        key = daycare_director._solomon_key()
    if not key:
        raise RuntimeError("no Anthropic key for Solomon")
    base = daycare_replies._prompt(contact, ev, now).split("\n\nReturn the JSON")[0]
    waiting = bool(ev and ev[-1]["dir"] == "inbound")
    why = ("The parent's last text was never answered." if waiting
           else "We texted last and they have not replied.")
    out = daycare_replies._parse(review_agent._claude(
        key, daycare_replies._system(), base + "\n\n" + _TASK.format(why=why),
        max_tokens=500, model=daycare_replies.MODEL))
    text = str(out.get("draft") or "").strip()
    if not text:
        raise ValueError("empty revive draft")
    if STOP_LINE.lower() not in text.lower():
        text = f"{text} {STOP_LINE}"
    return {"action": "draft", "category": "revive", "draft": text,
            "why": str(out.get("why") or "")[:300],
            "unknowns": [str(u)[:160] for u in (out.get("unknowns") or [])][:6],
            "model": daycare_replies.MODEL}


def _build(contact, ev, now, ai_down):
    """Claude when the AI is up, template when it is down or the call fails — never blocks."""
    if not ai_down:
        try:
            return draft_revive(contact, ev, now)
        except Exception as e:  # noqa: BLE001 — a failed call degrades to the template
            print(f"[daycare_revive] claude failed ({type(e).__name__}); using template")
    return template(contact, ev, now)


# ── I/O ───────────────────────────────────────────────────────────────────────
def _live(client, cid, now):
    """Fresh thread + contact for one candidate, or None when it is no longer a revival."""
    conv = daycare_leads._conversation(client, cid)
    ev = daycare_replies._events(daycare_leads._messages(client, conv))
    if not ev or any(e["dir"] == "inbound" and seller_classify.is_opt_out(e["body"]) for e in ev):
        return None
    contact = daycare_replies._contact(client, cid)
    if contact.get("dnd"):
        return None
    return conv, ev, contact


def run_once(client, now=None, drafter=None):
    """One pass: pick, re-check live, draft into the shared drafts store. Sends nothing."""
    now = now or time.time()
    if not ENABLED or forge_ops.paused() or client is None or not getattr(client, "configured", False):
        return {"ok": True, "skipped": "off"}
    drafts = (daycare_replies._load().get("drafts") or {})
    room = MAX_PENDING - sum(1 for d in drafts.values() if d.get("revive") and d.get("status") == "pending")
    if room <= 0:
        return {"ok": True, "drafted": 0, "skipped": "queue_full"}
    ai_down = review_agent.ai_blocked()
    st = _load()
    cands = pick(daycare_leads.apply_stages(daycare_leads._load().get("leads")), drafts, st, now, ai_down)
    made, names = 0, []
    for lead in cands:
        if made >= min(room, PER_SWEEP):
            break
        cid = lead["contactId"]
        try:
            got = _live(client, cid, now)
            if not got:
                continue
            conv, ev, contact = got
            if not lead["_waiting"] and now - ev[-1]["t"] < MIN_QUIET_DAYS * 86400:
                continue                                # staff/parent texted since the sweep
            res = drafter(contact, ev, now) if drafter else _build(contact, ev, now, ai_down)
            fam = daycare_ghl._family_from_contact(contact)
            label, brand = daycare_replies._center({str(t).strip().lower() for t in contact.get("tags") or []})
            last_in = next((e for e in reversed(ev) if e["dir"] == "inbound"), None)
            waiting = ev[-1]["dir"] == "inbound"
            entry = {"kind": "lead", "revive": True, "autoEligible": False, "contactId": cid,
                     "conversationId": conv.get("id"), "parentName": fam.get("parent_first") or "",
                     "center": label, "brand": brand, "quietDays": lead["_days"],
                     "inboundId": last_in["id"] if last_in else f"revive:{cid}",
                     "inboundAt": int((last_in["t"] if waiting else now) * 1000),
                     "inboundText": (last_in["body"][:300] if waiting else
                                     f"(no reply from them in {lead['_days']} days)"),
                     "status": "pending", "createdAt": int(now * 1000),
                     "flags": daycare_replies.flags(res["draft"]), **res}
            with daycare_replies._LOCK:
                rs = daycare_replies._load()
                if (rs.get("drafts") or {}).get(cid, {}).get("status") == "pending":
                    continue                            # a real reply draft landed first
                rs.setdefault("drafts", {})[cid] = entry
                daycare_replies._save(rs)
            with _LOCK:
                st = _load()
                c = st.setdefault("contacts", {}).setdefault(cid, {"attempts": 0})
                c.update(attempts=c["attempts"] + 1, lastAt=int(now * 1000))
                _save(st)
            made += 1
            names.append(daycare_leads.display_name(lead, first_only=True))
        except Exception as e:  # noqa: BLE001 — one bad thread never kills the pass
            print(f"[daycare_revive] {cid}: {type(e).__name__}: {str(e)[:160]}")
            if getattr(e, "code", None) == 429:
                break
    if made:
        _ping(names, now)
    with _LOCK:
        st = _load()
        st.update(lastRunAt=int(now * 1000), lastSweep={"candidates": len(cands), "drafted": made})
        _save(st)
    return {"ok": True, "drafted": made, "candidates": len(cands)}


def _ping(names, now):
    """One Telegram line per batch so the owner knows taps are waiting. Never texts a family."""
    try:
        import telegram_io
        day = datetime.fromtimestamp(now, daycare_leads.ET).strftime("%Y-%m-%d")
        shown = ", ".join(names[:4]) + (f" +{len(names) - 4}" if len(names) > 4 else "")
        telegram_io.send_biz("daycare", f"🔁 Solomon · Revive queued {len(names)} check-in text(s) "
                             f"for quiet leads: {shown}. Messages tab → one tap each (8am–9pm ET).",
                             dedupe_key=f"dcrevive:{day}:{'|'.join(names)}")
    except Exception as e:  # noqa: BLE001
        print(f"[daycare_revive] ping: {type(e).__name__}: {str(e)[:120]}")
