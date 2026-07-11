"""Tier 2 — work leads 24/7 instead of waiting on inbound.

Two gated cadences, run on their own slow loop. NOTHING auto-texts a seller — every touch
lands as a one-tap proposal in Marcus's approval inbox, or a flagged check-back the operator
sends with one click. The send-ledger keeps the loops from double-texting one thread.

1. No-response bump — a seller replied at least once, then we replied and they went quiet.
   At 24h / 72h / 7d (FORGE_FOLLOWUP_TIERS) we drop a gated, grounded re-engage draft via
   MARCUS.make_proposal_for(). Max 3 bumps, then we stop.

2. Due check-back — a screened "not ready" seller whose checkBackDays window elapsed. We flag
   the screening (checkBackDue) and ping the operator (bus -> Telegram) with the draft. The
   operator taps Send check-back (the existing gated nurture send). Up to 3 touches.
"""
import json
import os
import threading
import time
from pathlib import Path

import agent_bus
import autopilot
import forge_atomic
import forge_heartbeat
import forge_ops
import marcus_engine
import scout_triage
import send_ledger

STATE = Path(__file__).resolve().parent / "marcus_state" / "followup.json"
DAY_MS = 24 * 60 * 60 * 1000

INTERVAL = int(os.environ.get("FORGE_FOLLOWUP_INTERVAL", "1800"))          # 30 min
TIERS_H = [int(x) for x in os.environ.get("FORGE_FOLLOWUP_TIERS", "24,72,168").split(",") if x.strip()]
MAX_BUMPS = len(TIERS_H)
MAX_CHECKBACKS = int(os.environ.get("FORGE_CHECKBACK_MAX", "3"))
SCAN_LIMIT = int(os.environ.get("FORGE_FOLLOWUP_SCAN", "80"))              # convos scanned/sweep
BUMPS_PER_SWEEP = int(os.environ.get("FORGE_FOLLOWUP_PER_SWEEP", "8"))     # cap Claude drafts/sweep
QUIET_HOURS = 18                                                          # don't pile on a recent touch


class FollowupEngine:
    def __init__(self, scout, screener, marcus, ghl_get, location_id):
        self.scout = scout
        self.screener = screener
        self.marcus = marcus
        self.ghl_get = ghl_get
        self.location_id = location_id
        self.lock = threading.RLock()
        self.last_run = 0
        self.last_error = None
        loaded = self._load()
        self.state = loaded.get("state", {})        # convId -> {bumps, lastBumpAt}
        self.activity = loaded.get("activity", [])

    # -- persistence --------------------------------------------------------
    def _load(self):
        try:
            return json.loads(STATE.read_text())
        except Exception:
            return {}

    def _save(self):
        with self.lock:
            forge_atomic.atomic_write_json(STATE, {"state": self.state,
                                                   "activity": self.activity[:200],
                                                   "lastRun": self.last_run})

    def _log(self, kind, text):
        self.activity.insert(0, {"ts": int(time.time() * 1000), "kind": kind, "text": text})

    # -- public read --------------------------------------------------------
    def status(self):
        return {
            "lastRun": self.last_run,
            "lastError": self.last_error,
            "tracked": len(self.state),
            "tiersHours": TIERS_H,
            "maxBumps": MAX_BUMPS,
            "maxCheckbacks": MAX_CHECKBACKS,
            "activity": self.activity[:30],
        }

    # -- the loop -----------------------------------------------------------
    def run_cadence(self):
        if forge_ops.paused():            # clocked out — no follow-up drafting/sending
            return
        try:
            self._scan_no_response()
        except Exception as e:  # noqa: BLE001
            self.last_error = f"no_response: {e}"
        try:
            self._scan_due_checkbacks()
        except Exception as e:  # noqa: BLE001
            self.last_error = f"checkback: {e}"
        self.last_run = int(time.time() * 1000)
        self._save()

    def run_forever(self):
        # Let Scout/Marcus warm up first so the first sweep sees real state.
        time.sleep(min(120, INTERVAL))
        while True:
            try:
                self.run_cadence()
            except Exception as e:  # noqa: BLE001
                self.last_error = str(e)
            forge_heartbeat.beat("followup", INTERVAL, "Follow-up cadence",
                                 error=self.last_error)
            time.sleep(INTERVAL)

    # -- 1. no-response bumps ----------------------------------------------
    def _scan_no_response(self):
        data = self.ghl_get("/conversations/search", {
            "locationId": self.location_id, "limit": SCAN_LIMIT,
            "sortBy": "last_message_date"})
        convos = data.get("conversations", []) or []
        now = int(time.time() * 1000)
        made = 0
        for c in convos:
            if made >= BUMPS_PER_SWEEP:
                break
            cid, contact_id = c.get("id"), c.get("contactId")
            if not cid or not contact_id:
                continue
            # Ball's in our court only if WE spoke last (they went quiet on us).
            if c.get("lastMessageDirection") != "outbound":
                continue
            last_ms = scout_triage._to_ms(c.get("lastMessageDate")) or 0
            if not last_ms:
                continue
            age = now - last_ms
            if age < TIERS_H[0] * 3600 * 1000:
                continue                                # too fresh for even the first bump
            st = self.state.get(cid) or {"bumps": 0, "lastBumpAt": 0}
            bumps = st.get("bumps", 0)
            if bumps >= MAX_BUMPS:
                continue                                # exhausted the cadence
            if age < TIERS_H[bumps] * 3600 * 1000:
                continue                                # not due for the next tier yet
            if send_ledger.touched_within(cid, QUIET_HOURS):
                continue                                # something already texted them recently
            # Confirm a REAL engaged lead: the thread has a genuine seller inbound (not a
            # cold blast we sent into the void) and they didn't say no.
            seller_last = self._last_seller_msg(cid)
            if not seller_last:
                continue
            if (marcus_engine._is_hard_no(seller_last) or marcus_engine._is_soft_no(seller_last)
                    or marcus_engine.classify(seller_last) == "DNC"):
                continue
            hint = (f"No reply in ~{TIERS_H[bumps]}h. Send a short, warm, no-pressure bump that "
                    f"references what they said — not a generic 'just following up'.")
            res = self.marcus.make_proposal_for(cid, contact_id=contact_id,
                                                hint=hint, seller_said=seller_last)
            if isinstance(res, dict) and res.get("ok"):
                st["bumps"] = bumps + 1
                st["lastBumpAt"] = now
                self.state[cid] = st
                nm = c.get("contactName") or c.get("fullName") or contact_id
                self._log("bump", f"Queued follow-up #{st['bumps']} (~{TIERS_H[bumps]}h) for {nm}")
                made += 1
                # AUTOPILOT (opt-in, default OFF): only ever fires on the re-engage bumps
                # THIS engine just created — first replies and nurture check-backs stay
                # tap-gated. maybe_send re-checks the full safety stack and never raises;
                # on any skip the proposal simply stays in the approval inbox as before.
                try:
                    prop = next((p for p in self.marcus.proposals_list()
                                 if p.get("status") == "pending"
                                 and p.get("conversationId") == cid), None)
                    if prop:
                        ap = autopilot.maybe_send(self.marcus, self.scout, prop)
                        if isinstance(ap, dict) and ap.get("ok"):
                            self._log("autopilot",
                                      f"Autopilot auto-sent follow-up #{st['bumps']} to {nm} "
                                      f"({ap.get('sentToday')}/{ap.get('cap')} today)")
                except Exception:
                    pass
        if made:
            self._save()

    def _last_seller_msg(self, conv_id):
        if not self.scout:
            return None
        try:
            msgs = self.scout._thread_transcript(conv_id)  # oldest-first
        except Exception:
            return None
        for m in reversed(msgs or []):
            body = (m.get("body") or "").strip()
            if (m.get("direction") == "inbound"
                    and marcus_engine._is_seller_message(body)):
                return body
        return None

    # -- 2. due check-backs -------------------------------------------------
    def _scan_due_checkbacks(self):
        if not self.screener:
            return
        now = int(time.time() * 1000)
        flagged = 0
        for cid, r in list(self.screener.screenings.items()):
            rep = r.get("report") or {}
            if rep.get("interest") != "not_ready":
                continue
            cb = rep.get("checkBackDays")
            if not cb or not rep.get("nurtureDraft"):
                continue
            if (r.get("checkBackCount") or 0) >= MAX_CHECKBACKS:
                continue
            base = r.get("nurtureSentAt") or r.get("updatedAt") or 0
            if now < base + cb * DAY_MS:
                continue                                # window hasn't elapsed
            if r.get("checkBackDue"):
                continue                                # already flagged this cycle
            conv_id = r.get("convId")
            if conv_id and send_ledger.touched_within(conv_id, QUIET_HOURS):
                continue
            r["checkBackDue"] = True
            r["checkBackDueSince"] = now
            try:
                self.screener._save()
            except Exception:
                pass
            count = r.get("checkBackCount") or 0
            try:
                agent_bus.send("marcus", "all", "alert",
                    f"📅 Check-back due — {r.get('name')} (touch {count + 1}/{MAX_CHECKBACKS}). "
                    f"One tap to send your check-back.",
                    {"type": "checkback_due", "contactId": cid, "convId": conv_id,
                     "name": r.get("name"), "draft": rep.get("nurtureDraft")})
            except Exception:
                pass
            self._log("checkback", f"Check-back due for {r.get('name')} ({count + 1}/{MAX_CHECKBACKS})")
            flagged += 1
        if flagged:
            self._save()
