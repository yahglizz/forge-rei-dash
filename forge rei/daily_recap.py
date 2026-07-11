"""FORGE end-of-day recap — the evening "close the loops" pulse.

Companion to daily_brief. Once a day at the operator-set evening hour (box-local via
FORGE_TZ_OFFSET) the box pushes a Telegram recap: what's still open before you clock out —
hot leads not yet contacted, drafts still waiting on your tap, pipeline, appointments, and
today's spend. Morning brief starts the day; this closes it. Same scheduling shape as
daily_brief; the connector gathers the numbers and calls build_text(stats). Never raises.
"""
import json
import os
import time
from pathlib import Path

import forge_atomic

STATE = Path(__file__).resolve().parent / "marcus_state" / "daily_recap.json"

# ET by default (operator's zone). July = EDT (-4); set FORGE_TZ_OFFSET=-5 for EST.
_TZ_OFFSET_H = float(os.environ.get("FORGE_TZ_OFFSET", "-4") or -4)

# Evening send hour default 18:00 (6pm). Kept distinct from the morning brief's hour.
_DEFAULTS = {"enabled": True, "hour": 18, "lastSentDay": "", "lastSentAt": 0}


def _load():
    try:
        raw = json.loads(STATE.read_text())
    except Exception:
        raw = None
    d = dict(_DEFAULTS)
    if isinstance(raw, dict):
        d.update({k: raw.get(k, d[k]) for k in _DEFAULTS})
    try:
        d["hour"] = max(0, min(23, int(d["hour"])))
    except Exception:
        d["hour"] = 18
    d["enabled"] = bool(d["enabled"])
    return d


def _save(d):
    try:
        forge_atomic.atomic_write_json(STATE, d)
    except Exception:
        pass


def _local(now_ms=None):
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
    """True when it's past the evening send hour today and we haven't sent today's recap."""
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
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


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
    """Format the evening recap from the same flat stats dict the brief uses (the connector
    reuses _gather_brief_stats). Framed around what's still OPEN before clocking out. Pure."""
    stats = stats or {}
    lines = ["🌙 <b>FORGE end-of-day recap</b> — " + _esc(stats.get("date") or date_label())]
    lines.append("")

    def row(icon, label, val):
        if val is None:
            return
        lines.append(f"{icon} {label}: <b>{_esc(val)}</b>")

    # Open loops first — the whole point of the evening ping is "clear these before bed".
    hot = stats.get("hot")
    ap = stats.get("approvals")
    open_any = bool(hot) or bool(ap)
    if open_any:
        lines.append("<b>Still open</b>")
    if hot:
        row("\U0001f525", "Hot leads to text back", hot)
    if ap:
        row("✅", "Drafts waiting on your tap", ap)
    row("\U0001f4ac", "Conversations needing a reply", stats.get("replies"))

    # Where the pipeline stands tonight.
    if stats.get("openOpps") is not None:
        lines.append("")
        row("\U0001f4ca", "Pipeline", f"{stats.get('openOpps')} open · {_money(stats.get('pipelineValue'))}")
    if stats.get("appointments"):
        row("\U0001f4c5", "Appointments", stats.get("appointments"))

    top = stats.get("topLeads") or []
    if top:
        lines.append("")
        lines.append("<b>Don't let these go cold</b>")
        for l in top[:3]:
            name = _esc(l.get("name") or "(unknown)")
            last = (l.get("last") or "").strip().replace("\n", " ")
            snip = _esc(last[:60] + ("…" if len(last) > 60 else "")) if last else ""
            lines.append(f"• {name}" + (f" — “{snip}”" if snip else ""))

    spend = (stats.get("spendLine") or "").strip()
    if spend:
        lines.append("")
        lines.append("\U0001f4b8 " + _esc(spend) + " today")

    stale = stats.get("staleAgents") or []
    if stale:
        lines.append("")
        lines.append("⚠️ Stale agents: " + _esc(", ".join(stale)))

    lines.append("")
    if open_any:
        lines.append("Clear the open ones from your phone, then clock out. 🌙")
    else:
        lines.append("Nothing hanging — you're clear. Rest up. 🌙")
    return "\n".join(lines)
