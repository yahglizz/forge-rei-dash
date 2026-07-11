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
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


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


def build_text(stats):
    """Format the brief from a flat stats dict the connector assembles. Pure."""
    stats = stats or {}
    lines = ["☀️ <b>FORGE daily brief</b> — " + _esc(stats.get("date") or date_label())]
    lines.append("")

    def row(icon, label, val):
        if val is None:
            return
        lines.append(f"{icon} {label}: <b>{_esc(val)}</b>")

    hot = stats.get("hot")
    if hot is not None:
        warm = stats.get("warm")
        htxt = str(hot) + (f" hot · {warm} warm" if warm is not None else " hot")
        row("\U0001f525", "Leads", htxt)
    row("\U0001f4ac", "Replies waiting", stats.get("replies"))
    ap = stats.get("approvals")
    if ap:
        row("✅", "Drafts to approve", ap)
    pv = stats.get("pipelineValue")
    if stats.get("openOpps") is not None:
        row("\U0001f4ca", "Pipeline", f"{stats.get('openOpps')} open · {_money(pv)}")
    if stats.get("appointments"):
        row("\U0001f4c5", "Appointments", stats.get("appointments"))

    top = stats.get("topLeads") or []
    if top:
        lines.append("")
        lines.append("<b>Top hot leads</b>")
        for l in top[:3]:
            name = _esc(l.get("name") or "(unknown)")
            last = (l.get("last") or "").strip().replace("\n", " ")
            snip = _esc(last[:60] + ("…" if len(last) > 60 else "")) if last else ""
            lines.append(f"• {name}" + (f" — “{snip}”" if snip else ""))

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
