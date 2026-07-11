"""telegram_ops.py — full remote control of FORGE REI OS from Telegram.

Texting the bot now COMMANDS the operation, not just chats with it. The agents act
as employees: deterministic slash-commands run instantly, plain English is parsed
into an action by Claude (falls through to normal agent chat when it's just talk),
and anything OUTWARD (an SMS to a seller) comes back as a draft with a one-tap
✅ Send / ❌ Cancel button — propose → review → execute, with the operator's tap
as the review. Nothing texts a seller without that tap.

Command surface (also in /ops):
  /today            today's battle plan, numbered      /done 3   check item off
  /hot              Scout's text-back-now list          /sweep    run a Scout sweep
  /screen <name>    Marcus screens the seller           /find <name>  contact lookup
  /text <name>: <msg>   draft an SMS  -> confirm tap    /checkback <name>  nurture send -> tap
  /proposals        pending Marcus drafts w/ buttons    /report   ops snapshot
Plain English works too: "text arthur tell him I can call at 3" → same confirm flow.

Wiring: connector calls register(handlers); telegram_io._handle_message calls
route(...) before agent chat; confirm taps dispatch through telegram_io._ACTIONS
("opsgo:<token>" / "opsno:<token>" → confirm()/cancel()).
"""
import hashlib
import json
import re
import threading
import time
from pathlib import Path

import forge_atomic

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "telegram_ops.json"
_LOCK = threading.Lock()
PENDING_TTL = 3600          # confirm buttons live 1 hour

_H = {}                     # handlers injected by the connector
_SESS = {}                  # chat_id -> {"todayMap": {n: taskId}, "pick": {...}}


def register(handlers):
    """Connector injects: scout, screener, marcus, do_today, ghl_get, location_id,
    send_sms(cid,msg,name), send_nurture(cid,msg), claude_key() -> str|None."""
    _H.update(handlers or {})


# ── pending outward actions (confirm-gated) ──────────────────────────────────
def _load():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {"pending": {}}


def _save(d):
    forge_atomic.atomic_write_json(STATE, d)


def _queue_pending(kind, contact_id, name, message, extra=None):
    tok = hashlib.sha1(f"{kind}|{contact_id}|{time.time()}".encode()).hexdigest()[:12]
    with _LOCK:
        d = _load()
        now = int(time.time())
        d["pending"] = {k: v for k, v in d.get("pending", {}).items()
                        if now - v.get("ts", 0) < PENDING_TTL}
        row = {"kind": kind, "contactId": contact_id, "name": name,
               "message": message, "ts": now}
        if isinstance(extra, dict):
            row.update(extra)
        d["pending"][tok] = row
        _save(d)
    return tok


def confirm(token):
    """✅ tap — the operator's review. Fires the actual outward send."""
    with _LOCK:
        d = _load()
        p = d.get("pending", {}).pop(token, None)
        _save(d)
    if not p:
        return {"error": "expired — draft it again"}
    if int(time.time()) - p.get("ts", 0) > PENDING_TTL:
        return {"error": "expired — draft it again"}
    try:
        if p["kind"] == "move_stage":
            res = _H["move_stage"](p)
            if isinstance(res, dict) and res.get("error"):
                return res
            tag_note = ""
            tags = p.get("tags") or []
            if tags:
                tres = _H["tag_contact"]({
                    "contactId": p.get("contactId"), "tags": tags,
                    "op": p.get("tagOp") or "add", "name": p.get("name"),
                    "convId": p.get("convId"),
                })
                if isinstance(tres, dict) and tres.get("error"):
                    tag_note = f"; tag failed: {tres['error']}"
                else:
                    tag_note = f"; tagged {', '.join(tags)}"
            msg = f"Moved {p.get('name') or 'seller'} → {p.get('stage')}{tag_note}"
            _receipt("marcus", msg, {
                "type": "agent_command", "action": "move_stage",
                "contactId": p.get("contactId"), "opportunityId": p.get("opportunityId"),
                "stage": p.get("stage"), "tags": tags,
            }, telegram=True)
            return {"ok": True, "message": msg}
        if p["kind"] == "checkback":
            res = _H["send_nurture"](p["contactId"], p["message"])
        else:
            res = _H["send_sms"](p["contactId"], p["message"], p.get("name"))
        if isinstance(res, dict) and res.get("error"):
            return res
        return {"ok": True, "message": f"Sent to {p.get('name') or 'seller'}"}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def cancel(token):
    with _LOCK:
        d = _load()
        p = d.get("pending", {}).pop(token, None)
        _save(d)
    return {"ok": True, "message": "Cancelled"} if p else {"error": "already gone"}


# ── contact resolution ────────────────────────────────────────────────────────
def _find_contacts(name):
    data = _H["ghl_get"]("/contacts/", {"locationId": _H["location_id"],
                                        "query": name, "limit": 5})
    out = []
    for c in (data.get("contacts") or []):
        nm = (f"{c.get('firstName', '')} {c.get('lastName', '')}").strip() \
            or c.get("contactName") or c.get("email") or "?"
        out.append({"id": c.get("id"), "name": nm, "phone": c.get("phone") or ""})
    return out


def _esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _norm_text(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _norm_phone(s):
    return re.sub(r"\D+", "", str(s or ""))


def _tag_list(v):
    raw = v if isinstance(v, list) else re.split(r",|\band\b", str(v or ""))
    out = []
    for t in raw:
        tag = re.sub(r"^(?:as|with|tagged|tag|tags?)\s+", "", str(t).strip(), flags=re.I)
        tag = re.sub(r"^(?:him|her|them|it|the contact|this contact)\s+", "", tag, flags=re.I)
        tag = tag.strip(" .;:").lower()
        if tag and tag not in out:
            out.append(tag)
    return out


def _clean_stage(stage):
    s = str(stage or "").strip().strip(".")
    s = re.sub(r"\s+and\s+tag\s+.*$", "", s, flags=re.I)
    s = re.sub(r"\s+(?:section|stage)(?:\s+of\s+the\s+pipeline)?$", "", s, flags=re.I)
    s = re.sub(r"\s+pipeline$", "", s, flags=re.I)
    return s.replace("-", " ").strip()


def _rule_intent(text):
    t = str(text or "").strip()
    # "put Christopher Giles in the under-contract section of the pipeline and tag him motivated"
    m = re.search(
        r"\b(?:move|put|place|advance)\s+(?P<contact>.+?)\s+"
        r"(?:to|into|in)\s+(?:the\s+)?(?P<stage>.+?)(?:\s+and\s+tag\s+"
        r"(?P<tags>.+))?\s*$",
        t, re.I)
    if m:
        stage = _clean_stage(m.group("stage"))
        tags = _tag_list(m.group("tags"))
        if m.group("contact") and stage:
            out = {"action": "move_stage", "contact": m.group("contact").strip(),
                   "stage": stage}
            if tags:
                out["tags"] = tags
                out["tagOp"] = "add"
            return out
    m = re.search(
        r"\b(?P<op>remove|delete|drop)\s+tags?\s+(?P<tags>.+?)\s+"
        r"(?:from|off)\s+(?P<contact>.+)$", t, re.I)
    if m:
        return {"action": "tag", "contact": m.group("contact").strip(),
                "tags": _tag_list(m.group("tags")), "op": "remove"}
    m = re.search(
        r"\b(?:add|apply|set)\s+tags?\s+(?P<tags>.+?)\s+"
        r"(?:to|on|for)\s+(?P<contact>.+)$", t, re.I)
    if m:
        return {"action": "tag", "contact": m.group("contact").strip(),
                "tags": _tag_list(m.group("tags")), "op": "add"}
    m = re.search(r"\b(?:tag|label)\s+(?P<contact>.+?)\s+(?:as|with)\s+(?P<tags>.+)$",
                  t, re.I)
    if m:
        return {"action": "tag", "contact": m.group("contact").strip(),
                "tags": _tag_list(m.group("tags")), "op": "add"}
    return None


def _candidate_matches(query, cand):
    qn = _norm_text(query)
    qp = _norm_phone(query)
    if qp and qp in _norm_phone(cand.get("phone")):
        return True
    if not qn:
        return False
    hay = _norm_text(" ".join([
        cand.get("name") or "", cand.get("phone") or "",
        cand.get("lastMessage") or "",
    ]))
    return qn in hay


def _merge_candidate(bucket, cand):
    if not isinstance(cand, dict):
        return
    cid = cand.get("contactId") or cand.get("id")
    key = cid or f"{_norm_text(cand.get('name'))}|{_norm_phone(cand.get('phone'))}"
    if not key:
        return
    cur = bucket.setdefault(key, {
        "contactId": cid, "name": cand.get("name") or "Unknown",
        "phone": cand.get("phone") or "", "lastMessage": cand.get("lastMessage") or "",
        "convId": cand.get("convId"), "opportunities": [],
    })
    for field in ("contactId", "name", "phone", "lastMessage", "convId"):
        if cand.get(field) and not cur.get(field):
            cur[field] = cand.get(field)
    if cand.get("opportunityId"):
        opp = {
            "id": cand.get("opportunityId"), "pipelineId": cand.get("pipelineId"),
            "stageId": cand.get("stageId"), "status": cand.get("status"),
            "stage": cand.get("stage"),
        }
        if opp["id"] and all(o.get("id") != opp["id"] for o in cur["opportunities"]):
            cur["opportunities"].append(opp)


def _resolve_contacts(query):
    found = {}
    try:
        for c in _find_contacts(query):
            _merge_candidate(found, {
                "contactId": c.get("id"), "name": c.get("name"),
                "phone": c.get("phone"),
            })
    except Exception:  # noqa: BLE001
        pass
    scout = _H.get("scout")
    scout_records = list(getattr(scout, "records", {}).values()) if scout is not None else []
    for r in scout_records:
        cand = {
            "contactId": r.get("contactId"), "name": r.get("name"),
            "phone": r.get("phone"), "lastMessage": r.get("lastMessage"),
            "convId": r.get("convId"),
        }
        if _candidate_matches(query, cand):
            _merge_candidate(found, cand)
    oppfn = _H.get("opportunities")
    if oppfn:
        try:
            for o in oppfn() or []:
                cand = {
                    "contactId": o.get("contactId"), "name": o.get("name"),
                    "phone": o.get("phone"), "opportunityId": o.get("id"),
                    "pipelineId": o.get("pipelineId"), "stageId": o.get("stageId"),
                    "stage": o.get("stage"), "status": o.get("status"),
                }
                if _candidate_matches(query, cand):
                    _merge_candidate(found, cand)
        except Exception:  # noqa: BLE001
            pass
    return [c for c in found.values() if c.get("contactId")]


def _attach_opportunities(cand):
    if not cand or not cand.get("contactId") or cand.get("opportunities"):
        return cand
    fn = _H.get("find_opportunities")
    if not fn:
        return cand
    try:
        for o in fn(cand["contactId"]) or []:
            _merge_candidate({cand.get("contactId"): cand}, {
                "contactId": cand.get("contactId"), "name": cand.get("name"),
                "phone": cand.get("phone"), "opportunityId": o.get("id"),
                "pipelineId": o.get("pipelineId"), "stageId": o.get("pipelineStageId"),
                "status": o.get("status"), "stage": o.get("stage"),
            })
    except Exception:  # noqa: BLE001
        pass
    return cand


def _pick_opportunity(cand):
    cand = _attach_opportunities(cand)
    opps = cand.get("opportunities") or []
    if not opps:
        return None, None
    open_opps = [o for o in opps if (o.get("status") or "open").lower() == "open"]
    choices = open_opps or opps
    if len(choices) == 1:
        return choices[0], None
    labels = [f"{o.get('id')} ({o.get('stage') or o.get('status') or 'unknown stage'})"
              for o in choices[:5]]
    return None, "multiple opportunities found: " + ", ".join(labels)


def _candidate_lines(matches):
    lines = []
    for i, m in enumerate(matches[:8], 1):
        snippet = (m.get("lastMessage") or "").replace("\n", " ")[:90]
        tail = f" — {snippet}" if snippet else ""
        lines.append(f"{i}. {_esc(m.get('name') or 'Unknown')} "
                     f"({_esc(m.get('phone') or 'no phone')}){_esc(tail)}")
    return "\n".join(lines)


def _resolve_stage(stage):
    fn = _H.get("resolve_stage")
    if not fn:
        return {"error": "pipeline stage lookup is not wired"}
    return fn(_clean_stage(stage))


def _receipt(agent_id, text, data=None, telegram=False):
    bus = _H.get("bus_send")
    if bus:
        try:
            bus(agent_id or "marcus", "all", "note", text, data or {})
        except Exception:  # noqa: BLE001
            pass
    if telegram and _H.get("telegram_send"):
        try:
            _H["telegram_send"](text, dedupe_key=f"agentcmd:{hashlib.sha1(text.encode()).hexdigest()[:12]}")
        except Exception:  # noqa: BLE001
            pass


def _send_or_telegram(text, buttons, send=None):
    if send:
        send(text, buttons)
        return {"ok": True}
    tg = _H.get("telegram_send")
    if not tg:
        return {"error": "Telegram confirm is not configured"}
    return tg(text, buttons=buttons,
              dedupe_key=f"agentcmd_confirm:{hashlib.sha1(text.encode()).hexdigest()[:12]}")


def _queue_move(match, stage_info, tags=None, tag_op="add", send=None):
    opp, opp_err = _pick_opportunity(match)
    if opp_err:
        return {"reply": f"I found {_esc(match.get('name'))}, but {opp_err}. Tell me which opportunity/stage."}
    if not opp and not match.get("convId"):
        return {"reply": f"I found {_esc(match.get('name'))}, but no opportunity or Scout lead record to move."}
    stage = stage_info.get("stage") or _clean_stage(stage_info.get("input"))
    tok = _queue_pending("move_stage", match.get("contactId"), match.get("name"), "",
                         {"stage": stage, "stageId": stage_info.get("stageId"),
                          "pipelineId": stage_info.get("pipelineId"),
                          "opportunityId": (opp or {}).get("id"),
                          "convId": match.get("convId"), "tags": tags or [],
                          "tagOp": tag_op or "add"})
    tag_line = f"\nTags on approval: <b>{_esc(', '.join(tags or []))}</b>" if tags else ""
    text = (f"Move <b>{_esc(match.get('name'))}</b> "
            f"({_esc(match.get('phone') or 'no phone')}) → <b>{_esc(stage)}</b>?{tag_line}")
    res = _send_or_telegram(text, [[{"text": "✅ Move", "callback_data": f"opsgo:{tok}"},
                                    {"text": "❌ Cancel", "callback_data": f"opsno:{tok}"}]], send)
    if res.get("error"):
        return {"reply": f"Move queued, but I couldn't send the confirm button: {res['error']}"}
    return {"reply": f"Queued the move for approval: {match.get('name')} → {stage}.",
            "sent": True}


def _run_tag(match, tags, op="add", send=None, source="telegram", agent_id="marcus"):
    tags = _tag_list(tags)
    if not tags:
        return {"reply": "Which tag should I apply?"}
    res = _H["tag_contact"]({"contactId": match.get("contactId"), "tags": tags,
                             "op": op, "name": match.get("name"),
                             "convId": match.get("convId")})
    if isinstance(res, dict) and res.get("error"):
        return {"reply": f"Tag update failed for {_esc(match.get('name'))}: {_esc(res['error'])}"}
    verb = "Removed" if op == "remove" else "Tagged"
    msg = f"{verb} {match.get('name') or 'seller'}: {', '.join(tags)}"
    _receipt(agent_id, msg, {"type": "agent_command", "action": "tag",
                             "contactId": match.get("contactId"), "tags": tags,
                             "op": op}, telegram=(source != "telegram"))
    if send:
        send(_esc(msg))
        return {"reply": msg, "sent": True}
    return {"reply": msg}


def _handle_write_intent(it, chat_id=None, send=None, source="telegram", agent_id="marcus",
                         selected=None):
    action = (it.get("action") or "").strip()
    contact = (it.get("contact") or it.get("name") or "").strip()
    matches = [selected] if selected else _resolve_contacts(contact)
    if not matches:
        return {"reply": f"I couldn't find one contact matching “{_esc(contact)}”. Send a fuller name or phone."}
    if len(matches) > 1:
        if chat_id and send:
            _SESS.setdefault(chat_id, {})["pick"] = {
                "kind": action, "matches": matches, "intent": it, "ts": time.time()}
        return {"reply": f"Which contact?\n{_candidate_lines(matches)}\n\nReply with the number."}
    match = matches[0]
    if action == "move_stage":
        stage = _clean_stage(it.get("stage"))
        if not stage:
            return {"reply": "Which pipeline stage should I move them to?"}
        stage_info = _resolve_stage(stage)
        if stage_info.get("error"):
            choices = ", ".join(stage_info.get("stages") or [])
            return {"reply": f"I couldn't find stage “{_esc(stage)}”. Available: {_esc(choices)}"}
        return _queue_move(match, stage_info, tags=_tag_list(it.get("tags")),
                           tag_op=it.get("tagOp") or "add", send=send)
    if action == "tag":
        return _run_tag(match, it.get("tags") or [], op=(it.get("op") or "add"),
                        send=send, source=source, agent_id=agent_id)
    return None


def handle_agent_command(agent_id, text, source="dashboard"):
    """Shared write-command entry point for in-app agent chat."""
    it = _command_intent(text)
    if not it or it.get("action") not in ("move_stage", "tag"):
        return None
    out = _handle_write_intent(it, source=source, agent_id=agent_id or "marcus")
    return {"reply": out.get("reply") or "Command handled.", "agent": agent_id or "Marcus",
            "command": it.get("action")}


# ── the actions ───────────────────────────────────────────────────────────────
def _do_today(chat_id, send):
    v = _H["do_today"].view()
    tasks = v.get("tasks", [])
    if not tasks:
        send("☀️ Board's clear — nothing waiting on you.")
        return
    sess = _SESS.setdefault(chat_id, {})
    sess["todayMap"] = {}
    lines = [f"☀️ <b>Do Today</b> — {v.get('doneCount', 0)}/{v.get('total', 0)} done"]
    for i, t in enumerate(tasks, 1):
        sess["todayMap"][str(i)] = t["id"]
        box = "✅" if t.get("done") else "▢"
        lines.append(f"{box} {i}. [{t['label']}] {_esc(t['title'])}")
    lines.append("\n<code>/done 3</code> checks one off")
    send("\n".join(lines)[:4000])


def _done(chat_id, arg, send):
    sess = _SESS.get(chat_id) or {}
    tmap = sess.get("todayMap") or {}
    tid = tmap.get(arg.strip())
    if not tid:
        # match by name fragment against today's tasks
        frag = arg.strip().lower()
        for t in _H["do_today"].view().get("tasks", []):
            if frag and frag in t["title"].lower():
                tid = t["id"]
                break
    if not tid:
        send("Couldn't find that item — run /today first, then /done &lt;number&gt;.")
        return
    v = _H["do_today"].check(tid, True)
    send(f"✅ Checked off. {v.get('doneCount', 0)}/{v.get('total', 0)} done today.")


def _hot(send):
    leads = (_H["scout"].leads("asap") or {}).get("leads", [])
    if not leads:
        send("🔥 No hot sellers waiting right now.")
        return
    lines = ["🔥 <b>Text back now</b>"]
    for l in leads[:8]:
        lines.append(f"• <b>{_esc(l.get('name'))}</b> ({l.get('motivation')}) — "
                     f"{_esc(l.get('reason') or l.get('lastMessage') or '')[:80]}")
    lines.append("\n<code>/text &lt;name&gt;: &lt;message&gt;</code> to reply")
    send("\n".join(lines)[:4000])


def _sweep(send):
    send("🔭 Scout sweeping now…")

    def run():
        try:
            _H["scout"].poll_once()
            counts = (_H["scout"].summary() or {}).get("counts", {})
            send(f"🔭 Sweep done — {counts.get('asap', 0)} hot · "
                 f"{counts.get('warm', 0)} warm · {counts.get('nurture', 0)} nurture.")
        except Exception as e:  # noqa: BLE001
            send(f"⚠ Sweep failed: {_esc(e)}")
    threading.Thread(target=run, daemon=True).start()


def _screen(name, send):
    matches = _find_contacts(name)
    if not matches:
        send(f"No GHL contact matching “{_esc(name)}”.")
        return
    m = matches[0]
    send(f"🩺 Marcus is screening <b>{_esc(m['name'])}</b>…")

    def run():
        try:
            res = _H["screener"].screen(contact_id=m["id"])
            r = (res or {}).get("screening") or {}
            rep = r.get("report") or {}
            if res.get("error"):
                send(f"⚠ Screening failed: {_esc(res['error'])}")
                return
            send(f"🩺 <b>{_esc(m['name'])}</b> — score {rep.get('score', '?')}/10 · "
                 f"{_esc(rep.get('interest', '?'))} · stage {_esc(rep.get('stage', '?'))}\n"
                 f"{_esc(rep.get('sellerSituation') or '')[:300]}")
        except Exception as e:  # noqa: BLE001
            send(f"⚠ Screening failed: {_esc(e)}")
    threading.Thread(target=run, daemon=True).start()


def _find(name, send):
    matches = _find_contacts(name)
    if not matches:
        send(f"No GHL contact matching “{_esc(name)}”.")
        return
    lines = ["🔎 <b>Contacts</b>"]
    for m in matches:
        lines.append(f"• <b>{_esc(m['name'])}</b> — <code>{_esc(m['phone'] or 'no phone')}</code>")
    send("\n".join(lines))


def _text_seller(chat_id, name, message, send):
    """Draft an SMS → confirm buttons. The tap is the approval (rule: gated outward)."""
    if not message:
        send("Give me the message too: <code>/text arthur: I can call at 3pm</code>")
        return
    matches = _find_contacts(name)
    if not matches:
        send(f"No GHL contact matching “{_esc(name)}”.")
        return
    if len(matches) > 1 and matches[0]["name"].lower() != name.strip().lower():
        opts = "\n".join(f"{i}. {_esc(m['name'])} ({_esc(m['phone'])})"
                         for i, m in enumerate(matches, 1))
        _SESS.setdefault(chat_id, {})["pick"] = {
            "kind": "text", "matches": matches, "message": message, "ts": time.time()}
        send(f"Which one?\n{opts}\n\nReply with the number.")
        return
    m = matches[0]
    tok = _queue_pending("sms", m["id"], m["name"], message)
    send(f"📤 <b>To {_esc(m['name'])}</b> ({_esc(m['phone'])}):\n"
         f"“{_esc(message)}”\n\nSend it?",
         [[{"text": "✅ Send", "callback_data": f"opsgo:{tok}"},
           {"text": "❌ Cancel", "callback_data": f"opsno:{tok}"}]])


def _checkback(chat_id, name, send):
    """One-tap nurture check-back from the screening report's draft."""
    scr = _H["screener"]
    frag = name.strip().lower()
    for cid, r in list(getattr(scr, "screenings", {}).items()):
        rep = r.get("report") or {}
        if frag in (r.get("name") or "").lower() and rep.get("nurtureDraft"):
            tok = _queue_pending("checkback", cid, r.get("name"), rep["nurtureDraft"])
            send(f"📅 <b>Check-back to {_esc(r.get('name'))}</b>:\n"
                 f"“{_esc(rep['nurtureDraft'])}”\n\nSend it?",
                 [[{"text": "✅ Send", "callback_data": f"opsgo:{tok}"},
                   {"text": "❌ Cancel", "callback_data": f"opsno:{tok}"}]])
            return
    send(f"No screened seller matching “{_esc(name)}” with a nurture draft. "
         f"Try <code>/screen {_esc(name)}</code> first.")


def _proposals(send):
    props = [p for p in _H["marcus"].proposals_list() if p.get("status") == "pending"]
    if not props:
        send("📭 No pending drafts.")
        return
    for p in props[:5]:
        send(f"💬 <b>{_esc(p.get('name'))}</b> said: “{_esc(p.get('inbound'))[:120]}”\n"
             f"Draft: “{_esc(p.get('suggestedReply'))[:300]}”",
             [[{"text": "✅ Approve & send", "callback_data": f"approve:{p['id']}"},
               {"text": "🗑 Dismiss", "callback_data": f"mdismiss:{p['id']}"}]])
    if len(props) > 5:
        send(f"…and {len(props) - 5} more in the Command Center.")


def _prep(name, send):
    """Atlas's deal-prep card for a screened seller — anchors, MAO note, call card."""
    dp = _H.get("deal_prep")
    if dp is None:
        send("Atlas isn't wired up yet.")
        return
    frag = name.strip().lower()
    rec = None
    for r in (dp.list_all() or {}).get("preps", []):
        if frag in (r.get("name") or "").lower():
            rec = r
            break
    if not rec:
        send(f"No deal prep for “{_esc(name)}” yet. Atlas preps screened-interested "
             f"sellers every 15 min, or try <code>/screen {_esc(name)}</code> first.")
        return
    pr = rec.get("prep") or {}
    a = pr.get("anchors") or {}

    def fmt(v):
        return f"${v:,.0f}" if isinstance(v, (int, float)) and v else "—"
    lines = [f"📐 <b>{_esc(rec.get('name'))}</b> — Atlas's deal prep",
             f"{_esc(pr.get('address') or 'address unknown')} · ask {fmt(pr.get('askingPrice'))}",
             f"cond: {_esc(pr.get('condition'))} · occ: {_esc(pr.get('occupancy'))} · repairs: {_esc(pr.get('repairEstimate'))}",
             f"\n<b>Anchors:</b> open {fmt(a.get('opening'))} · target {fmt(a.get('target'))} · walk {fmt(a.get('walkaway'))}",
             f"<i>{_esc(pr.get('anchorLogic'))}</i>",
             f"\n<b>MAO:</b> {_esc(pr.get('maoNote'))}"]
    cc = pr.get("callCard") or []
    if cc:
        lines.append("\n<b>Call card:</b>\n" + "\n".join(f"• {_esc(c)}" for c in cc[:7]))
    rf = pr.get("redFlags") or []
    if rf:
        lines.append("\n⚠ " + " · ".join(_esc(x) for x in rf[:4]))
    send("\n".join(lines)[:4000])


def _directives(send):
    """Marcus surveys the whole operation and issues orders — to Scout + to you."""
    send("📋 Marcus is surveying the operation…")

    def run():
        try:
            d = _H["directives"]()
            if d.get("error"):
                send(f"⚠ {_esc(d['error'])}")
                return
            send(f"🎯 <b>{_esc(d.get('focus') or 'Orders')}</b>\n\n"
                 f"<b>You:</b>\n{_esc(d.get('operator') or '—')}\n\n"
                 f"<b>Scout:</b>\n{_esc(d.get('scout') or '—')}")
        except Exception as e:  # noqa: BLE001
            send(f"⚠ Directives failed: {_esc(e)}")
    threading.Thread(target=run, daemon=True).start()


def _autopilot(arg, send):
    """Opt-in auto-send tier for the no-response re-engage bumps (everything else stays
    tap-gated). /autopilot on | /autopilot off | /autopilot (status)."""
    if "autopilot_status" not in _H:               # graceful before the connector wires it
        send("🤖 Autopilot isn't wired up on this build yet.")
        return
    a = (arg or "").strip().lower()
    if a in ("on", "off") and "autopilot_set" in _H:
        st = _H["autopilot_set"](a == "on") or {}
    else:
        st = _H["autopilot_status"]() or {}
    lines = [
        f"🤖 <b>Autopilot</b> — {'🟢 ON' if st.get('enabled') else '⚪ OFF'}",
        f"Sent today: <b>{st.get('sentToday', 0)}/{st.get('cap', 0)}</b>",
        "Scope: re-engage bumps only · 9am–8pm ET · legit-checked · receipt per send",
    ]
    last = (st.get("log") or [])[:3]
    if last:
        lines.append("\n<b>Last auto-sends:</b>")
        for e in last:
            lines.append(f"• <b>{_esc(e.get('name'))}</b> — “{_esc(e.get('reply'))[:90]}”")
    lines.append("\n<code>/autopilot off</code> to stop" if st.get("enabled")
                 else "\n<code>/autopilot on</code> to enable")
    send("\n".join(lines)[:4000])


def _report(send):
    bits = []
    try:
        c = (_H["scout"].summary() or {}).get("counts", {})
        bits.append(f"🔭 Scout: {c.get('asap', 0)} hot · {c.get('warm', 0)} warm · "
                    f"{c.get('nurture', 0)} nurture")
    except Exception:  # noqa: BLE001
        pass
    try:
        pend = sum(1 for p in _H["marcus"].proposals_list() if p.get("status") == "pending")
        bits.append(f"💬 Marcus drafts pending: {pend}")
    except Exception:  # noqa: BLE001
        pass
    try:
        if "autopilot_status" in _H:
            ap = _H["autopilot_status"]() or {}
            bits.append(f"🤖 Autopilot: {'ON' if ap.get('enabled') else 'off'} · "
                        f"sent today {ap.get('sentToday', 0)}/{ap.get('cap', 0)}")
    except Exception:  # noqa: BLE001
        pass
    try:
        v = _H["do_today"].view()
        bits.append(f"☀️ Do Today: {v.get('doneCount', 0)}/{v.get('total', 0)} done")
    except Exception:  # noqa: BLE001
        pass
    send("📊 <b>Ops report</b>\n" + "\n".join(bits) if bits else "Nothing to report.")


def _clock(on, send):
    """Clock the agent crew OUT (pause) / IN (resume) / show status. The command or the
    button tap flips forge_ops; the gate then freezes all autonomous work while out.
    on=True clock out · on=False clock in · on=None just report status."""
    if "ops_status" not in _H:
        send("Clock isn't wired yet — try again in a moment.")
        return
    if on is not None and "ops_set" in _H:
        st = _H["ops_set"](on) or {}
    else:
        st = _H["ops_status"]() or {}
    crew = ", ".join(st.get("crew") or [])
    if st.get("paused"):
        body = ("🕐 <b>Agents clocked OUT</b>\n" + crew + " stood down — nothing "
                "autonomous runs. You've got the wheel; your own taps still work.")
        btns = [[{"text": "🟢 Clock agents back in", "callback_data": "opsresume:1"}]]
    else:
        body = ("🟢 <b>Agents clocked IN</b>\n" + crew + " back to work: sweeping, "
                "scoring, tagging, screening, prepping.")
        btns = [[{"text": "🕐 Clock agents out", "callback_data": "opspause:1"}]]
    _send_or_telegram(body, btns, send)


OPS_HELP = (
    "🕹 <b>Remote control</b>\n"
    "<code>/today</code> battle plan · <code>/done 3</code> check off\n"
    "<code>/hot</code> sellers waiting · <code>/sweep</code> Scout sweep now\n"
    "<code>/text name: msg</code> SMS a seller (confirm tap)\n"
    "<code>/screen name</code> Marcus screens · <code>/checkback name</code> nurture\n"
    "<code>/proposals</code> pending drafts · <code>/report</code> snapshot · <code>/find name</code>\n"
    "<code>/directives</code> Marcus surveys everything + issues orders\n"
    "<code>/prep name</code> Atlas's deal prep, anchors + call card\n"
    "<code>/autopilot on|off</code> auto-send re-engage bumps (capped, legit-checked, receipted)\n"
    "<code>/pause</code> clock agents OUT (you're working) · <code>/resume</code> clock them IN\n"
    "Plain English works too — “text arthur I can call at 3” or "
    "“move Christopher Giles to under contract and tag him motivated”."
)

_CMD_RE = re.compile(r"^/(today|done|hot|sweep|screen|find|text|send|checkback|"
                     r"proposals|report|directives|orders|ops|autopilot|prep|"
                     r"pause|resume|clockin|clockout|clock)\b\s*(.*)$", re.I | re.S)


# ── Claude natural-language intent (falls through to agent chat) ─────────────
_INTENT_SYS = (
    "You route an operator's Telegram message for a real-estate ops bot. Return ONE "
    "JSON object, nothing else. Actions:\n"
    '{"action":"text_seller","name":"<who>","message":"<sms text, written in a short '
    "casual friendly style>\"} — operator wants a message SENT to a seller/contact\n"
    '{"action":"screen","name":"<who>"} — screen/qualify/look into a seller\n'
    '{"action":"checkback","name":"<who>"} — send the nurture check-back\n'
    '{"action":"sweep"} — run scout sweep / check for new leads\n'
    '{"action":"today"} — show today\'s tasks/battle plan\n'
    '{"action":"done","item":"<number or name>"} — mark a today-task done\n'
    '{"action":"hot"} — hot sellers waiting\n'
    '{"action":"proposals"} — pending drafts to approve\n'
    '{"action":"report"} — ops status report\n'
    '{"action":"directives"} — Marcus surveys the operation and issues orders\n'
    '{"action":"find","name":"<who>"} — look up a contact\n'
    '{"action":"move_stage","contact":"<name or phone>","stage":"<stage name>",'
    '"tags":["<optional tag>"]} — move a contact/opportunity to a pipeline stage; '
    "include tags only if the operator also asked to tag them\n"
    '{"action":"tag","contact":"<name or phone>","tags":["<tag>",...],'
    '"op":"add|remove"} — add/remove internal GHL contact tags\n'
    '{"action":"chat"} — anything else: questions, analysis, conversation\n'
    "If the operator gives the gist of a message (e.g. 'tell arthur I can call at 3'), "
    "WRITE the actual SMS in message. When unsure, use chat."
)


def _intent(text):
    keyfn = _H.get("claude_key")
    key = keyfn() if keyfn else None
    if not key:
        return None
    try:
        import review_agent
        raw = review_agent._claude(key, _INTENT_SYS, text, max_tokens=300)
        m = re.search(r"\{.*\}", raw, re.S)
        return json.loads(m.group(0)) if m else None
    except Exception:  # noqa: BLE001
        return None


def _command_intent(text):
    return _rule_intent(text) or _intent(text)


# ── the router (called by telegram_io._handle_message) ───────────────────────
def route(text, chat_id, send):
    """True = consumed (an ops command ran). False = fall through to agent chat.
    send(text, buttons=None) replies in the same chat through the right bot."""
    command_text = text.strip()
    agent_prefix = re.match(r"^/(?:marcus|scout|atlas)\s+(.+)$", command_text, re.I | re.S)
    if agent_prefix:
        command_text = agent_prefix.group(1).strip()
    low = command_text.lower()

    # pending disambiguation: operator replied "1"/"2" to a which-one prompt
    sess = _SESS.get(chat_id) or {}
    pick = sess.get("pick")
    if pick and low.isdigit() and time.time() - pick.get("ts", 0) < 300:
        sess.pop("pick", None)
        idx = int(low) - 1
        matches = pick.get("matches") or []
        if 0 <= idx < len(matches):
            m = matches[idx]
            if pick.get("kind") == "text":
                tok = _queue_pending("sms", m["id"], m["name"], pick["message"])
                send(f"📤 <b>To {_esc(m['name'])}</b> ({_esc(m['phone'])}):\n"
                     f"“{_esc(pick['message'])}”\n\nSend it?",
                     [[{"text": "✅ Send", "callback_data": f"opsgo:{tok}"},
                       {"text": "❌ Cancel", "callback_data": f"opsno:{tok}"}]])
            elif pick.get("kind") in ("move_stage", "tag"):
                out = _handle_write_intent(pick.get("intent") or {}, chat_id=chat_id,
                                           send=send, source="telegram", selected=m)
                if out and out.get("reply") and not out.get("sent"):
                    send(out["reply"])
            else:
                send("That pending choice expired — start over.")
            return True
        send("Number didn't match — start over.")
        return True

    mt = _CMD_RE.match(command_text.strip())
    if mt:
        cmd, arg = mt.group(1).lower(), mt.group(2).strip()
        if cmd == "ops":
            send(OPS_HELP)
        elif cmd == "today":
            _do_today(chat_id, send)
        elif cmd == "done":
            _done(chat_id, arg, send)
        elif cmd == "hot":
            _hot(send)
        elif cmd == "sweep":
            _sweep(send)
        elif cmd == "screen":
            _screen(arg, send) if arg else send("Who? <code>/screen arthur</code>")
        elif cmd == "find":
            _find(arg, send) if arg else send("Who? <code>/find arthur</code>")
        elif cmd in ("text", "send"):
            name, _, msg = arg.partition(":")
            _text_seller(chat_id, name.strip(), msg.strip(), send)
        elif cmd == "checkback":
            _checkback(chat_id, arg, send) if arg else send("Who? <code>/checkback kenneth</code>")
        elif cmd == "proposals":
            _proposals(send)
        elif cmd == "report":
            _report(send)
        elif cmd in ("directives", "orders"):
            _directives(send)
        elif cmd == "prep":
            _prep(arg, send) if arg else send("Who? <code>/prep latasha</code>")
        elif cmd == "autopilot":
            _autopilot(arg, send)
        elif cmd in ("pause", "clockout"):
            _clock(True, send)
        elif cmd in ("resume", "clockin"):
            _clock(False, send)
        elif cmd == "clock":
            _clock(None, send)
        return True

    if command_text.startswith("/"):
        return False                      # /marcus, /scout etc. — not ours

    # plain English → Claude intent; "chat" falls through to the agent convo
    it = _command_intent(command_text)
    if not it or it.get("action") in (None, "chat"):
        return False
    a = it["action"]
    if a == "text_seller":
        _text_seller(chat_id, it.get("name") or "", it.get("message") or "", send)
    elif a == "screen":
        _screen(it.get("name") or "", send)
    elif a == "checkback":
        _checkback(chat_id, it.get("name") or "", send)
    elif a == "sweep":
        _sweep(send)
    elif a == "today":
        _do_today(chat_id, send)
    elif a == "done":
        _done(chat_id, str(it.get("item") or ""), send)
    elif a == "hot":
        _hot(send)
    elif a == "proposals":
        _proposals(send)
    elif a == "report":
        _report(send)
    elif a == "directives":
        _directives(send)
    elif a == "find":
        _find(it.get("name") or "", send)
    elif a in ("move_stage", "tag"):
        out = _handle_write_intent(it, chat_id=chat_id, send=send, source="telegram")
        if out and out.get("reply") and not out.get("sent"):
            send(out["reply"])
    else:
        return False
    return True
