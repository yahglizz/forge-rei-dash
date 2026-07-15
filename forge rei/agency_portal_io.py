"""agency_portal_io.py — the CLIENT-FACING edit-request portal (Forge AI Agency).

This is the thin, security-scoped layer that a client's browser talks to. A client
opens a link the operator shared — …/portal?c=<clientId>&k=<token> — and can:

  • see their own name + their own edit requests (status + history), and
  • submit a new edit request,

…without logging in, without a dashboard account, and without contacting the
operator. Every request they file lands in the SAME store the agency's admin
"Edit Requests" tab reads (agency_requests_io), pings Telegram for approval, and
can be handed to Dyson — end to end.

SECURITY MODEL (why this module is separate + tiny):
  • Bearer token scoped to ONE client (agency_io.verify_portal, compare_digest).
    A valid (clientId, token) unlocks ONLY that client's name + that client's own
    requests. It grants ZERO access to other clients, the CRM, or any dashboard API.
  • clientId + clientName on a submitted request are taken from the VERIFIED client
    record, never from the client's POST body — so a client cannot file under, or
    read, another client's account by editing the payload.
  • This module exposes exactly three verbs (bootstrap / submit / link). It is the
    only code the portal-only public listener (connector portal server) will route
    to. The main dashboard + its APIs stay on the private tailnet.

No store of its own — it composes agency_io (clients/tokens) + agency_requests_io
(the request store). Nothing here writes anything the admin side can't see.
"""
import agency_io
import agency_requests_io

# Types a client may pick in the portal. A deliberately friendlier, shorter subset
# of agency_requests_io.TYPES (the admin has the full list). Anything a client sends
# that is not in agency_requests_io.TYPES is coerced to "Other" by save_request.
CLIENT_TYPES = ["Website Edit", "New Page", "Content Update", "Bug Fix",
                "Design Change", "SEO", "Other"]
CLIENT_PRIORITIES = ["low", "medium", "high", "urgent"]

_MAX_TITLE = 160
_MAX_DETAIL = 4000


def bootstrap(cid, token):
    """Validate the client link and return everything the portal page renders.

    Returns {ok, clientId, clientName, business, requests:[...], types, priorities}
    or {error} on a bad/expired link. Never raises."""
    client = agency_io.verify_portal(cid, token)
    if not client:
        return {"error": "invalid or expired link"}
    reqs = agency_requests_io.list_for_client(client["id"]).get("requests", [])
    # Slim the requests to what a client should see (no internal source flag noise,
    # but keep status/history so they can track progress).
    shown = []
    for r in reqs:
        shown.append({
            "id": r.get("id"),
            "title": r.get("title"),
            "type": r.get("type"),
            "priority": r.get("priority"),
            "status": r.get("status"),
            "detail": r.get("detail"),
            "createdAt": r.get("createdAt"),
            "updatedAt": r.get("updatedAt"),
            "history": r.get("history") or [],
        })
    return {
        "ok": True,
        "clientId": client["id"],
        "clientName": client.get("name") or "",
        "business": client.get("business") or "",
        "site": client.get("site") or "",
        "requests": shown,
        "types": CLIENT_TYPES,
        "priorities": CLIENT_PRIORITIES,
    }


def submit(cid, token, payload):
    """Client files a new edit request. Validates the link, locks clientId +
    clientName from the verified record, and persists via agency_requests_io.

    Returns {ok, request} or {error}. Never raises."""
    client = agency_io.verify_portal(cid, token)
    if not client:
        return {"error": "invalid or expired link"}
    if not isinstance(payload, dict):
        return {"error": "request object required"}

    title = (payload.get("title") or "").strip()[:_MAX_TITLE]
    if not title:
        return {"error": "please add a short title"}
    detail = (payload.get("detail") or "").strip()[:_MAX_DETAIL]
    rtype = payload.get("type")
    if rtype not in agency_requests_io.TYPES:
        rtype = "Other"
    priority = payload.get("priority")
    if priority not in agency_requests_io.PRIORITIES:
        priority = "medium"

    # clientId + clientName come from the VERIFIED client, never the payload.
    return agency_requests_io.save_request({
        "clientId": client["id"],
        "clientName": client.get("name") or "(client)",
        "title": title,
        "type": rtype,
        "priority": priority,
        "detail": detail,
        "source": "portal",
    })


def link(cid, base=""):
    """Operator helper: ensure a token exists and return a shareable portal URL.

    base is the public origin the operator will send clients to (e.g.
    https://forge-reios.tail0a2dda.ts.net). With no base, returns a relative link."""
    tok = agency_io.ensure_portal_token(cid)
    if tok.get("error"):
        return tok
    prefix = (base or "").rstrip("/")
    url = f"{prefix}/portal?c={cid}&k={tok['portalToken']}"
    return {"ok": True, "clientId": cid, "name": tok.get("name") or "",
            "url": url, "portalToken": tok["portalToken"]}


def links_for_all(base=""):
    """Return a portal link for every client (minting tokens lazily). Powers the
    operator's 'Client portal links' panel."""
    out = []
    for c in agency_io.list_clients().get("clients", []):
        li = link(c["id"], base=base)
        if li.get("ok"):
            out.append({"clientId": c["id"], "name": c.get("name") or "",
                        "business": c.get("business") or "",
                        "url": li["url"]})
    return {"ok": True, "links": out, "count": len(out)}
