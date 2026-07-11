"""autopilot.py — opt-in AUTOPILOT tier: auto-send ONLY the no-response re-engage bump.

DEFAULT OFF. The operator flips it on (/autopilot on). When on, the ONE class of outward
message it may auto-approve is the re-engage bump that followup.py drafts for a seller who
engaged and then went quiet — the lowest-risk routine touch that today just sits in the
approval inbox waiting on a tap. Everything else (first replies, nurture check-backs,
anything with numbers — PRICE/READY/HELP) stays tap-gated forever.

Safety stack on EVERY auto-send (all must pass, in order):
  1. enabled            — operator opt-in, persisted, default false
  2. reengage flag      — proposal["reengage"] is True (only followup-engine bumps)
  3. class allowlist    — classification NOT in DNC/PRICE/READY/HELP (those deserve YOU)
  4. send window        — 9am–8pm America/New_York, no late-night texts
  5. daily cap          — FORGE_AUTOPILOT_CAP (default 10) auto-sends per day
  6. ledger dedupe      — nothing touched this thread in the last 18h
  7. legit verdict      — legit_check says the thread is a real interested seller
Then marcus.approve() does the actual gated send (GHL SMS + send_ledger.record), the
draft having been voice-scrubbed, and the operator gets a Telegram receipt the moment
it happens. maybe_send() never raises.

State: marcus_state/autopilot.json {enabled, day, sentToday, log[:50]}.
"""
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import agent_bus
import forge_atomic
import forge_ops
import legit_check
import marcus_engine
import send_ledger
import telegram_io

STATE = Path(__file__).resolve().parent / "marcus_state" / "autopilot.json"
_LOCK = threading.Lock()

DAILY_CAP = int(os.environ.get("FORGE_AUTOPILOT_CAP", "10"))
SEND_START = 9              # no auto-sends before 9am ET
SEND_END = 20               # ...or after 8pm ET
LEDGER_HOURS = 18           # don't stack on any touch in the last 18h
# PRICE / READY / HELP threads deserve the operator personally; DNC never gets texted.
DENY_CLASSES = ("DNC", "PRICE", "READY", "HELP")


# ── state ─────────────────────────────────────────────────────────────────────
def _today():
    return time.strftime("%Y-%m-%d")


def _load():
    """Load state, rolling sentToday over to 0 on a new day. Call under _LOCK."""
    try:
        d = json.loads(STATE.read_text())
    except Exception:
        d = {}
    if not isinstance(d, dict):
        d = {}
    d.setdefault("enabled", False)
    d.setdefault("sentToday", 0)
    d.setdefault("log", [])
    if d.get("day") != _today():            # day rollover resets the cap counter
        d["day"] = _today()
        d["sentToday"] = 0
    return d


def _save(d):
    d["log"] = (d.get("log") or [])[:50]
    forge_atomic.atomic_write_json(STATE, d)


# ── public read/toggle ───────────────────────────────────────────────────────
def enabled():
    with _LOCK:
        return bool(_load().get("enabled"))


def set_enabled(on):
    with _LOCK:
        d = _load()
        d["enabled"] = bool(on)
        _save(d)
    try:        # best-effort broadcast so the Command Center + Telegram see the flip
        agent_bus.send("marcus", "all", "alert",
                       ("🤖 Autopilot ON — re-engage bumps will auto-send "
                        f"(cap {DAILY_CAP}/day, {SEND_START}am–{SEND_END - 12}pm ET, receipts on every send)."
                        if on else
                        "🤖 Autopilot OFF — every follow-up is back to tap-to-approve."),
                       {"type": "autopilot", "enabled": bool(on)})
    except Exception:
        pass
    return status()


def status():
    with _LOCK:
        d = _load()
        return {
            "enabled": bool(d.get("enabled")),
            "sentToday": int(d.get("sentToday") or 0),
            "cap": DAILY_CAP,
            "day": d.get("day"),
            "log": (d.get("log") or [])[:10],
        }


# ── gates ─────────────────────────────────────────────────────────────────────
def _within_hours():
    """True inside the 9am–8pm America/New_York send window (naive local fallback)."""
    try:
        from zoneinfo import ZoneInfo
        hr = datetime.now(ZoneInfo("America/New_York")).hour
    except Exception:
        hr = time.localtime().tm_hour
    return SEND_START <= hr < SEND_END


# ── the decision gate ────────────────────────────────────────────────────────
def maybe_send(marcus, scout, proposal):
    """Judge ONE pending proposal against the full safety stack; auto-approve only if
    every gate passes. Returns {"ok": True, ...} on an auto-send, else {"skipped": why}.
    Never raises — any error is a skip, the proposal stays in the approval inbox."""
    try:
        if not isinstance(proposal, dict) or not proposal.get("id"):
            return {"skipped": "no proposal"}
        pid = proposal["id"]
        conv_id = proposal.get("conversationId")
        name = proposal.get("name") or "(unknown)"

        # 1. operator opt-in (default OFF)
        if not enabled():
            return {"skipped": "autopilot off"}
        # 1b. crew clocked out — no autonomous sends while the operator is working
        if forge_ops.paused():
            return {"skipped": "clocked out"}
        # 2. ONLY the re-engage bump followup.py drafts — never first replies
        if proposal.get("reengage") is not True:
            return {"skipped": "not a re-engage bump"}
        # 3. classification allowlist — price/ready/help deserve the operator personally
        if proposal.get("classification") in DENY_CLASSES:
            return {"skipped": f"class {proposal.get('classification')} is operator-only"}
        # 4. send window
        if not _within_hours():
            return {"skipped": "outside 9am-8pm ET window"}
        # 5. daily cap
        with _LOCK:
            sent_today = int(_load().get("sentToday") or 0)
        if sent_today >= DAILY_CAP:
            return {"skipped": f"daily cap {DAILY_CAP} reached"}
        # 6. ledger dedupe — nothing else touched this thread recently
        if send_ledger.touched_within(conv_id, LEDGER_HOURS):
            return {"skipped": f"thread touched within {LEDGER_HOURS}h"}
        # 7. legit verdict on the actual thread (cached Claude judge)
        v = legit_check.verdict(scout, conv_id, name)
        if not (isinstance(v, dict) and v.get("legit")):
            why = (v or {}).get("reason") or "not legit"
            return {"skipped": f"legit_check: {why}"}

        # All gates passed — voice-scrub the draft and fire the same gated send a tap would.
        reply = proposal.get("suggestedReply") or ""
        try:
            reply = marcus_engine.MarcusEngine._scrub_voice(
                reply, seller_said=proposal.get("inbound") or "") or reply
        except Exception:
            pass
        proposal["autopilot"] = True
        proposal["autonomous"] = True
        res = marcus.approve(pid, reply) if reply else marcus.approve(pid)
        if not (isinstance(res, dict) and res.get("ok")):
            return {"skipped": f"approve failed: {(res or {}).get('error', '?')}"}

        with _LOCK:
            d = _load()
            d["sentToday"] = int(d.get("sentToday") or 0) + 1
            n = d["sentToday"]
            d.setdefault("log", []).insert(0, {
                "ts": int(time.time() * 1000),
                "name": name,
                "reply": reply[:160],
            })
            _save(d)

        # Receipt — the operator sees every auto-send the moment it happens (best-effort).
        try:
            telegram_io.send(
                f"🤖 Autopilot sent follow-up #{n}/{DAILY_CAP} to {name}:\n“{reply}”",
                dedupe_key=f"autopilot:{pid}")
        except Exception:
            pass
        try:
            agent_bus.send("marcus", "all", "alert",
                           f"🤖 Autopilot auto-sent follow-up #{n}/{DAILY_CAP} to {name}.",
                           {"type": "autopilot_send", "pid": pid, "convId": conv_id,
                            "name": name, "reply": reply})
        except Exception:
            pass
        return {"ok": True, "pid": pid, "name": name, "sentToday": n, "cap": DAILY_CAP}
    except Exception as e:  # noqa: BLE001 — autopilot must never break the cadence loop
        return {"skipped": f"error: {e}"}
