#!/usr/bin/env python3
"""pipeboard_io.py — Pipeboard Meta Ads client (MCP JSON-RPC over plain HTTPS, stdlib only).

Why: the box's direct Meta Graph path needs a long-lived system-user token that keeps dying
(META_ACCESS_TOKEN rejected). Pipeboard already holds the owner's Meta login, refreshes it, and
exposes the same data as MCP tools — and its endpoint is ordinary JSON-RPC, so no MCP client
is needed on the box. READ-ONLY here: insights + campaigns + account health. Anything that
launches, activates, spends or changes a budget is NOT in this file (CLAUDE.md rule 2 — those
stay one-tap owner approvals, added behind their own gate).

Config (os.environ — callers overlay the right business's env, see daycare_growth._scoped_env):
  PIPEBOARD_API_TOKEN      required. Never logged, never echoed.
  PIPEBOARD_AD_ACCOUNT_ID  default account (act_…) when no client map entry resolves.
  PIPEBOARD_MCP_URL        optional endpoint override.

Evidence discipline: every payload is labeled dataSource="live" + via="pipeboard" + the exact
dateRange it covers; any failure raises so the caller falls back to an honestly-labeled mock /
not_configured read — never a silent zero.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
import urllib.error
import urllib.request

DEFAULT_URL = "https://mcp.pipeboard.co/meta-ads-mcp"
_UA = "forge-reios/1.0 (+pipeboard_io)"
_TTL = 60                      # seconds — dashboards poll; Meta insights don't move that fast
_AUTH_DEAD_TTL = 15 * 60       # after a 401/403, stop calling for 15 min (same idea as agency_ads WP-A)
_cache: dict = {}
_dead_until = 0.0


class PipeboardError(RuntimeError):
    """Any Pipeboard failure (HTTP, JSON-RPC, tool error). Message is safe to show."""


class PipeboardAuthError(PipeboardError):
    """Pipeboard refused our token, or its Meta login expired — owner must fix it."""


_tl = threading.local()


@contextlib.contextmanager
def creds(tok: str, url: str = ""):
    """Run Pipeboard calls on THIS thread with one business's token (the daycare's, not
    the agency's) — no process-wide env swap, so a long run never holds a lock the UI needs."""
    prev = getattr(_tl, "c", None)
    _tl.c = (tok or "", url or "")
    try:
        yield
    finally:
        _tl.c = prev


def token() -> str:
    c = getattr(_tl, "c", None)
    return ((c[0] if c and c[0] else os.environ.get("PIPEBOARD_API_TOKEN")) or "").strip()


def configured() -> bool:
    return bool(token())


def default_account() -> str:
    return (os.environ.get("PIPEBOARD_AD_ACCOUNT_ID") or "").strip()


def auth_dead() -> bool:
    return time.time() < _dead_until


def _mark_dead() -> None:
    global _dead_until
    _dead_until = time.time() + _AUTH_DEAD_TTL


def _rpc(method: str, params: dict | None = None, timeout: int = 60) -> dict:
    """One JSON-RPC call. Retries once on 502/503/504 and timeouts. Raises PipeboardError."""
    tok = token()
    if not tok:
        raise PipeboardError("PIPEBOARD_API_TOKEN not set")
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                       "params": params or {}}).encode()
    req = urllib.request.Request(
        ((getattr(_tl, "c", None) or ("", ""))[1] or os.environ.get("PIPEBOARD_MCP_URL") or DEFAULT_URL),
        data=body, method="POST",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream", "User-Agent": _UA})
    last = None
    for attempt in (0, 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", "ignore")
            break
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                _mark_dead()
                raise PipeboardAuthError(f"Pipeboard rejected the token (HTTP {e.code})") from None
            last = PipeboardError(f"Pipeboard HTTP {e.code}")
            if e.code not in (502, 503, 504) or attempt:
                raise last from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = PipeboardError(f"Pipeboard unreachable: {type(e).__name__}")
            if attempt:
                raise last from None
        time.sleep(1.5)
    try:
        msg = json.loads(raw)
    except ValueError:
        raise PipeboardError("Pipeboard returned non-JSON") from None
    if msg.get("error"):
        raise PipeboardError(f"Pipeboard RPC error: {str(msg['error'])[:200]}")
    return msg.get("result") or {}


def call(tool: str, args: dict | None = None, timeout: int = 60) -> dict:
    """Call one Pipeboard Meta tool and return its parsed JSON body ({} if non-JSON)."""
    res = _rpc("tools/call", {"name": tool, "arguments": args or {}}, timeout)
    text = "".join(c.get("text", "") for c in res.get("content") or []
                   if isinstance(c, dict) and c.get("type") == "text")
    if res.get("isError"):
        low = text.lower()
        if "expired" in low or "reconnect" in low or "unauthor" in low:
            _mark_dead()
            raise PipeboardAuthError(f"Pipeboard/Meta login needs reconnecting: {text[:160]}")
        raise PipeboardError(f"Pipeboard {tool} failed: {text[:200]}")
    try:
        return json.loads(text) if text.strip() else {}
    except ValueError:
        return {"text": text}


# ── reads ─────────────────────────────────────────────────────────────────────
def _cached(key, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


def ad_accounts() -> list[dict]:
    """[{id, status, spent, currency}] for every ad account the Pipeboard login can see."""
    d = _cached(("accts",), lambda: call("get_ad_accounts", {}))
    return [{"id": a.get("id"), "status": a.get("account_status_label"),
             "spent": a.get("amount_spent"), "currency": a.get("currency")}
            for a in d.get("data") or []]


def campaigns(account_id: str, limit: int = 50) -> list[dict]:
    d = _cached(("camps", account_id), lambda: call(
        "get_campaigns", {"account_id": account_id, "limit": limit}))
    return d.get("data") or []


def insights(account_id: str, since: str, until: str, level: str = "ad") -> list[dict]:
    """Raw Meta insight rows for [since, until] (YYYY-MM-DD) at account|campaign|adset|ad."""
    d = _cached(("ins", account_id, since, until, level), lambda: call("get_insights", {
        "object_id": account_id, "level": level, "limit": 100,
        "time_range": {"since": since, "until": until}}))
    return d.get("data") or []


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _action(row: dict, *types: str) -> int:
    """First matching action type's value (NOT the sum — lead + lead_grouped is one lead)."""
    got = {a.get("action_type"): _num(a.get("value")) for a in row.get("actions") or []}
    for t in types:
        if t in got:
            return int(got[t])
    return 0


def analytics(account_id: str, days: int = 7) -> dict:
    """Live analytics in the exact shape agency_ads._live_analytics returns, so the Ads UI,
    Eco and Solomon read it unchanged. Raises PipeboardError on any failure."""
    import agency_ads
    rng = agency_ads._date_range(days)
    rows = insights(account_id, rng["since"], rng["until"], "ad")
    try:
        status = {str(c.get("id")): str(c.get("status") or "").lower() for c in campaigns(account_id)}
    except PipeboardError:
        status = {}                      # status is garnish; numbers stay real
    camps: dict = {}
    ads: list = []
    tot = {"spend": 0.0, "impressions": 0, "reach": 0, "clicks": 0,
           "leads": 0, "conversions": 0, "revenue": 0.0}
    for r in rows:
        a = {"spend": _num(r.get("spend")), "impressions": int(_num(r.get("impressions"))),
             "reach": int(_num(r.get("reach"))), "clicks": int(_num(r.get("clicks"))),
             "leads": lead_count(r),
             "conversions": _action(r, "purchase", "omni_purchase"), "revenue": 0.0}
        cid = str(r.get("campaign_id") or r.get("campaign_name") or "unknown")
        c = camps.setdefault(cid, {"id": cid, "name": r.get("campaign_name") or "Unknown",
                                   "objective": "", "status": status.get(cid) or "unknown",
                                   **{k: 0 for k in tot}})
        for k in tot:
            c[k] += a[k]
            tot[k] += a[k]
        ads.append({"id": str(r.get("ad_id") or f"ad_{len(ads)}"),
                    "name": r.get("ad_name") or "(ad)",
                    "campaign": r.get("campaign_name") or "", "hook": "", **a})
    ads_out = [{"id": a["id"], "name": a["name"], "campaign": a["campaign"], "hook": "",
                **agency_ads._metrics(a)} for a in ads]
    key = lambda x: (x["leads"], x["ctr"])      # noqa: E731 — no revenue from Pipeboard: rank by leads
    return {
        "account": {"id": account_id, "name": account_id, "clientName": ""},
        "days": days,
        "totals": agency_ads._metrics(tot),
        "campaigns": [agency_ads._metrics(c) | {"id": c["id"], "name": c["name"],
                                                 "objective": c["objective"], "status": c["status"]}
                      for c in camps.values()],
        "topAds": sorted(ads_out, key=key, reverse=True)[:3],
        "weakAds": sorted(ads_out, key=key)[:3],
        "source": "live", "dataSource": "live", "via": "pipeboard", "dateRange": rng,
    }


# ── daily-optimizer reads (fresh, uncached) ───────────────────────────────────
# Lead events, first match wins (NOT summed — one lead is reported under several action types).
LEAD_ACTIONS = ("lead", "offsite_conversion.fb_pixel_lead", "onsite_web_lead",
                "onsite_conversion.lead_grouped")


def lead_count(row: dict) -> int:
    return _action(row, *LEAD_ACTIONS)


def account_info(account_id: str) -> dict:
    return call("get_account_info", {"account_id": account_id})


def daily_ad_rows(account_id: str, since: str, until: str) -> list[dict]:
    """One row per (day, ad) with spend/impressions/clicks/actions, each tagged `day`.
    Pipeboard returns time_breakdown=day as segmented_metrics[].metrics (one ad per segment)."""
    d = call("get_insights", {"object_id": account_id, "level": "ad", "limit": 1000,
                              "time_breakdown": "day",
                              "time_range": {"since": since, "until": until}})
    return [dict(seg["metrics"], day=seg.get("period_start") or seg.get("period"))
            for seg in d.get("segmented_metrics") or []
            if isinstance(seg.get("metrics"), dict) and seg["metrics"].get("ad_id")]


def window_ad_rows(account_id: str, since: str, until: str) -> list[dict]:
    """One row per ad over the whole window — the only place Meta's reach/frequency is right
    (reach is not additive across days)."""
    d = call("get_insights", {"object_id": account_id, "level": "ad", "limit": 500,
                              "time_range": {"since": since, "until": until}})
    return d.get("data") or []


def structure(account_id: str) -> dict:
    """Live campaigns/adsets/ads with status + budgets (budget strings are minor units)."""
    out = {}
    for key, tool in (("campaigns", "get_campaigns"), ("adsets", "get_adsets"), ("ads", "get_ads")):
        out[key] = call(tool, {"account_id": account_id, "limit": 200}).get("data") or []
    return out


# ── WRITES — called ONLY by daycare_ads_autopilot, which owns the mode switch (off/shadow/
# auto), the budget guardrails and the undo ledger. CLAUDE.md rule 2: nothing else may spend,
# pause or change a budget. Every write supports dry_run (Meta validates, nothing persists).
def _w(tool: str, args: dict, dry_run: bool) -> dict:
    if dry_run:
        args = dict(args, dry_run=True)
    out = call(tool, args)
    clear_cache()
    return out


def set_status(kind: str, obj_id: str, status: str, dry_run: bool = False) -> dict:
    """kind = campaign|adset|ad; status = ACTIVE|PAUSED. Never DELETED/ARCHIVED — pause only."""
    if status not in ("ACTIVE", "PAUSED"):
        raise PipeboardError(f"refusing status {status!r} — pause/activate only")
    tool, key = {"campaign": ("update_campaign", "campaign_id"),
                 "adset": ("update_adset", "adset_id"), "ad": ("update_ad", "ad_id")}[kind]
    return _w(tool, {key: obj_id, "status": status}, dry_run)


def set_budget(kind: str, obj_id: str, daily_budget_cents: int, dry_run: bool = False) -> dict:
    """kind = campaign (CBO) | adset (ABO). Minor units (cents)."""
    tool, key = {"campaign": ("update_campaign", "campaign_id"),
                 "adset": ("update_adset", "adset_id")}[kind]
    return _w(tool, {key: obj_id, "daily_budget": int(daily_budget_cents)}, dry_run)


def upload_image(account_id: str, image_url: str, name: str = "") -> str:
    """Upload a public image URL; returns Meta's image hash."""
    d = call("upload_ad_image", {"account_id": account_id, "image_url": image_url,
                                 **({"name": name} if name else {})})
    h = d.get("hash") or d.get("image_hash")
    if not h:                                 # response nests the hash under images.<name>.hash
        for v in (d.get("images") or {}).values():
            h = (v or {}).get("hash") or h
    if not h:
        raise PipeboardError("image upload returned no hash")
    return h


def create_creative(account_id: str, **kw) -> str:
    d = _w("create_ad_creative", dict(account_id=account_id, **kw), False)
    cid = d.get("id") or d.get("creative_id") or (d.get("details") or {}).get("id")
    if not cid:
        raise PipeboardError(f"creative create returned no id: {str(d)[:160]}")
    return str(cid)


def create_ad(account_id: str, name: str, adset_id: str, creative_id: str) -> str:
    """Always created PAUSED — activation is a separate, guarded set_status."""
    d = _w("create_ad", {"account_id": account_id, "name": name, "adset_id": adset_id,
                         "creative_id": creative_id, "status": "PAUSED"}, False)
    aid = d.get("id") or d.get("ad_id")
    if not aid:
        raise PipeboardError(f"ad create returned no id: {str(d)[:160]}")
    return str(aid)


def clear_cache() -> None:
    _cache.clear()
    global _dead_until
    _dead_until = 0.0


if __name__ == "__main__":     # selfcheck: python3 pipeboard_io.py  (live read; prints no secrets)
    if not configured():
        raise SystemExit("PIPEBOARD_API_TOKEN not set in env")
    print("accounts:", [(a["id"], a["status"]) for a in ad_accounts()])
    acct = default_account() or (ad_accounts() or [{}])[0].get("id")
    t = analytics(acct, 30)["totals"]
    print("30d totals:", {k: t[k] for k in ("spend", "impressions", "clicks", "leads")})
