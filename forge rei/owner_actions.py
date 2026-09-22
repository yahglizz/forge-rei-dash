"""owner_actions.py — ONE read-only list answering "what requires my attention right now?"

Spec §15 OWNER ACTIONS. The owner's day = CALL / CLOSE / APPROVE / REVIEW. Every existing
queue across Agency, Wholesale, Daycare + the system itself is folded into one sorted
list: URGENT → REVENUE → CUSTOMER → NORMAL, oldest first inside a tier.

Hard rules (match mission_control.py):
  * READ-ONLY. Sends nothing, writes no CRM record, makes ZERO Claude calls. The only
    state it keeps is an in-process cache for the daycare GHL read.
  * NEVER 500s. Every source is wrapped; a failing source yields at most ONE FIX item
    (`fix:<source>`) and the rest of the list still comes back.
  * Stable ids (`<source>:<record id>`) so the list dedupes across refreshes.
  * Archived businesses are skipped (business_scope.is_archived — WP-B; absent = nothing
    archived).

Item shape:
  {id, kind: CALL|CALLBACK|APPROVE|REVIEW|FIX, business: agency|wholesale|daycare|system,
   priority: urgent|revenue|customer|normal, title, why, ageSec, link: {ws,page}|{view}, source}

`merge_and_sort(items)` is the pure core (testable, no I/O); `build(ctx)` is the I/O shell.
"""
import time
from datetime import datetime

PRIORITY_RANK = {"urgent": 0, "revenue": 1, "customer": 2, "normal": 3}
KINDS = ("CALL", "CALLBACK", "APPROVE", "REVIEW", "FIX")
DAYCARE_TTL_SEC = 600          # pending_families is a paged GHL read — cache >= 10 min
DAYCARE_FAILS_BEFORE_FIX = 3   # fail soft; only a repeated failure becomes a FIX item
CALL_FRESH_DAYS = 5            # a screened-interested seller stays a call this long (do_today)


# ---------------------------------------------------------------------------
# Pure core
# ---------------------------------------------------------------------------

def merge_and_sort(items):
    """Dedupe by id (first wins), then URGENT → REVENUE → CUSTOMER → NORMAL, oldest first.
    Items with an unknown age sort after known ages inside their tier."""
    seen, out = set(), []
    for it in items or []:
        iid = it.get("id")
        if not iid or iid in seen:
            continue
        seen.add(iid)
        out.append(it)

    def key(it):
        age = it.get("ageSec")
        return (PRIORITY_RANK.get(it.get("priority"), 9),
                -age if isinstance(age, (int, float)) else 1)
    out.sort(key=key)
    return out


def _age(created_ms, now_ms):
    try:
        created_ms = int(created_ms or 0)
    except (TypeError, ValueError):
        return None
    if created_ms <= 0:
        return None
    return max(0, (now_ms - created_ms) // 1000)


def _iso_ms(s):
    """ISO-8601 (GHL dateAdded) → epoch ms, or None."""
    try:
        return int(datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        return None


def _item(iid, kind, business, priority, title, why="", created_ms=None, link=None,
          source="", now_ms=None):
    now_ms = now_ms or int(time.time() * 1000)
    return {
        "id": iid, "kind": kind if kind in KINDS else "REVIEW", "business": business,
        "priority": priority if priority in PRIORITY_RANK else "normal",
        "title": str(title or "")[:160], "why": str(why or "")[:200],
        "ageSec": _age(created_ms, now_ms), "link": link or {}, "source": source,
    }


def _is_archived(business):
    try:
        import business_scope
    except ImportError:
        return False
    try:
        fn = business_scope.is_archived
        if business == "wholesale":
            return bool(fn("wholesale") or fn("rei"))
        return bool(fn(business))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Sources — each takes ctx and returns a list of items. Read the code, not guesses:
# every one mirrors the read its own tab already makes.
# ---------------------------------------------------------------------------

def _src_marcus_proposals(ctx):
    """Marcus seller-reply drafts sitting in the approval inbox (marcus_engine.proposals)."""
    marcus = ctx.get("marcus")
    if not marcus:
        return []
    out = []
    for p in marcus.proposals_list() or []:
        if p.get("status") != "pending":
            continue
        hot = bool(p.get("newLead")) or p.get("classification") == "READY"
        why = ("🆕 new lead — " if p.get("newLead") else "") + (p.get("inbound") or "")
        out.append(_item(f"marcus:{p.get('id')}", "APPROVE", "wholesale",
                         "urgent" if hot else "revenue",
                         f"Approve reply to {p.get('name') or 'seller'}"
                         + (" — HOT" if p.get("classification") == "READY" else ""),
                         why, p.get("ts"), {"ws": "rei", "page": "Agents"}, "marcus"))
    return out


def _src_scout_asap(ctx):
    """Scout's ASAP bucket — hot sellers we have NOT replied to since their last message."""
    scout = ctx.get("scout")
    if not scout:
        return []
    try:
        import send_ledger
    except Exception:
        send_ledger = None
    out = []
    for l in (scout.leads("asap") or {}).get("leads", []):
        conv = l.get("id")
        if send_ledger is not None:
            try:  # already texted back and the seller hasn't said anything new → handled
                replied_at = send_ledger.last_reply_msg_date(conv)
                lmd = int(l.get("lastMessageDate") or 0)
                if replied_at and lmd and lmd <= replied_at:
                    continue
            except Exception:
                pass
        out.append(_item(f"scout:asap:{l.get('contactId') or conv}", "CALL", "wholesale", "urgent",
                         f"Call {l.get('name') or 'seller'} — HOT seller",
                         l.get("reason") or l.get("lastMessage"), l.get("lastMessageDate"),
                         {"ws": "rei", "page": "Leads"}, "scout"))
    return out


def _src_scout_pending_tags(ctx):
    """Warm/nurture tag proposals still waiting for a tap (HOT tags auto-apply)."""
    scout = ctx.get("scout")
    if not scout:
        return []
    out = []
    for bucket in ("warm", "nurture"):
        for l in (scout.leads(bucket) or {}).get("leads", []):
            tags = l.get("proposedTags") or []
            if not tags or l.get("tagsAppliedAt"):
                continue
            out.append(_item(f"scout:tags:{l.get('id')}", "APPROVE", "wholesale", "normal",
                             f"Approve tags for {l.get('name') or 'seller'}: " + ", ".join(map(str, tags)),
                             l.get("reason"), l.get("lastMessageDate"),
                             {"ws": "rei", "page": "Leads"}, "scout"))
    return out


def _src_ace_callready(ctx):
    """ACE's fully-qualified sellers — the operator's only job is the phone call."""
    import ace
    out = []
    for row in (ace.call_ready_list() or {}).get("callReady") or []:
        if row.get("ackAt"):
            continue
        bits = []
        if row.get("score"):
            bits.append(f"screened {row['score']}/10")
        if row.get("askingPrice"):
            bits.append(f"seller asked {row['askingPrice']}")
        if (row.get("anchors") or {}).get("opening"):
            bits.append("Atlas anchors ready")
        out.append(_item(f"ace:{row.get('convId')}", "CALL", "wholesale", "revenue",
                         f"Call {row.get('name') or 'seller'} — ACE call-ready",
                         " · ".join(bits), row.get("updatedAt"),
                         {"ws": "rei", "page": "Leads"}, "ace"))
    return out


def _src_screenings(ctx):
    """Marcus screening: interested → CALL (with Atlas card if prepped); check-back due → APPROVE."""
    screener = ctx.get("screener")
    if not screener:
        return []
    deal_prep = ctx.get("deal_prep")
    now = int(time.time() * 1000)
    fresh_ms = CALL_FRESH_DAYS * 24 * 3600 * 1000
    out = []
    for cid, r in list((getattr(screener, "screenings", None) or {}).items()):
        rep = r.get("report") or {}
        name = r.get("name") or "seller"
        if r.get("checkBackDue"):
            out.append(_item(f"screen:cb:{cid}", "APPROVE", "wholesale", "normal",
                             f"Send check-back to {name}", rep.get("nurtureDraft"),
                             r.get("updatedAt"), {"ws": "rei", "page": "Agents"}, "marcus"))
        elif rep.get("interest") == "interested" and now - (r.get("updatedAt") or 0) < fresh_ms:
            why = rep.get("summary") or rep.get("notes") or ""
            if deal_prep is not None:
                try:
                    if ((deal_prep.get(cid) or {}).get("prep") or {}).get("anchors"):
                        why = "Atlas call card ready · " + why
                except Exception:
                    pass
            score = rep.get("score")
            out.append(_item(f"screen:{cid}", "CALL", "wholesale", "revenue",
                             f"Call {name} — screened" + (f" {score}/10," if score else ",") + " interested",
                             why, r.get("updatedAt"), {"ws": "rei", "page": "Agents"}, "marcus"))
    return out


def _src_agency_callsheet(ctx):
    """Call Sheet: callback/interested rows individually; fresh 'new' rows as ONE dial item."""
    import agency_callsheet
    leads = (agency_callsheet.list_leads() or {}).get("leads") or []
    out, fresh = [], 0
    for l in leads:
        st = l.get("status") or "new"
        if st in ("callback", "interested"):
            who = l.get("company") or l.get("name") or "prospect"
            why = l.get("note") or l.get("pain") or ""
            if l.get("last_called"):
                why = f"last called {l['last_called']} · " + why
            out.append(_item(f"callsheet:{l.get('id')}", "CALLBACK", "agency", "revenue",
                             f"Call back {who}" + (" — interested" if st == "interested" else ""),
                             why, None, {"ws": "agency", "page": "CallCenter"}, "callsheet"))
        elif st == "new":
            fresh += 1
    if fresh:
        out.append(_item("callsheet:new", "CALL", "agency", "revenue",
                         f"{fresh} prospect{'s' if fresh != 1 else ''} ready to dial",
                         "Call Sheet rows not yet called", None,
                         {"ws": "agency", "page": "CallCenter"}, "callsheet"))
    return out


def _src_agency_approvals(ctx):
    """Agency Approval Center — pending only. The in-memory mock seed (no state file yet,
    or refId seed-*) is NOT an owner action."""
    import agency_approvals_io
    if not agency_approvals_io.STATE.exists():
        return []
    out = []
    for a in (agency_approvals_io.list_queue("pending") or {}).get("queue") or []:
        if str(a.get("refId") or "").startswith("seed-"):
            continue
        risk = str(a.get("risk") or "low").lower()
        out.append(_item(f"agency-approval:{a.get('id')}", "APPROVE", "agency",
                         "urgent" if risk == "high" else "customer",
                         a.get("title") or "Agency approval",
                         (f"{a.get('client')} · " if a.get("client") else "") + (a.get("summary") or ""),
                         a.get("createdAt"), {"ws": "agency", "page": "Approvals"}, "agency_approvals"))
    return out


def _src_agency_requests(ctx):
    """Client edit requests nobody has looked at yet."""
    import agency_requests_io
    out = []
    for r in (agency_requests_io.list_requests() or {}).get("requests") or []:
        if r.get("status") != "submitted":
            continue
        pri = str(r.get("priority") or "").lower()
        out.append(_item(f"request:{r.get('id')}", "REVIEW", "agency",
                         "urgent" if pri in ("urgent", "high") else "customer",
                         f"Review {r.get('clientName') or 'client'} request: {r.get('title') or ''}",
                         r.get("detail"), r.get("createdAt"),
                         {"ws": "agency", "page": "Requests"}, "agency_requests"))
    return out


# in-process cache for the daycare GHL read (paged contacts list — never poll it per refresh)
_DC = {"at": 0.0, "items": [], "fails": 0, "err": ""}


def _src_daycare_inquiries(ctx):
    """Website inquiries in the Parent Logins inbox (daycare_ghl.pending_families, kind=inquiry)
    that are neither dismissed nor already enrolled. Network → cached DAYCARE_TTL_SEC."""
    now = time.time()
    if now - _DC["at"] < DAYCARE_TTL_SEC:
        return list(_DC["items"])
    try:
        import daycare_ghl
        client = ctx.get("daycare_client")
        items = []
        for f in daycare_ghl.pending_families(client) if client is not None else []:
            cid = f.get("contact_id")
            if f.get("kind") != "inquiry" or not cid:
                continue
            if daycare_ghl.is_dismissed(cid) or daycare_ghl.form_child_id(cid):
                continue
            bits = [b for b in (f.get("child_name"), f.get("classroom_label"),
                                f.get("location_tag")) if b]
            items.append(_item(f"daycare:{cid}", "CALL", "daycare", "revenue",
                               f"Call {f.get('parent_name') or 'family'} — new enrollment inquiry",
                               " · ".join(map(str, bits)), _iso_ms(f.get("created_at")),
                               {"ws": "daycare", "page": "ParentLogins"}, "daycare_ghl"))
        _DC.update(at=now, items=items, fails=0, err="")
    except Exception as e:  # noqa: BLE001 — fail soft, back off, surface only if repeated
        _DC.update(at=now, fails=_DC["fails"] + 1, err=str(e)[:120])
        if _DC["fails"] >= DAYCARE_FAILS_BEFORE_FIX:
            return [_item("fix:daycare_ghl", "FIX", "daycare", "urgent",
                          "Daycare GHL read failing", f"{_DC['fails']}x: {_DC['err']}",
                          None, {"ws": "daycare", "page": "Settings"}, "daycare_ghl")] + list(_DC["items"])
    return list(_DC["items"])


def _src_daycare_leads(ctx):
    """Daycare Lead Desk (daycare_leads.needs_human): {id, title, why, ageSec,
    priority URGENT|REVENUE|NORMAL, contactId, ...}. Keyed daycare:<contactId> like the
    inquiry source so one family is ONE row; this source runs first, so it wins."""
    try:
        import daycare_leads
    except ImportError:
        return []
    now = int(time.time() * 1000)
    out = []
    for r in daycare_leads.needs_human() or []:
        if not isinstance(r, dict) or not r.get("contactId"):
            continue
        age = r.get("ageSec")
        created = now - int(age) * 1000 if isinstance(age, (int, float)) else None
        out.append(_item(f"daycare:{r['contactId']}", "CALL", "daycare",
                         str(r.get("priority") or "urgent").lower(),
                         r.get("title") or "Call family — needs a human", r.get("why"),
                         created, {"ws": "daycare", "page": "Dashboard"}, "daycare_leads",
                         now_ms=now))
    return out


def _src_system(ctx):
    """Red heartbeats + AI hard-down, read from the api_system_health dict the connector passes."""
    sysd = ctx.get("system") or {}
    out = []
    if sysd.get("active"):
        for l in sysd.get("loops") or []:
            if l.get("status") == "red":
                out.append(_item(f"heartbeat:{l.get('loop')}", "FIX", "system", "urgent",
                                 f"Loop down: {l.get('label') or l.get('loop')}",
                                 l.get("lastError") or "no heartbeat", l.get("lastRun"),
                                 {"view": "health"}, "heartbeat"))
    ai = sysd.get("ai")
    if isinstance(ai, dict) and ai.get("ok") is False:
        out.append(_item("ai:down", "FIX", "system", "urgent", "Anthropic credits/auth",
                         ai.get("error") or ai.get("reason") or "AI calls failing — every agent is blind",
                         ai.get("downSince") or ai.get("lastErrorAt"), {"view": "health"}, "ai"))
    return out


def _src_skill_forge(ctx):
    import skill_forge
    out = []
    for p in (skill_forge.pending() or {}).get("pending") or []:
        out.append(_item(f"skillforge:{p.get('id')}", "REVIEW", "system", "normal",
                         f"Review proposed skill: {p.get('title') or p.get('topic') or ''}",
                         (p.get("body") or "")[:120], p.get("ts"),
                         {"ws": "rei", "page": "Agents"}, "skill_forge"))
    return out


# (name, business, fn) — business drives archive-skip + the FIX item on failure.
SOURCES = [
    ("marcus_proposals", "wholesale", _src_marcus_proposals),
    ("scout_asap", "wholesale", _src_scout_asap),
    ("scout_pending_tags", "wholesale", _src_scout_pending_tags),
    ("ace_callready", "wholesale", _src_ace_callready),
    ("screenings", "wholesale", _src_screenings),
    ("agency_callsheet", "agency", _src_agency_callsheet),
    ("agency_approvals", "agency", _src_agency_approvals),
    ("agency_requests", "agency", _src_agency_requests),
    ("daycare_leads", "daycare", _src_daycare_leads),   # first: richer row wins the dedupe
    ("daycare_inquiries", "daycare", _src_daycare_inquiries),
    ("system", "system", _src_system),
    ("skill_forge", "system", _src_skill_forge),
]


def build(ctx, sources=None):
    """ctx: {scout, marcus, screener, deal_prep, daycare_client, system}. Never raises."""
    ctx = ctx or {}
    items = []
    for name, business, fn in (sources if sources is not None else SOURCES):
        if business != "system" and _is_archived(business):
            continue
        try:
            items.extend(fn(ctx) or [])
        except Exception as e:  # noqa: BLE001 — one FIX row, the rest of the list survives
            items.append(_item(f"fix:{name}", "FIX", business, "urgent",
                               f"Can't read {name.replace('_', ' ')}", str(e)[:160], None,
                               {"view": "health"}, name))
    items = merge_and_sort(items)
    counts = {"total": len(items)}
    for k in KINDS:
        counts[k] = sum(1 for i in items if i["kind"] == k)
    for p in PRIORITY_RANK:
        counts[p] = sum(1 for i in items if i["priority"] == p)
    return {"ok": True, "generatedAt": int(time.time() * 1000), "counts": counts, "items": items}


if __name__ == "__main__":
    import json
    print(json.dumps(build({}), indent=1)[:3000])
