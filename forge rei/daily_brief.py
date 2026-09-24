"""FORGE daily ops brief — the "run it from anywhere" morning pulse.

Once a day (operator-set hour, box-local via FORGE_TZ_OFFSET) the box pushes a
Telegram digest of the whole operation: hot leads, replies waiting, drafts
awaiting approval, pipeline, appointments, spend. Telegram reaches the operator
ANYWHERE with no app/tunnel — so he wakes up already briefed. Also pullable on
demand (mobile More -> Daily brief -> "Send now" / preview).

This module owns scheduling + text formatting only. The connector gathers the
numbers (it has SCOUT/MARCUS/ghl/cost) and calls build_text(stats). Never raises.
"""
import json
import os
import time
from pathlib import Path

import forge_atomic

STATE = Path(__file__).resolve().parent / "marcus_state" / "daily_brief.json"

# ET by default (operator's zone). July = EDT (-4); set FORGE_TZ_OFFSET=-5 for EST.
_TZ_OFFSET_H = float(os.environ.get("FORGE_TZ_OFFSET", "-4") or -4)

_DEFAULTS = {"enabled": True, "hour": 8, "lastSentDay": "", "lastSentAt": 0}


def _load():
    try:
        raw = json.loads(STATE.read_text())
    except Exception:
        raw = None
    d = dict(_DEFAULTS)
    if isinstance(raw, dict):
        d.update({k: raw.get(k, d[k]) for k in _DEFAULTS})
    # sanitize
    try:
        d["hour"] = max(0, min(23, int(d["hour"])))
    except Exception:
        d["hour"] = 8
    d["enabled"] = bool(d["enabled"])
    return d


def _save(d):
    try:
        forge_atomic.atomic_write_json(STATE, d)
    except Exception:
        pass


def _local(now_ms=None):
    """struct_time in the operator's zone (box UTC + FORGE_TZ_OFFSET)."""
    secs = (now_ms / 1000.0) if now_ms else time.time()
    return time.gmtime(secs + _TZ_OFFSET_H * 3600.0)


def today_key(now_ms=None):
    return time.strftime("%Y-%m-%d", _local(now_ms))


def date_label(now_ms=None):
    return time.strftime("%a %b %-d", _local(now_ms))


def config():
    d = _load()
    d["tzOffset"] = _TZ_OFFSET_H
    d["localTime"] = time.strftime("%-I:%M %p", _local())
    return d


def set_config(enabled=None, hour=None):
    d = _load()
    if enabled is not None:
        d["enabled"] = bool(enabled)
    if hour is not None:
        try:
            d["hour"] = max(0, min(23, int(hour)))
        except (TypeError, ValueError):
            return {"error": "hour must be 0-23"}
    _save(d)
    out = config()
    out["ok"] = True
    return out


def due(now_ms=None):
    """True when it's past the send hour today and we haven't sent today's brief."""
    d = _load()
    if not d["enabled"]:
        return False
    lt = _local(now_ms)
    if lt.tm_hour < d["hour"]:
        return False
    return d["lastSentDay"] != today_key(now_ms)


def mark_sent(now_ms=None):
    d = _load()
    d["lastSentDay"] = today_key(now_ms)
    d["lastSentAt"] = int((now_ms or time.time() * 1000))
    _save(d)


def _esc(s):
    # Telegram send() uses parse_mode=HTML — escape the three special chars so a
    # seller snippet with & < > can't break the message.
    # None -> blank, but 0 is a real value and must render as "0".
    return (("" if s is None else str(s)).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _n(v):
    return v if isinstance(v, (int, float)) else 0


def _money(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "$0"
    if abs(x) >= 1e6:
        return "$" + ("%.1f" % (x / 1e6)).rstrip("0").rstrip(".") + "M"
    if abs(x) >= 1e4:
        return "$" + str(int(round(x / 1e3))) + "k"
    return "$" + format(int(round(x)), ",")


def archived(stats, biz):
    """True when the connector flagged this business archived (business_scope)."""
    return biz in ((stats or {}).get("archived") or ())


def _dur(sec):
    sec = int(sec)
    return f"{sec // 60}m" if sec < 3600 else f"{sec / 3600:.1f}h"


def business_sections(stats, open_loops=True):
    """AGENCY / WHOLESALE / DAYCARE / AGENTS blocks from the flat stats dict. Pure.

    A key the connector couldn't read is absent -> its line is omitted (never a fake 0);
    a block with no lines drops its header; an archived business is skipped entirely.
    open_loops=False leaves hot/replies/approvals out of WHOLESALE (the recap already
    lists them under "Still open")."""
    stats = stats or {}
    out = []

    def block(title, rows):
        rows = [r for r in rows if r]
        if rows:
            out.extend(["", f"<b>{title}</b>"] + rows)

    def r(label, val):
        return None if val is None else f"{label}: <b>{_esc(val)}</b>"

    ag = stats.get("agency") or {}
    if not archived(stats, "agency"):
        block("AGENCY", [r("\U0001f4de Ready to dial", ag.get("callsReady")),
                         r("\U0001f501 Callbacks", ag.get("callbacks")),
                         r("\U0001f91d Interested", ag.get("interested")),
                         r("\U0001f465 Clients", ag.get("clients")),
                         r("\U0001f4b0 MRR", _money(ag["mrr"]) if ag.get("mrr") is not None else None)])

    if not archived(stats, "wholesale"):
        rows = []
        if open_loops:
            hot = stats.get("hot")
            if hot is not None:
                warm = stats.get("warm")
                rows.append(r("\U0001f525 Leads",
                              str(hot) + (f" hot · {warm} warm" if warm is not None else " hot")))
            rows.append(r("\U0001f4ac Replies waiting", stats.get("replies")))
            if stats.get("approvals"):
                rows.append(r("✅ Drafts to approve", stats.get("approvals")))
        rows.append(r("\U0001f4de Owner calls required", stats.get("ownerCalls")))
        if stats.get("openOpps") is not None:
            rows.append(r("\U0001f4ca Pipeline",
                          f"{stats.get('openOpps')} open · {_money(stats.get('pipelineValue'))}"))
        if stats.get("appointments"):
            rows.append(r("\U0001f4c5 Appointments", stats.get("appointments")))
        block("WHOLESALE", rows)

    dc = stats.get("daycare") or {}
    if not archived(stats, "daycare"):
        med = dc.get("medianResponseSec")
        block("DAYCARE", [r("\U0001f476 New leads (7d)", dc.get("newLeads7d")),
                          r("\U0001f64b Need a human", dc.get("needsHuman")),
                          r("⏱ Median response", _dur(med) if isinstance(med, (int, float)) else None),
                          "⚠️ Last Solomon · Leads sweep failed — numbers are from the last good one"
                          if dc and dc.get("stale") else None])

    a = stats.get("agents")
    if isinstance(a, dict):
        block("AGENTS", [" · ".join(f"{a.get(k, 0)} {k}" for k in
                                    ("healthy", "running", "waiting approval", "degraded", "failed"))])
    return out


def owner_lines(items, n=5, skip_fix=False):
    """Numbered '[KIND] title' rows from the Owner Actions list. Pure."""
    rows = [i for i in (items or []) if not (skip_fix and i.get("kind") == "FIX")][:n]
    return [f"{k}. [{_esc(i.get('kind'))}] {_esc(i.get('title'))}" for k, i in enumerate(rows, 1)]


def build_text(stats):
    """Format the brief from a flat stats dict the connector assembles. Pure."""
    stats = stats or {}
    lines = ["☀️ <b>FORGE daily brief</b> — " + _esc(stats.get("date") or date_label())]
    lines += business_sections(stats)

    top = stats.get("topLeads") or []
    if top and not archived(stats, "wholesale"):
        lines.append("")
        lines.append("<b>Top hot leads</b>")
        for l in top[:3]:
            name = _esc(l.get("name") or "(unknown)")
            last = (l.get("last") or "").strip().replace("\n", " ")
            snip = _esc(last[:60] + ("…" if len(last) > 60 else "")) if last else ""
            lines.append(f"• {name}" + (f" — “{snip}”" if snip else ""))

    if stats.get("ownerItems") is not None:   # absent = Owner Actions unreadable → no section
        total = (stats.get("ownerCounts") or {}).get("total")
        lines.append("")
        lines.append("<b>OWNER TASKS</b>" + (f" — {total} total" if total else ""))
        lines += owner_lines(stats["ownerItems"]) or ["Nothing waiting on you."]

    spend = (stats.get("spendLine") or "").strip()
    if spend:
        lines.append("")
        lines.append("\U0001f4b8 " + _esc(spend))

    stale = stats.get("staleAgents") or []
    if stale:
        lines.append("")
        lines.append("⚠️ Stale agents: " + _esc(", ".join(stale)))

    lines.append("")
    lines.append("Open FORGE to reply to \U0001f525 leads and approve drafts.")
    return "\n".join(lines)
