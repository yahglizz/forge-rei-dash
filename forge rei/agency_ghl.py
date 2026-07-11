"""agency_ghl.py — Forge AI Agency's GoHighLevel sub-account (separate from wholesale).

Takes a GHLClient configured from forge-agency/config/agency.env and exposes the
agency's own contacts / conversations / pipeline. Every function returns
{"connected": False} until the agency key is filled in, so the UI can show a clean
"connect your GHL" state instead of erroring. This module never touches the
wholesale account.
"""


def health(client):
    ok = bool(client and client.configured)
    return {
        "connected": ok,
        "locationId": client.location_id if ok else None,
        "version": client.version if client else None,
    }


def dashboard(client):
    if not (client and client.configured):
        return {"connected": False}
    out = {"connected": True, "locationId": client.location_id}
    try:
        c = client.get("/contacts/", {"locationId": client.location_id, "limit": 1})
        out["totalContacts"] = (c.get("meta", {}) or {}).get("total", 0)
    except Exception as e:  # noqa: BLE001
        out["totalContacts"] = 0
        out.setdefault("_errors", {})["contacts"] = str(e)
    try:
        cv = client.get("/conversations/search",
                        {"locationId": client.location_id, "limit": 100})
        convos = cv.get("conversations", []) or []
        out["totalConversations"] = cv.get("total", len(convos))
        out["unread"] = sum(1 for x in convos if (x.get("unreadCount") or 0) > 0)
    except Exception as e:  # noqa: BLE001
        out["totalConversations"] = 0
        out["unread"] = 0
        out.setdefault("_errors", {})["conversations"] = str(e)
    try:
        op = client.get("/opportunities/search",
                        {"location_id": client.location_id, "limit": 100})
        opps = op.get("opportunities", []) or []
        out["openOpportunities"] = sum(1 for o in opps if o.get("status") == "open")
        out["pipelineValue"] = sum(float(o.get("monetaryValue", 0) or 0)
                                   for o in opps if o.get("status") == "open")
    except Exception as e:  # noqa: BLE001
        out["openOpportunities"] = 0
        out["pipelineValue"] = 0
        out.setdefault("_errors", {})["opportunities"] = str(e)
    return out


def contacts(client, limit=50, query=None):
    if not (client and client.configured):
        return {"connected": False, "contacts": []}
    params = {"locationId": client.location_id, "limit": limit}
    if query:
        params["query"] = query
    data = client.get("/contacts/", params)
    out = []
    for c in data.get("contacts", []) or []:
        nm = f"{c.get('firstName') or ''} {c.get('lastName') or ''}".strip() or "(no name)"
        out.append({
            "id": c.get("id"), "name": nm, "phone": c.get("phone") or "",
            "email": c.get("email") or "", "tags": c.get("tags") or [],
            "dateAdded": c.get("dateAdded"),
        })
    meta = data.get("meta", {}) or {}
    return {"connected": True, "total": meta.get("total", len(out)),
            "count": len(out), "contacts": out}


# --- service tags -----------------------------------------------------------
# A client's signed services are mirrored into GHL as "signed: <service>" tags so
# the agency sub-account stays organized alongside the dashboard.
SERVICE_TAG_PREFIX = "signed: "


def service_tag(name):
    return SERVICE_TAG_PREFIX + (name or "").strip().lower()


def list_tags(client):
    if not (client and client.configured):
        return {"connected": False, "tags": []}
    try:
        d = client.get(f"/locations/{client.location_id}/tags")
        raw = d.get("tags", d) if isinstance(d, dict) else d
        names = [t.get("name") for t in raw if isinstance(t, dict)] if isinstance(raw, list) else []
        return {"connected": True, "tags": names}
    except Exception as e:  # noqa: BLE001
        return {"connected": True, "tags": [], "error": str(e)}


def ensure_service_tags(client, services):
    """Create the 'signed: <service>' tags in the GHL location if missing."""
    if not (client and client.configured):
        return {"connected": False}
    want = [service_tag(s) for s in (services or [])]
    have = set(t.lower() for t in list_tags(client).get("tags", []))
    created, existed, errors = [], [], {}
    for tag in want:
        if tag in have:
            existed.append(tag)
            continue
        try:
            client.post(f"/locations/{client.location_id}/tags", {"name": tag})
            created.append(tag)
        except Exception as e:  # noqa: BLE001
            errors[tag] = str(e)
    out = {"connected": True, "created": created, "existed": existed,
           "tags": want}
    if errors:
        out["errors"] = errors
    return out


def apply_contact_tags(client, contact_id, services):
    """Apply the 'signed: <service>' tags to a specific GHL contact."""
    if not (client and client.configured):
        return {"connected": False}
    if not contact_id:
        return {"connected": True, "applied": [], "note": "no GHL contact linked"}
    tags = [service_tag(s) for s in (services or [])]
    if not tags:
        return {"connected": True, "applied": []}
    try:
        client.post(f"/contacts/{contact_id}/tags", {"tags": tags})
        return {"connected": True, "applied": tags, "contactId": contact_id}
    except Exception as e:  # noqa: BLE001
        return {"connected": True, "applied": [], "error": str(e)}


def pipeline(client):
    if not (client and client.configured):
        return {"connected": False, "pipelines": []}
    pls = (client.get("/opportunities/pipelines",
                      {"locationId": client.location_id}).get("pipelines", []) or [])
    opps, sa, sai = [], None, None
    for _ in range(20):  # hard cap
        params = {"location_id": client.location_id, "limit": 100}
        if sa:
            params["startAfter"] = sa
            params["startAfterId"] = sai
        d = client.get("/opportunities/search", params)
        batch = d.get("opportunities", []) or []
        opps.extend(batch)
        meta = d.get("meta", {}) or {}
        if not batch or not meta.get("nextPage"):
            break
        sa = meta.get("startAfter")
        sai = meta.get("startAfterId")
    out = []
    for p in pls:
        stages = []
        for s in p.get("stages", []) or []:
            cards = [o for o in opps if o.get("pipelineStageId") == s.get("id")]
            stages.append({
                "id": s.get("id"), "name": s.get("name"), "count": len(cards),
                "value": sum(float(o.get("monetaryValue", 0) or 0) for o in cards),
            })
        out.append({"id": p.get("id"), "name": p.get("name"), "stages": stages,
                    "totalDeals": sum(st["count"] for st in stages)})
    return {"connected": True, "pipelines": out}
