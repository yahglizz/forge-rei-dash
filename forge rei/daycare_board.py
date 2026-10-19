"""daycare_board.py — Solomon's Command Board: the daycare's standing task list (state only).

One ranked list of items, each tied to evidence (spec 2026-10-18-solomon-daycare-orchestrator).
Written by daycare_watches.run_round (zero Claude) and by two internal, reversible routes
(POST /api/daycare/board/{snooze,done} — dashboard chat AUTO tier). This module never contacts
anyone and never writes Supabase / GHL / Gmail / Meta: it is one JSON file.

Item = {id, domain, key, title (≤120), why (≤240), evidence {source, window, fetchedAt}, center,
        owner solomon|owner, severity urgent|high|normal|low, state open|doing|waiting-tap|done|snoozed,
        due, firstSeen, lastSeen, seenCount, snoozeUntil, link {kind, ref}, closedBy, closedAt}
Rules (the creed): no evidence source + window → rejected, never shown. center is required
("unknown" allowed; 1923 A Mother's Touch is its own center — never merged). (domain, key) dedupes:
a persisting problem is ONE item that ages (firstSeen kept, seenCount++). A watch that FAILED never
closes its items (apply_round resolves only domains / key-prefixes that read OK). "Done" closes now,
but the next round reopens it while the source still shows the problem — Snooze is "not now".
State: marcus_state/daycare_board.json (FORGE_DAYCARE_BOARD overrides). Test: python3 test_daycare_board.py
"""
import hashlib
import json
import os
import threading
import time
from pathlib import Path

import forge_atomic

HERE = Path(__file__).resolve().parent
STATE = forge_atomic.guard_state_path(
    Path(os.environ.get("FORGE_DAYCARE_BOARD") or HERE / "marcus_state" / "daycare_board.json"))
_LOCK = threading.Lock()

DOMAINS = ("inbox", "enrollment", "billing", "ads", "social", "roster", "systems")
SEVERITIES = ("urgent", "high", "normal", "low")
STATES = ("open", "doing", "waiting-tap", "done", "snoozed")
ACTIVE = ("open", "doing", "waiting-tap")
OWNERS = ("solomon", "owner")
_RANK = {s: i for i, s in enumerate(SEVERITIES)}
KEEP_DONE_DAYS = 14          # closed items older than this are pruned on save
MAX_SNOOZE_H = 168           # a week — snooze is "not now", never "forever"
_DOT = {"urgent": "🔴", "high": "🟠", "normal": "🟡", "low": "⚪"}


def _ms(now=None):
    return int((time.time() if now is None else now) * 1000)


def item_id(domain, key):
    return hashlib.sha1(f"{domain}:{key}".encode()).hexdigest()[:12]


def _clip(s, n):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def _load():
    try:
        d = json.loads(STATE.read_text())
    except Exception:  # noqa: BLE001 — missing/corrupt = empty board
        d = {}
    if not isinstance(d, dict):
        d = {}
    if not isinstance(d.get("items"), dict):
        d["items"] = {}
    return d


def _save(d, now_ms):
    cut = now_ms - KEEP_DONE_DAYS * 86400 * 1000
    d["items"] = {k: v for k, v in d["items"].items()
                  if v.get("state") != "done" or (v.get("closedAt") or now_ms) >= cut}
    forge_atomic.atomic_write_json(STATE, d)


def validate(item):
    """-> (clean fields, None) or (None, reason). An item without source + window is Unknown,
    not a finding — rejected."""
    if not isinstance(item, dict):
        return None, "item must be an object"
    domain = item.get("domain")
    if domain not in DOMAINS:
        return None, f"domain must be one of {', '.join(DOMAINS)}"
    key = _clip(item.get("key"), 200)
    title = _clip(item.get("title"), 120)
    if not key or not title:
        return None, "key and title are required"
    ev = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    src, win = _clip(ev.get("source"), 120), _clip(ev.get("window"), 120)
    if not (src and win):
        return None, "evidence.source and evidence.window are required (no source + window = Unknown, not a finding)"
    center = _clip(item.get("center"), 60)
    if not center:
        return None, "center is required ('unknown' allowed)"
    sev, owner = item.get("severity") or "normal", item.get("owner") or "owner"
    if sev not in SEVERITIES:
        return None, f"severity must be one of {', '.join(SEVERITIES)}"
    if owner not in OWNERS:
        return None, "owner must be solomon or owner"
    link = item.get("link") if isinstance(item.get("link"), dict) else {}
    return {"domain": domain, "key": key, "title": title, "why": _clip(item.get("why"), 240),
            "evidence": {"source": src, "window": win, "fetchedAt": ev.get("fetchedAt")},
            "center": center, "owner": owner, "severity": sev, "due": item.get("due"),
            "link": ({"kind": _clip(link.get("kind"), 20), "ref": _clip(link.get("ref"), 120)}
                     if link.get("kind") and link.get("ref") else None)}, None


def _effective(it, now_ms):
    """A snooze that ran out reads as open."""
    if it.get("state") == "snoozed" and (it.get("snoozeUntil") or 0) <= now_ms:
        return "open"
    return it.get("state") or "open"


def _upsert(d, clean, now_ms):
    """-> (id, 'new' | 'reopened' | 'seen'). One item per (domain, key), ever."""
    iid = item_id(clean["domain"], clean["key"])
    cur = d["items"].get(iid)
    if cur is None:
        d["items"][iid] = dict(clean, id=iid, state="open", firstSeen=now_ms, lastSeen=now_ms,
                               seenCount=1, snoozeUntil=None, closedBy=None, closedAt=None)
        return iid, "new"
    change, seen = "seen", int(cur.get("seenCount") or 0) + 1
    if cur.get("state") == "done":
        if cur.get("closedBy") == "watch":     # the condition went away and came back: a fresh occurrence
            cur["firstSeen"], seen = now_ms, 1
        cur.update(state="open", closedBy=None, closedAt=None, reopenedAt=now_ms)
        change = "reopened"
    elif _effective(cur, now_ms) == "open" and cur.get("state") == "snoozed":
        cur.update(state="open", snoozeUntil=None)
    cur.update(clean, lastSeen=now_ms, seenCount=seen)
    return iid, change


def _resolve(d, domain, live_keys, prefixes, now_ms):
    """Close items of `domain` whose key is no longer live. prefixes (when given) limits the
    sweep to the key-prefixes whose source read OK. -> closed ids."""
    live, closed = set(live_keys or ()), []
    for iid, it in d["items"].items():
        key = str(it.get("key") or "")
        if it.get("domain") != domain or key in live:
            continue
        if prefixes is not None and not any(key.startswith(p) for p in prefixes):
            continue
        if it.get("state") == "done":
            it["closedBy"] = "watch"            # a marked-done item whose condition cleared
            continue
        it.update(state="done", closedBy="watch", closedAt=now_ms)
        closed.append(iid)
    return closed


def upsert(item, now=None):
    clean, why = validate(item)
    if why:
        return {"ok": False, "error": why}
    with _LOCK:
        d, n = _load(), _ms(now)
        iid, change = _upsert(d, clean, n)
        _save(d, n)
    return {"ok": True, "id": iid, "change": change}


def resolve_missing(domain, live_keys, prefixes=None, now=None):
    """Auto-close (state done, closedBy 'watch') the domain's items not in live_keys. Call it ONLY
    for a source that read OK — a failed read never becomes '0 problems'."""
    if domain not in DOMAINS:
        return {"ok": False, "error": "unknown domain"}
    with _LOCK:
        d, n = _load(), _ms(now)
        closed = _resolve(d, domain, live_keys, prefixes, n)
        _save(d, n)
    return {"ok": True, "closed": closed}


def _status_row(r, n_items, rejected, now_ms):
    st = r.get("status") or {}
    row = {"domain": r["domain"], "ok": bool(st.get("ok")), "items": n_items, "at": now_ms}
    for k in ("error", "notWired", "note"):
        if st.get(k):
            row[k] = st[k]
    if rejected:
        row["rejected"] = rejected
    return row


def apply_round(results, now=None, mail_desk=None):
    """One watch round in ONE load/save. results = [{domain, items, status {ok, error?, notWired?,
    sources? {key-prefix: ok}}}]. A domain is resolved only where it read OK: ok → the whole domain
    (unless `sources` names prefixes), ok:false → only its OK prefixes, none → nothing closed."""
    with _LOCK:
        d, n = _load(), _ms(now)
        new, closed, rows = [], [], []
        for r in results:
            st = r.get("status") or {}
            keys, rejected = [], 0
            for raw in r.get("items") or []:
                clean, why = validate(dict(raw, domain=r["domain"]))
                if why:
                    rejected += 1
                    continue
                iid, change = _upsert(d, clean, n)
                keys.append(clean["key"])
                if change != "seen":
                    new.append(iid)
            src = st.get("sources") if isinstance(st.get("sources"), dict) else None
            if src is not None:
                ok_pre = [p for p, ok in src.items() if ok]
                if ok_pre:
                    closed += _resolve(d, r["domain"], keys, ok_pre, n)
            elif st.get("ok"):
                closed += _resolve(d, r["domain"], keys, None, n)
            rows.append(_status_row(r, len(keys), rejected, n))
        d["sources"] = rows
        if mail_desk is not None:
            d["mailDesk"] = mail_desk
        active = [it for it in d["items"].values() if _effective(it, n) in ACTIVE]
        urgent = sorted((it for it in active if it.get("severity") == "urgent"), key=lambda i: i.get("firstSeen") or 0)
        failed = [x["domain"] for x in rows if not x["ok"]]
        line = (f"{len(active)} open ({len(urgent)} urgent) · {len(new)} new · {len(closed)} closed"
                + (f" · Unknown (read failed / not wired): {', '.join(failed)}" if failed else ""))
        d["lastRound"] = {"ranAt": n, "line": line, "open": len(active), "new": len(new), "closed": len(closed),
                          "failed": failed}
        _save(d, n)
        new_items = [_slim(it) for it in sorted((d["items"][i] for i in new if i in d["items"]),
                                                 key=lambda i: _RANK.get(i.get("severity"), 9))][:10]
    return {"new": new, "closed": closed, "domains": rows, "open": len(active),
            "urgent": [_slim(i) for i in urgent[:10]], "newItems": new_items, "line": line,
            "lastRound": d["lastRound"]}


def _slim(it):
    return {k: it.get(k) for k in ("id", "domain", "title", "severity", "center", "owner")}


def _find(d, iid):
    it = d["items"].get(str(iid or ""))
    return it if isinstance(it, dict) else None


def snooze(iid, hours=24, now=None):
    """Hide until `hours` from now (1..168). hours <= 0 = unsnooze (the undo of an AUTO snooze)."""
    try:
        hours = float(hours if hours is not None else 24)
    except (TypeError, ValueError):
        return {"ok": False, "error": "hours must be a number"}
    with _LOCK:
        d, n = _load(), _ms(now)
        it = _find(d, iid)
        if it is None:
            return {"ok": False, "error": f"no board item {str(iid)[:20]}"}
        if it.get("state") == "done":
            return {"ok": False, "error": "that item is already closed"}
        if hours <= 0:
            if it.get("state") == "snoozed":
                it.update(state="open", snoozeUntil=None)
        else:
            it.update(state="snoozed", snoozeUntil=n + int(min(max(hours, 1.0), MAX_SNOOZE_H) * 3600 * 1000))
        _save(d, n)
    return {"ok": True, "id": it["id"], "state": it["state"], "snoozeUntil": it.get("snoozeUntil")}


def last_round():
    return _load().get("lastRound") or {}


def done(iid, now=None):
    """Mark handled. Reversible by design: if the next round still sees the problem in its source,
    the item reopens (evidence beats the mark)."""
    with _LOCK:
        d, n = _load(), _ms(now)
        it = _find(d, iid)
        if it is None:
            return {"ok": False, "error": f"no board item {str(iid)[:20]}"}
        it.update(state="done", closedBy="marked", closedAt=n, snoozeUntil=None)
        _save(d, n)
    return {"ok": True, "id": it["id"], "state": "done",
            "note": "Closed. If the next round still sees it in its source, it reopens."}


def _int(v, default, lo, hi):
    try:
        return max(lo, min(int(v), hi))
    except (TypeError, ValueError):
        return default


def view(state="open", domain="", limit=50, now=None):
    """GET /api/daycare/board — state file only, no network. state = open (open|doing|waiting-tap,
    incl. expired snoozes) | all | one exact state."""
    n = _ms(now)
    d = _load()
    state = str(state or "open").strip().lower()
    domain = str(domain or "").strip().lower()
    limit = _int(limit, 50, 1, 200)
    rows = []
    for it in d["items"].values():
        eff = _effective(it, n)
        if state == "open" and eff not in ACTIVE:
            continue
        if state not in ("open", "all") and eff != state:
            continue
        if domain and it.get("domain") != domain:
            continue
        rows.append(dict(it, state=eff, ageSec=max(0, (n - (it.get("firstSeen") or n)) // 1000)))
    rows.sort(key=lambda i: (_RANK.get(i.get("severity"), 9), i.get("firstSeen") or 0))
    active = [it for it in d["items"].values() if _effective(it, n) in ACTIVE]
    by_dom, by_sev = {}, {}
    for it in active:
        by_dom[it.get("domain")] = by_dom.get(it.get("domain"), 0) + 1
        by_sev[it.get("severity")] = by_sev.get(it.get("severity"), 0) + 1
    shown = rows[:limit]
    mail = d.get("mailDesk")
    snoozed = sum(1 for it in d["items"].values() if _effective(it, n) == "snoozed")
    return {"ok": True, "items": shown, "count": len(rows), "state": state, "domain": domain or None,
            "counts": {"open": len(active), "byDomain": by_dom, "bySeverity": by_sev, "snoozed": snoozed},
            "lastRound": d.get("lastRound"), "sources": d.get("sources") or [], "mailDesk": mail,
            # email subjects / senders are third-party text: dash_live taints the chat turn on this
            "thirdPartyText": bool(shown) or bool((mail or {}).get("top")),   # fail closed: titles carry names / senders / lead text
            "fetchedAt": n}


def counts_block(now=None):
    """For Solomon's chat lanes block: counts only — no titles (mail subjects are third-party text
    and this lands in a system prompt). The items themselves: GET /api/daycare/board."""
    v = view(limit=1, now=now)
    lr = v.get("lastRound") or {}
    return {"open": v["counts"]["open"], "bySeverity": v["counts"]["bySeverity"],
            "byDomain": v["counts"]["byDomain"], "lastRoundAt": lr.get("ranAt"), "lastRound": lr.get("line"),
            "failedSources": [s.get("domain") for s in v.get("sources") or [] if not s.get("ok")],
            "read": "api_get /api/daycare/board (items); api_post /api/daycare/board/run (fresh round)"}


def brief_block(limit=10, now=None):
    """The board + mail summary for build_brief's live data (counts, top open items with evidence,
    failed sources; mail = counts + top-5 subjects only)."""
    v = view(limit=limit, now=now)
    mail = v.get("mailDesk") or {}
    return {"board": {"counts": v["counts"], "lastRound": v.get("lastRound"),
                      "failedSources": [{k: s.get(k) for k in ("domain", "error", "notWired")}
                                        for s in v.get("sources") or [] if not s.get("ok")],
                      "items": [{k: i.get(k) for k in ("domain", "title", "why", "severity", "center", "owner",
                                                       "evidence", "ageSec")} for i in v["items"]]},
            "mailDesk": ({k: mail.get(k) for k in ("window", "fetchedAt", "counts", "unread", "needsAnswer",
                                                    "filteredOut")}
                         | {"topUrgentSubjects": [t.get("subject") for t in (mail.get("urgent") or [])[:5]]}
                         if mail else None)}


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _age(sec):
    sec = int(sec or 0)
    return f"{sec // 60}m" if sec < 3600 else f"{sec // 3600}h" if sec < 172800 else f"{sec // 86400}d"


def telegram_text(v, top=8):
    """/board (zero Claude): the top open items + counts. HTML for telegram_io."""
    c = v.get("counts") or {}
    sev = c.get("bySeverity") or {}
    lines = [f"🏛️ <b>Solomon's board</b> — {c.get('open', 0)} open"
             + (f" (🔴 {sev['urgent']} urgent)" if sev.get("urgent") else "")]
    for i in (v.get("items") or [])[:top]:
        lines.append(f"{_DOT.get(i.get('severity'), '•')} {_esc(i.get('domain'))} · {_esc(i.get('title'))}"
                     f" · {_age(i.get('ageSec'))}")
    if not v.get("items"):
        lines.append("Nothing open.")
    lr = v.get("lastRound") or {}
    lines.append("Last round: " + (_esc(lr.get("line")) if lr else "none yet — Run round on the Daycare dashboard"))
    bad = [s for s in v.get("sources") or [] if not s.get("ok")]
    if bad:
        lines.append("⚠️ Unknown (not zero): " + ", ".join(_esc(s.get("domain")) for s in bad))
    return "\n".join(lines)


def board_digest_text(res, did=None):
    """Round-end digest for the DAYCARE Telegram chat (≤12 lines, zero Claude). `did` = action_digest
    'latest' rows for solomon (what he did himself); read from action_log when None."""
    if did is None:
        try:
            import action_digest
            did = ((action_digest.digest(24).get("agents") or {}).get("solomon") or {}).get("latest") or []
        except Exception:  # noqa: BLE001
            did = []
    urgent = res.get("urgent") or []
    lines = [f"🏛️ <b>Solomon · board round</b> — 🆕 {len(res.get('new') or [])} new · 🔴 {len(urgent)} urgent"
             f" · ✅ {len(res.get('closed') or [])} closed · {res.get('open', 0)} open"]
    seen = set()
    for i in urgent[:3] + (res.get("newItems") or [])[:6]:      # urgent first, then the rest of what's new
        if i.get("id") in seen or len(seen) >= 5:          # 1 + 5 + 1 + 4 + 1 = the 12-line cap
            continue
        seen.add(i.get("id"))
        title, center = str(i.get("title") or ""), str(i.get("center") or "")
        lines.append(f"{_DOT.get(i.get('severity'), '•')} {_esc(i.get('domain'))} · {_esc(title)}"
                     + (f" — {_esc(center)}" if center and center not in title else ""))
    bad = [r.get("domain") for r in res.get("domains") or [] if not r.get("ok")]
    if bad:
        lines.append("⚠️ Unknown (read failed / not wired): " + ", ".join(_esc(b) for b in bad))
    if did:
        lines.append("<b>What I did (24 h)</b>")
        for x in did[:3]:
            lines.append(("✅ " if x.get("ok") else "❌ ") + _esc(_clip(x.get("summary") or x.get("path"), 90)))
    lines.append("Board: Daycare → Dashboard · /board")
    return "\n".join(lines[:12])
