"""mission_control.py — the cross-business FRONT DOOR snapshot.

One read-only GET (`/api/mission-control`) assembles a light health + "what needs
attention" read for EVERY workspace (REI · Agency · Daycare · Dropship) plus the
fleet's background-loop health, so the operator's landing screen answers three
questions at a glance:

  1. Is everything running?           -> per-business + system status dot
  2. What's off / needs fixing?       -> ranked `attention` items per business
  3. Where do I jump to fix it?       -> every item + card carries a jump target
                                         {ws, page} the UI turns into a button

Design rules (match the rest of the box):
  * NEVER 500s. Every source is wrapped; a failing business degrades to
    status "unknown" with an error note instead of taking the whole snapshot down.
  * No Claude calls, no heavy work. Only cheap status reads + the health pings
    the health tabs already make. Safe to poll.
  * Additive + read-only. Touches nothing, proposes nothing, sends nothing.

The connector passes in its live agent instances (SCOUT/SOLOMON/MIDAS/SCREENER)
since those are stateful globals there; stateless module reads (agency, dropship,
approvals) are imported directly.
"""

import time

# Severity ranks for sorting attention items (worst first).
_SEV_RANK = {"down": 0, "warn": 1, "info": 2}
# Status -> display, worst-first ordering for the cards.
_STATUS_RANK = {"down": 0, "warn": 1, "unknown": 2, "idle": 3, "ok": 4}


def _now_ms():
    return int(time.time() * 1000)


def _archived():
    """Archived business ids from business_scope. Fails OPEN (nothing archived)."""
    try:
        import business_scope
        return business_scope.archived()
    except Exception:
        return set()


def _sort_attention(items):
    return sorted(items, key=lambda a: _SEV_RANK.get(a.get("sev"), 9))


def _worst(*statuses):
    """Return the worst status among the given (down > warn > unknown > idle > ok)."""
    present = [s for s in statuses if s]
    if not present:
        return "ok"
    return min(present, key=lambda s: _STATUS_RANK.get(s, 9))


# ---------------------------------------------------------------------------
# Per-business builders. Each returns a card dict and never raises — on failure
# it returns an "unknown" card carrying the error so the UI can show it.
# ---------------------------------------------------------------------------

def _card(bid, name, tag, accent, home_page):
    return {"id": bid, "name": name, "tag": tag, "accent": accent,
            "status": "ok", "statusLabel": "All good",
            "metrics": [], "attention": [], "jump": {"ws": bid, "page": home_page}}


def _tiles(card, source, fn):
    """Spec §15 tiles from ONE source. fn() builds the whole list before anything lands, so a
    failing/absent source drops all its tiles and adds ONE warn line — never a fake 0 (creed)."""
    try:
        card["metrics"].extend(fn())
    except Exception as e:  # noqa: BLE001
        card["attention"].append({"sev": "warn", "text": f"{source} unavailable: {str(e)[:90]}",
                                  "jump": card["jump"]})


def _dur(sec):
    if sec is None:
        return "—"   # no sample yet = Unknown, not 0
    sec = int(sec)
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m"
    return f"{sec / 3600:.1f}h"


# Wholesale CALL-producing Owner Actions sources (APPROVE-only sources skipped: no work).
_OWNER_CALL_SOURCES = ("scout_asap", "ace_callready", "screenings")
_LIVE_CONTRACT = ("sent", "delivered", "completed")


def _owner_calls(scout, screener):
    """Owner Actions' wholesale CALL count — same build() the list uses, so they can't drift."""
    import owner_actions
    if scout is None:
        raise RuntimeError("Scout not loaded")
    src = [s for s in owner_actions.SOURCES if s[0] in _OWNER_CALL_SOURCES]
    r = owner_actions.build({"scout": scout, "screener": screener}, sources=src)
    fix = [i for i in r["items"] if i["kind"] == "FIX"]
    if fix:
        raise RuntimeError(fix[0].get("why") or fix[0]["title"])
    return [{"label": "Owner calls required", "value": r["counts"]["CALL"],
             "jump": {"ws": "rei", "page": "Leads"}}]


def _deal_tiles():
    import deals
    rows = deals.list_deals()
    live = sum(1 for d in rows if d.get("contractStatus") in _LIVE_CONTRACT)
    return [{"label": "Contracts", "value": live, "jump": {"ws": "rei", "page": "Contracts"}},
            {"label": "Deals", "value": len(rows), "jump": {"ws": "rei", "page": "Pipeline"}}]


def _callsheet_tiles():
    import agency_callsheet
    n = agency_callsheet.list_leads()["counts"]
    j = {"ws": "agency", "page": "CallCenter"}
    return [{"label": "Calls ready", "value": n["new"], "jump": j},
            {"label": "Callbacks", "value": n["callback"], "jump": j},
            {"label": "Interested", "value": n["interested"], "jump": j}]


def _client_tiles():
    import agency_io
    s = agency_io.stats()
    j = {"ws": "agency", "page": "Clients"}
    return [{"label": "Clients", "value": s["activeClients"], "jump": j},
            {"label": "MRR", "value": f"${s['mrr']:,.0f}", "jump": j}]


def _lead_desk_tiles(card):
    """Solomon · Leads — the Lead Desk (saved state only; daycare_leads.view() never hits GHL)."""
    import daycare_leads
    v = daycare_leads.view()
    if not v.get("lastOkAt"):   # never swept OK → every count would be a fake 0
        raise RuntimeError(v.get("error") or "no successful sweep yet")
    k = v["kpis"]
    j = {"ws": "daycare", "page": "Dashboard"}
    tiles = [{"label": "New leads (7d)", "value": k["newLeads7d"]["total"], "jump": j},
             {"label": "Needs human", "value": k["needsHuman"], "jump": j},
             {"label": "Response time", "value": _dur(k.get("medianResponseSec")), "jump": j}]
    if v.get("error"):          # last good sweep still shown, but say it's stale
        card["attention"].append({"sev": "warn", "jump": j,
                                  "text": "Solomon · Leads: " + str(v["error"])[:100]})
    return tiles


def _agents_strip():
    """Agents strip from ONE registry() call (~2-13 ms, file/in-memory reads only).
    DISABLED (archived / switched off) rows are left out. Healthy = IDLE+RUNNING+WAITING."""
    try:
        import agents_hub
        rows = [a for a in agents_hub.registry() if a.get("status") != "DISABLED"]
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "warn": "Agent registry unavailable: " + str(e)[:90],
                "jump": {"view": "agents"}}
    n = {}
    for a in rows:
        n[a["status"]] = n.get(a["status"], 0) + 1
    return {"ok": True, "total": len(rows),
            "healthy": n.get("IDLE", 0) + n.get("RUNNING", 0) + n.get("WAITING FOR APPROVAL", 0),
            "running": n.get("RUNNING", 0), "failed": n.get("FAILED", 0),
            "degraded": n.get("DEGRADED", 0), "waiting": n.get("WAITING FOR APPROVAL", 0),
            "jump": {"view": "agents"}}


def _rei_card(scout, screener):
    c = _card("rei", "FORGE REI", "Wholesaling", "#4F7CFF", "Dashboard")
    try:
        s = scout.summary() if scout else {}
        counts = s.get("counts") or {}
        asap = int(counts.get("asap") or 0)
        warm = int(counts.get("warm") or 0)
        total = int(s.get("total") or 0)
        c["metrics"] = [
            {"label": "Hot leads", "value": asap, "jump": {"ws": "rei", "page": "Leads"}},
            {"label": "Warm", "value": warm, "jump": {"ws": "rei", "page": "Leads"}},
            {"label": "Active leads", "value": total, "jump": {"ws": "rei", "page": "Conversations"}},
        ]
        if s.get("lastError"):
            c["attention"].append({"sev": "down", "text": "Scout error: " + str(s["lastError"])[:120],
                                   "jump": {"ws": "rei", "page": "Agents"}})
        if not s.get("aiScoring"):
            c["attention"].append({"sev": "warn", "text": "Scout AI scoring off — no API key",
                                   "jump": {"ws": "rei", "page": "Agents"}})
        if asap:
            c["attention"].append({"sev": "info",
                                   "text": f"{asap} hot lead{'s' if asap != 1 else ''} waiting on a call",
                                   "jump": {"ws": "rei", "page": "Leads"}})
        # Screening queue — call-ready reports the operator hasn't cleared.
        try:
            q = screener.queue() if screener else {}
            pend = q.get("count")
            if pend is None:
                pend = len(q.get("queue") or q.get("reports") or [])
            if pend:
                c["metrics"].append({"label": "To screen", "value": pend,
                                     "jump": {"ws": "rei", "page": "Agents"}})
        except Exception:
            pass
    except Exception as e:
        return _fail(c, e)
    _tiles(c, "Owner Actions", lambda: _owner_calls(scout, screener))
    _tiles(c, "Deals", _deal_tiles)
    c["status"] = _status_from(c)
    return c


def _agency_card():
    c = _card("agency", "FORGE Agency", "ClientForge", "#8B5CF6", "Dashboard")
    _tiles(c, "Call Sheet", _callsheet_tiles)       # spec §15 tiles first
    _tiles(c, "Clients", _client_tiles)
    try:
        import agency_agents
        st = agency_agents.status() or {}
        agents = st.get("agents") or []
        online = sum(1 for a in agents if a.get("online"))
        open_tasks = sum(int(a.get("openTasks") or 0) for a in agents)
        c["metrics"] += [
            {"label": "Agents online", "value": f"{online}/{len(agents)}",
             "jump": {"ws": "agency", "page": "Agents"}},
            {"label": "Open tasks", "value": open_tasks, "jump": {"ws": "agency", "page": "Agents"}},
        ]
        if not st.get("connected"):
            c["attention"].append({"sev": "warn", "text": "Agency agents offline — no API key",
                                   "jump": {"ws": "agency", "page": "Settings"}})
        try:
            import agency_approvals_io
            aq = agency_approvals_io.list_queue("pending") or {}
            pend = int((aq.get("counts") or {}).get("pending") or len(aq.get("queue") or []))
            c["metrics"].append({"label": "Approvals", "value": pend,
                                 "jump": {"ws": "agency", "page": "Approvals"}})
            if pend:
                c["attention"].append({"sev": "info",
                                       "text": f"{pend} approval{'s' if pend != 1 else ''} waiting",
                                       "jump": {"ws": "agency", "page": "Approvals"}})
        except Exception:
            pass
    except Exception as e:
        return _fail(c, e)
    c["status"] = _status_from(c)
    return c


def _daycare_card(solomon):
    c = _card("daycare", "FORGE Daycare", "A Touch of Blessings", "#2DD4BF", "Dashboard")
    _tiles(c, "Solomon · Leads", lambda: _lead_desk_tiles(c))   # spec §15 tiles first
    try:
        st = solomon.status() if solomon else {}
        systems = st.get("systems") or []
        wired = sum(1 for s in systems if s.get("connected"))
        c["metrics"] += [
            {"label": "Systems wired", "value": f"{wired}/{len(systems)}" if systems else "—",
             "jump": {"ws": "daycare", "page": "Settings"}},
            {"label": "Director AI", "value": _ai_label(st.get("aiReady")),
             "jump": {"ws": "daycare", "page": "Agents"}},
        ]
        if not st.get("aiReady"):
            c["attention"].append({"sev": "warn", "text": "Solomon AI off — no API key",
                                   "jump": {"ws": "daycare", "page": "Settings"}})
        down = [s.get("name") for s in systems if not s.get("connected")]
        if down:
            c["attention"].append({"sev": "info",
                                   "text": "Not connected: " + ", ".join(str(x) for x in down[:4]),
                                   "jump": {"ws": "daycare", "page": "Settings"}})
    except Exception as e:
        return _fail(c, e)
    c["status"] = _status_from(c)
    return c


def _ai_label(ai_ready):
    """A key being present isn't the AI working — say Down while billing/auth is hard-down."""
    if not ai_ready:
        return "Off"
    try:
        import forge_heartbeat
        return "Down" if forge_heartbeat.ai_health().get("hard") else "Ready"
    except Exception:
        return "Ready"


def _dropship_card(midas):
    c = _card("dropship", "FORGE Dropship", "Shopify · AutoDS · Meta", "#F97316", "Dashboard")
    try:
        if midas:
            st = midas.status() or {}
            c["metrics"].append({"label": "Director AI", "value": _ai_label(st.get("aiReady")),
                                 "jump": {"ws": "dropship", "page": "Agents"}})
            if not st.get("aiReady"):
                c["attention"].append({"sev": "warn", "text": "Midas AI off — no API key",
                                       "jump": {"ws": "dropship", "page": "Settings"}})
        for mod, label, page in (("dropship_shopify", "Shopify", "Settings"),
                                 ("dropship_autods", "AutoDS", "Suppliers")):
            try:
                h = __import__(mod).health() or {}
                if not h.get("configured"):
                    val, sev = "Not set up", "info"
                elif h.get("connected"):
                    val, sev = "Live", None
                else:
                    val, sev = "Error", "down"
                c["metrics"].append({"label": label, "value": val,
                                     "jump": {"ws": "dropship", "page": page}})
                if sev == "down":
                    c["attention"].append({"sev": "down",
                                           "text": f"{label} connection failing: {str(h.get('error'))[:80]}",
                                           "jump": {"ws": "dropship", "page": page}})
                elif sev == "info":
                    c["attention"].append({"sev": "info", "text": f"{label} not connected yet",
                                           "jump": {"ws": "dropship", "page": page}})
            except Exception:
                pass
    except Exception as e:
        return _fail(c, e)
    c["status"] = _status_from(c)
    return c


def _fail(card, err):
    card["status"] = "unknown"
    card["statusLabel"] = "Can't read"
    card["attention"].append({"sev": "warn", "text": "Status unavailable: " + str(err)[:100],
                              "jump": card["jump"]})
    return card


def _status_from(card):
    """Roll a card's attention items into a single status + label."""
    sevs = [a.get("sev") for a in card.get("attention") or []]
    if "down" in sevs:
        card["statusLabel"] = "Needs a fix"
        return "down"
    if "warn" in sevs:
        card["statusLabel"] = "Check this"
        return "warn"
    if "info" in sevs:
        card["statusLabel"] = "Action waiting"  # info alone stays green
        return "ok"
    card["statusLabel"] = "All good"
    return "ok"


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------

def snapshot(scout=None, solomon=None, midas=None, screener=None, system=None):
    """Assemble the full front-door snapshot. `system` is the dict returned by
    the connector's api_system_health (passed in so we don't re-import loops)."""
    # Archived businesses (business_scope) get no card — and so no health pings
    # (Dropship's Shopify/AutoDS calls only happen inside its card builder).
    arch = _archived()
    builders = (("rei", lambda: _rei_card(scout, screener)),
                ("agency", _agency_card),
                ("daycare", lambda: _daycare_card(solomon)),
                ("dropship", lambda: _dropship_card(midas)))
    cards = [build() for bid, build in builders if bid not in arch]

    sysd = system or {}
    loops = sysd.get("loops") or []
    down = sum(1 for l in loops if l.get("status") == "red")
    stale = sum(1 for l in loops if l.get("stale"))
    healthy = sum(1 for l in loops if l.get("status") == "green")
    disk = sysd.get("disk") or {}
    active = bool(sysd.get("active"))
    paused = bool(sysd.get("paused"))

    system_card = {
        "active": active, "paused": paused,
        "loopsEnabled": bool(sysd.get("loopsEnabled")),
        "loopsDown": down, "loopsStale": stale, "loopsHealthy": healthy,
        "loopsTotal": len(loops),
        "diskPct": disk.get("pctUsed"),
        "telegram": bool(sysd.get("telegramConfigured")),
        "ok": bool(sysd.get("ok", True)),
        "reason": sysd.get("reason"),   # WP-A — why ok is false, one line
        "ai": sysd.get("ai"),           # WP-A — {ok, hard, kind, reason, downSince, ...}
        "jump": {"ws": "rei", "page": "SystemHealth"},
    }
    agents_strip = _agents_strip()
    # If the fleet is actively running and a loop is down, raise it on the REI card
    # too so it surfaces where the operator lives.
    if active and down:
        for c in cards:
            if c["id"] == "rei":
                c["attention"].insert(0, {
                    "sev": "down",
                    "text": f"{down} background loop{'s' if down != 1 else ''} down",
                    "jump": {"ws": "rei", "page": "SystemHealth"}})
                c["status"] = "down"
                c["statusLabel"] = "Needs a fix"

    for c in cards:
        c["attention"] = _sort_attention(c["attention"])

    total_attention = sum(len(c["attention"]) for c in cards)
    worst = _worst(*[c["status"] for c in cards])
    if active and not system_card["ok"]:
        worst = _worst(worst, "down")

    if not active:
        verdict = "CREW CLOCKED OUT" if (system_card["loopsEnabled"] and paused) else "UI ONLY — loops off"
        verdict_status = "idle"
    elif worst == "down":
        verdict = "NEEDS ATTENTION"
        verdict_status = "down"
    elif worst == "warn":
        verdict = "MINOR ITEMS TO CHECK"
        verdict_status = "warn"
    else:
        verdict = "ALL SYSTEMS GO"
        verdict_status = "ok"

    return {
        "ok": True,
        "verdict": verdict,
        "verdictStatus": verdict_status,
        "attentionCount": total_attention,
        "businesses": cards,
        "archived": sorted(arch),
        "system": system_card,
        "agents": agents_strip,     # spec §15 AGENTS: healthy/running/failed/waiting
        "generatedAt": _now_ms(),
    }
