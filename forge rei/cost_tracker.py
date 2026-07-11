"""cost_tracker.py — how much money the OS spends to run, per day and per month.

Three cost streams:
  1. AUTO — Claude API: both direct Anthropic call sites (`review_agent._claude` and
     `marcus_engine._ai_draft`) report token usage here after every response; tokens are
     stored raw and priced with the PRICES table so the math is recomputable.
  2. AUTO — GHL SMS: `sms_guard.record_success()` counts every outbound send; priced at a
     flat per-segment rate the operator can adjust (`smsRate`).
  3. MANUAL — fixed monthly services (DigitalOcean droplet, Telegram, anything flat):
     entered once via POST /api/cost/manual, prorated per day in the daily view.

Store mirrors ace.py: one small locked JSON (`marcus_state/cost_tracker.json`), atomic
writes, ET-day keys, best-effort everywhere — a cost-logging failure must NEVER break a
Claude call or an SMS send.
"""
import json
import threading
import time
from pathlib import Path

import forge_atomic

STATE = Path(__file__).resolve().parent / "marcus_state" / "cost_tracker.json"
_LOCK = threading.Lock()

_KEEP_DAYS = 92          # rolling window of per-day rows
_DEFAULT_SMS_RATE = 0.0083   # USD per outbound SMS segment (LC Phone default-ish; operator-tunable)

# USD per MILLION tokens, matched by substring on the model id (first hit wins).
# Raw tokens are stored per day, so editing this table re-prices history automatically.
PRICES = (
    ("fable", (10.0, 50.0)),
    ("mythos", (10.0, 50.0)),
    ("opus-4-1", (15.0, 75.0)),
    ("opus", (5.0, 25.0)),
    # Claude Sonnet 5 introductory API pricing is in effect through 2026-08-31.
    ("sonnet-5", (2.0, 10.0)),
    ("sonnet", (3.0, 15.0)),
    ("haiku", (1.0, 5.0)),
)
_DEFAULT_PRICE = (3.0, 15.0)


def _price_for(model):
    m = (model or "").lower()
    for frag, p in PRICES:
        if frag in m:
            return p
    return _DEFAULT_PRICE


def _today_key():
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    except Exception:
        return time.strftime("%Y-%m-%d")


def _load():
    try:
        d = json.loads(STATE.read_text())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(d):
    forge_atomic.atomic_write_json(STATE, d)


def _prune(d):
    days = d.setdefault("days", {})
    if len(days) > _KEEP_DAYS:
        for k in sorted(days)[:-_KEEP_DAYS]:
            days.pop(k, None)
    return d


def _day(d, key=None):
    return d.setdefault("days", {}).setdefault(
        key or _today_key(),
        {"claudeIn": 0, "claudeOut": 0, "claudeUSD": 0.0, "sms": 0})


# -- auto capture (called from review_agent / marcus_engine / sms_guard) ------------------

def record_anthropic(model, input_tokens, output_tokens):
    """Log one Claude API response's token usage. Best-effort — never raises."""
    try:
        i, o = int(input_tokens or 0), int(output_tokens or 0)
        if i <= 0 and o <= 0:
            return
        pin, pout = _price_for(model)
        usd = (i * pin + o * pout) / 1_000_000.0
        with _LOCK:
            d = _load()
            row = _day(d)
            row["claudeIn"] = int(row.get("claudeIn") or 0) + i
            row["claudeOut"] = int(row.get("claudeOut") or 0) + o
            row["claudeUSD"] = round(float(row.get("claudeUSD") or 0.0) + usd, 6)
            _save(_prune(d))
    except Exception:
        pass


def record_sms(n=1):
    """Count outbound SMS sends (called by sms_guard.record_success). Never raises."""
    try:
        with _LOCK:
            d = _load()
            row = _day(d)
            row["sms"] = int(row.get("sms") or 0) + int(n or 1)
            _save(_prune(d))
    except Exception:
        pass


# -- manual entries + settings -------------------------------------------------------------

def set_fixed(service, monthly_usd, note=""):
    """Add/update a flat monthly cost (droplet, Telegram, Retell...). monthly_usd<=0 removes."""
    service = (service or "").strip().lower()
    if not service:
        return {"error": "service name required"}
    try:
        amt = float(monthly_usd)
    except Exception:
        return {"error": "monthlyUSD must be a number"}
    with _LOCK:
        d = _load()
        fixed = d.setdefault("fixed", {})
        if amt <= 0:
            fixed.pop(service, None)
        else:
            fixed[service] = {"monthlyUSD": round(amt, 2), "note": str(note or "")[:120],
                              "updatedAt": int(time.time() * 1000)}
        _save(d)
    return status()


def set_settings(sms_rate=None, monthly_cap_usd=None):
    """Tune the per-SMS rate and/or the monthly spend-cap alert (0 = alert off)."""
    with _LOCK:
        d = _load()
        if sms_rate is not None:
            try:
                d["smsRate"] = max(0.0, float(sms_rate))
            except Exception:
                return {"error": "smsRate must be a number"}
        if monthly_cap_usd is not None:
            try:
                d["monthlyCapUSD"] = max(0.0, float(monthly_cap_usd))
            except Exception:
                return {"error": "monthlyCapUSD must be a number"}
        _save(d)
    return status()


# -- read API ------------------------------------------------------------------------------

def _row_usd(row, sms_rate):
    return round(float(row.get("claudeUSD") or 0.0)
                 + int(row.get("sms") or 0) * sms_rate, 4)


def status():
    """Everything the Cost card needs: today, month-to-date, trend, fixed, cap alert."""
    try:
        with _LOCK:
            d = _load()
        days = d.get("days") or {}
        fixed = d.get("fixed") or {}
        sms_rate = float(d.get("smsRate") or _DEFAULT_SMS_RATE)
        cap = float(d.get("monthlyCapUSD") or 0.0)
        today = _today_key()
        month = today[:7]
        fixed_monthly = round(sum(float(v.get("monthlyUSD") or 0) for v in fixed.values()), 2)

        trow = dict(days.get(today) or {})
        today_usage = _row_usd(trow, sms_rate)

        mtd_in = mtd_out = mtd_sms = 0
        mtd_claude_usd = 0.0
        for k, row in days.items():
            if not k.startswith(month):
                continue
            mtd_in += int(row.get("claudeIn") or 0)
            mtd_out += int(row.get("claudeOut") or 0)
            mtd_sms += int(row.get("sms") or 0)
            mtd_claude_usd += float(row.get("claudeUSD") or 0.0)
        mtd_sms_usd = round(mtd_sms * sms_rate, 4)
        day_of_month = int(today[-2:])
        # fixed costs prorated by how far into the month we are
        try:
            import calendar as _cal
            dim = _cal.monthrange(int(today[:4]), int(today[5:7]))[1]
        except Exception:
            dim = 30
        fixed_mtd = round(fixed_monthly * day_of_month / dim, 2)
        mtd_total = round(mtd_claude_usd + mtd_sms_usd + fixed_mtd, 2)

        trend = []
        for k in sorted(days)[-14:]:
            trend.append({"day": k, "usd": _row_usd(days[k], sms_rate)})

        alert = bool(cap and mtd_total >= cap)
        warn = bool(cap and not alert and mtd_total >= 0.8 * cap)
        return {
            "ok": True,
            "today": {"claudeIn": int(trow.get("claudeIn") or 0),
                      "claudeOut": int(trow.get("claudeOut") or 0),
                      "claudeUSD": round(float(trow.get("claudeUSD") or 0.0), 4),
                      "sms": int(trow.get("sms") or 0),
                      "usd": today_usage},
            "mtd": {"claudeIn": mtd_in, "claudeOut": mtd_out,
                    "claudeUSD": round(mtd_claude_usd, 4),
                    "sms": mtd_sms, "smsUSD": mtd_sms_usd,
                    "fixedUSD": fixed_mtd, "totalUSD": mtd_total},
            "fixed": fixed, "fixedMonthlyUSD": fixed_monthly,
            "smsRate": sms_rate, "monthlyCapUSD": cap,
            "capAlert": alert, "capWarn": warn,
            "trend": trend,
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "today": {}, "mtd": {}, "trend": []}


def digest_line():
    """One-line spend summary for the daily brief. Never raises."""
    try:
        s = status()
        m = s.get("mtd") or {}
        line = (f"Spend today ${s.get('today', {}).get('usd', 0):.2f} · "
                f"month ${m.get('totalUSD', 0):.2f}"
                f" (claude ${m.get('claudeUSD', 0):.2f} + sms ${m.get('smsUSD', 0):.2f}"
                f" + fixed ${m.get('fixedUSD', 0):.2f})")
        if s.get("capAlert"):
            line += f" — OVER the ${s.get('monthlyCapUSD'):.0f} cap"
        elif s.get("capWarn"):
            line += f" — 80% of the ${s.get('monthlyCapUSD'):.0f} cap"
        return line
    except Exception:
        return ""
