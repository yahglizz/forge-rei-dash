"""do_today.py — the operator's morning battle plan for FORGE REI OS.

Every morning at 9:00 AM Eastern the engine rebuilds a single checkable "Do Today"
list from what the agents already know, then emails it to the operator:

  - Text back  — Scout's ASAP bucket (hot sellers waiting on a reply)
  - Approve    — Marcus proposals sitting in the approval inbox
  - Call       — screened leads Marcus marked "interested" (call-ready reports)
  - Check-back — "not ready" sellers whose check-back window elapsed
  - Task       — GHL tasks due today (or overdue)

The dashboard reads /api/today and checks items off; done flags persist per-day in
marcus_state/do_today.json and survive the 9 AM rebuild (same task id = flag kept).
The email rides the existing GHL credentials (LeadConnector email to the operator's
own contact record) — no SMTP secrets needed.
"""
import hashlib
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import forge_atomic
import forge_heartbeat

try:
    from zoneinfo import ZoneInfo
except ImportError:          # very old python — fall back to server-local time
    ZoneInfo = None

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "do_today.json"

TZ_NAME = os.environ.get("FORGE_TODAY_TZ", "America/New_York")
RUN_HOUR = int(os.environ.get("FORGE_TODAY_HOUR", "9"))   # 9 AM Eastern
MAX_PER_KIND = int(os.environ.get("FORGE_TODAY_MAX", "10"))
MAX_TASKS = int(os.environ.get("FORGE_TODAY_CAP", "8"))   # STRICT: only today's real moves
GHOST_MAX = int(os.environ.get("FORGE_TODAY_GHOST", "12"))  # re-engage section (showed interest, went quiet)
CALL_FRESH_DAYS = 5                                       # screened-interested stays a call task this long

# Display metadata the frontend leans on. Priority orders the list (lower = higher).
KINDS = {
    "reply":     {"label": "Text back",  "priority": 1},
    "call":      {"label": "Call",       "priority": 2},
    "approve":   {"label": "Approve",    "priority": 3},
    "checkback": {"label": "Check-back", "priority": 4},
    "ghl":       {"label": "Task",       "priority": 5},
}


def _now_local():
    if ZoneInfo:
        try:
            return datetime.now(ZoneInfo(TZ_NAME))
        except Exception:
            pass
    return datetime.now()


def _today():
    return _now_local().strftime("%Y-%m-%d")


def _tid(kind, key):
    return hashlib.sha1(f"{kind}|{key}".encode()).hexdigest()[:10]


class DoTodayEngine:
    def __init__(self, scout, screener, marcus, ghl_get, ghl_post,
                 location_id, operator_email, ghl_tasks_fn=None):
        self.scout = scout
        self.screener = screener
        self.marcus = marcus
        self.ghl_get = ghl_get
        self.ghl_post = ghl_post
        self.location_id = location_id
        self.operator_email = (operator_email or "").strip()
        self.ghl_tasks_fn = ghl_tasks_fn
        self.lock = threading.RLock()
        self.last_error = None

    # -- persistence ---------------------------------------------------------
    def _load(self):
        try:
            import json
            return json.loads(STATE.read_text())
        except Exception:
            return {}

    def _save(self, d):
        forge_atomic.atomic_write_json(STATE, d)

    # -- collectors (each best-effort: one broken source never kills the list) -
    def _collect(self):
        tasks = []

        def safe(fn):
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                self.last_error = str(e)

        def add(kind, key, title, detail="", contact_id=None, conv_id=None):
            tasks.append({
                "id": _tid(kind, key), "kind": kind,
                "label": KINDS[kind]["label"], "priority": KINDS[kind]["priority"],
                "title": title, "detail": (detail or "")[:160],
                "contactId": contact_id, "convId": conv_id,
            })

        def scout_asap():
            import send_ledger
            leads = (self.scout.leads("asap") or {}).get("leads", []) if self.scout else []
            for l in leads[:MAX_PER_KIND]:
                # Scout's slim lead: id = convId, contactId = the GHL contact.
                conv = l.get("id")
                # Suppress if we already texted this thread back and the seller hasn't said
                # anything new since (thread lastMessageDate hasn't moved past our reply).
                try:
                    replied_at = send_ledger.last_reply_msg_date(conv)
                    lmd = int(l.get("lastMessageDate") or 0)
                    if replied_at and lmd and lmd <= replied_at:
                        continue
                except Exception:  # noqa: BLE001
                    pass
                add("reply", l.get("contactId") or conv,
                    f"Text back {l.get('name') or 'seller'}",
                    l.get("reason") or l.get("lastMessage"),
                    contact_id=l.get("contactId"), conv_id=conv)

        def marcus_pending():
            props = self.marcus.proposals_list() if self.marcus else []
            for p in props:
                if p.get("status") != "pending":
                    continue
                add("approve", p.get("contactId") or p.get("id"),
                    f"Review & send Marcus's draft to {p.get('name') or 'seller'}",
                    p.get("inbound"), contact_id=p.get("contactId"),
                    conv_id=p.get("conversationId"))

        def screenings():
            if not self.screener:
                return
            now = int(time.time() * 1000)
            fresh_ms = CALL_FRESH_DAYS * 24 * 3600 * 1000
            for cid, r in list(self.screener.screenings.items()):
                rep = r.get("report") or {}
                name = r.get("name") or "seller"
                if r.get("checkBackDue"):
                    add("checkback", cid, f"Send check-back to {name}",
                        rep.get("nurtureDraft"), contact_id=cid, conv_id=r.get("convId"))
                elif (rep.get("interest") == "interested"
                        and now - (r.get("updatedAt") or 0) < fresh_ms):
                    score = rep.get("score")          # Marcus scores 1-10
                    detail = rep.get("summary") or rep.get("notes") or ""
                    dp = getattr(self, "deal_prep", None)
                    if dp is not None:                 # Atlas's anchors arm the call
                        try:
                            a = ((dp.get(cid) or {}).get("prep") or {}).get("anchors") or {}
                            if a.get("opening"):
                                detail = (f"anchors ${a['opening']:,.0f} open / "
                                          f"${a.get('target', 0):,.0f} target / "
                                          f"${a.get('walkaway', 0):,.0f} walk · " + detail)
                        except Exception:  # noqa: BLE001
                            pass
                    add("call", cid,
                        f"Call {name}" + (f" — screened {score}/10, interested" if score else " — screened & interested"),
                        detail,
                        contact_id=cid, conv_id=r.get("convId"))

        def ace_callready():
            # ACE P4: leads the autonomous engine fully qualified — the operator's ONLY
            # job on these is the phone call. De-duped by contact in the pass below.
            try:
                import ace
                for row in (ace.call_ready_list().get("callReady") or []):
                    if row.get("ackAt"):
                        continue          # already acknowledged — it's in his hands
                    detail = ""
                    a = row.get("anchors") or {}
                    if a.get("opening"):
                        detail = (f"anchors ${a['opening']:,.0f} open / "
                                  f"${a.get('target', 0):,.0f} target / "
                                  f"${a.get('walkaway', 0):,.0f} walk · ")
                    if row.get("askingPrice"):
                        detail += f"seller asked {row.get('askingPrice')}"
                    add("call", row.get("contactId") or row.get("convId"),
                        f"Call {row.get('name') or 'seller'} — ACE qualified, call-ready",
                        detail, contact_id=row.get("contactId"), conv_id=row.get("convId"))
            except Exception:  # noqa: BLE001
                pass

        def ghl_due():
            if not self.ghl_tasks_fn:
                return
            today = _today()
            for t in (self.ghl_tasks_fn() or {}).get("tasks", []):
                if t.get("completed"):
                    continue
                due = (t.get("dueDate") or "")[:10]
                if not due or due > today:
                    continue                       # only due today or overdue
                who = t.get("contactName") or ""
                add("ghl", t.get("id"), t.get("title") + (f" — {who}" if who else ""),
                    t.get("body"), contact_id=t.get("contactId"))

        safe(scout_asap)
        safe(marcus_pending)
        safe(screenings)
        safe(ace_callready)
        safe(ghl_due)

        # One row per contact: a hot seller shouldn't show as both "text back" and
        # "call" — keep the highest-priority touch.
        tasks.sort(key=lambda t: (t["priority"], t["title"]))
        seen, out = set(), []
        for t in tasks:
            k = t.get("contactId") or t["id"]
            if k in seen:
                continue
            seen.add(k)
            out.append(t)
        return self._route(out)

    def _route(self, tasks):
        """STRICT split. The operator's own contact never makes the list. Every seller-touch
        task is judged by a READ-THE-THREAD verdict (legit_check, which reads the actual SMS
        thread via Claude) and routed by URGENCY:
          - urgency 'high' (act-today: engaged now, asked offer, gave price, negotiating,
            agreed to talk) → the strict MAIN list.
          - legit but 'medium/low' (showed real interest then went quiet/ghosted) → the
            separate RE-ENGAGE list, so they're not lost but don't clutter today's moves.
          - not legit → dropped entirely.
        Ready Marcus drafts (approve) + GHL tasks due today are today-moves by nature → main.
        No key → gate off, everything lands in main (degrade to old behavior)."""
        try:
            import legit_check
        except Exception:  # noqa: BLE001
            return {"today": tasks[:MAX_TASKS], "ghost": []}
        me = (self.operator_email or "").split("@")[0].lower()
        today, ghost = [], []
        for t in tasks:
            title_l = (t.get("title") or "").lower()
            if me and me in title_l:                 # don't tell me to text myself
                continue
            if t["kind"] in ("reply", "call", "checkback") and t.get("convId"):
                v = legit_check.verdict(self.scout, t.get("convId"), t.get("title"))
                if not v.get("legit"):
                    continue                          # not important — drop it
                if v.get("reason") and not t.get("detail"):
                    t["detail"] = v["reason"][:160]
                if (v.get("urgency") or "high") == "high":
                    today.append(t)
                else:
                    t["ghost"] = True
                    t["urgency"] = v.get("urgency")
                    ghost.append(t)
            else:                                     # approve (ready draft) / ghl (due today)
                today.append(t)
        return {"today": today[:MAX_TASKS], "ghost": ghost[:GHOST_MAX]}

    # -- build / view / check --------------------------------------------------
    def build(self, email=False):
        with self.lock:
            d = self._load()
            same_day = d.get("date") == _today()
            prev = {}
            if same_day:
                for t in (d.get("tasks", []) + d.get("ghost", [])):
                    prev[t["id"]] = t
            coll = self._collect()          # {"today": [...], "ghost": [...]}
            for lst in (coll["today"], coll["ghost"]):
                for t in lst:
                    old = prev.get(t["id"])
                    if old and old.get("done"):
                        t["done"], t["doneAt"] = True, old.get("doneAt")
            d = {"date": _today(), "generatedAt": int(time.time() * 1000),
                 "emailedAt": d.get("emailedAt") if same_day else None,
                 "tasks": coll["today"], "ghost": coll["ghost"]}
            self._save(d)
        if email:
            self._email_digest(d)
        return self.view()

    def view(self):
        with self.lock:
            d = self._load()
            if d.get("date") != _today() or "tasks" not in d:
                return self.build(email=False)
            tasks = d.get("tasks", [])
            ghost = d.get("ghost", [])
            return {"date": d.get("date"), "generatedAt": d.get("generatedAt"),
                    "emailedAt": d.get("emailedAt"), "lastError": self.last_error,
                    "emailTo": self.operator_email or None,
                    "doneCount": sum(1 for t in tasks if t.get("done")),
                    "total": len(tasks), "tasks": tasks,
                    "ghost": ghost, "ghostCount": len(ghost),
                    "autonomy": self._autonomy_digest()}

    @staticmethod
    def _autonomy_digest():
        """ACE P5 + cost: one small block riding the daily view/digest — what the
        autonomous engine did today and what the OS spent. Best-effort, never raises."""
        out = {}
        try:
            import ace
            out = ace.digest(days=1)
        except Exception:  # noqa: BLE001
            out = {}
        try:
            import cost_tracker
            out["costLine"] = cost_tracker.digest_line()
        except Exception:  # noqa: BLE001
            pass
        return out

    def mark_texted(self, contact_id):
        """Speed-to-Lead sent a reply → check off every task for this contact on today's
        list (main + ghost). Returns True if anything was marked. The send-ledger suppression
        keeps it off future rebuilds until the seller replies again."""
        if not contact_id:
            return False
        found = False
        with self.lock:
            d = self._load()
            for t in (d.get("tasks", []) + d.get("ghost", [])):
                if t.get("contactId") == contact_id and not t.get("done"):
                    t["done"], t["doneAt"], t["texted"] = True, int(time.time() * 1000), True
                    found = True
            if found:
                self._save(d)
        return found

    def check(self, task_id, done=True):
        with self.lock:
            d = self._load()
            for t in (d.get("tasks", []) + d.get("ghost", [])):
                if t["id"] == task_id:
                    t["done"] = bool(done)
                    t["doneAt"] = int(time.time() * 1000) if done else None
                    self._save(d)
                    break
        return self.view()

    # -- the 9 AM email ---------------------------------------------------------
    def _operator_contact_id(self):
        """Find-or-create the operator's own GHL contact (email digests ride GHL's
        LeadConnector email — no SMTP secrets on the box)."""
        res = self.ghl_post("/contacts/upsert", {
            "locationId": self.location_id, "email": self.operator_email,
            "firstName": "Yahjair", "lastName": "(Operator)",
            "source": "forge-do-today"})
        c = res.get("contact") or res
        return c.get("id")

    def _email_digest(self, d):
        if not self.operator_email:
            self.last_error = "no GHL_USER_EMAIL in ghl.env — digest email skipped"
            return
        try:
            cid = self._operator_contact_id()
            if not cid:
                raise RuntimeError("could not upsert operator contact")
            # Email rides a conversation, same as every other GHL message.
            convs = self.ghl_get("/conversations/search",
                                 {"locationId": self.location_id, "contactId": cid})
            clist = convs.get("conversations", []) or []
            if clist:
                conv_id = clist[0]["id"]
            else:
                new = self.ghl_post("/conversations/",
                                    {"locationId": self.location_id, "contactId": cid})
                conv_id = (new.get("conversation", {}) or {}).get("id") or new.get("id")
            tasks = d.get("tasks", [])
            ghost = d.get("ghost", [])
            nice = _now_local().strftime("%A, %B %-d")
            payload = {
                "type": "Email", "contactId": cid,
                "subject": f"DO TODAY — {len(tasks)} moves · {nice}",
                "emailTo": self.operator_email,
                "html": self._digest_html(tasks, nice, ghost),
            }
            if conv_id:
                payload["conversationId"] = conv_id
            self.ghl_post("/conversations/messages", payload)
            with self.lock:
                cur = self._load()
                cur["emailedAt"] = int(time.time() * 1000)
                self._save(cur)
            self.last_error = None
        except Exception as e:  # noqa: BLE001
            self.last_error = f"email: {e}"
        # Belt-and-suspenders: same digest hits Telegram via the bus.
        try:
            import agent_bus
            top = "\n".join(f"• {t['label']}: {t['title']}" for t in d.get("tasks", [])[:8])
            gn = len(d.get("ghost", []))
            tail = f"\n(+{gn} went-ghost leads to re-engage)" if gn else ""
            agent_bus.send("marcus", "all", "alert",
                           f"☀️ DO TODAY — {len(d.get('tasks', []))} moves on the board:\n{top}{tail}",
                           {"type": "do_today"})
        except Exception:
            pass

    def _rows_html(self, tasks):
        colors = {"reply": "#EF4444", "call": "#22C55E", "approve": "#4F7CFF",
                  "checkback": "#F59E0B", "ghl": "#8B5CF6"}
        rows = []
        for t in tasks:
            c = colors.get(t["kind"], "#4F7CFF")
            detail = f"<div style='color:#94A3B8;font-size:12px;margin-top:2px'>{t['detail']}</div>" if t.get("detail") else ""
            rows.append(
                f"<tr><td style='padding:10px 12px;border-bottom:1px solid #1E293B'>"
                f"<span style='display:inline-block;background:{c}22;color:{c};font-size:11px;"
                f"font-weight:700;padding:2px 8px;border-radius:4px;margin-right:8px'>{t['label'].upper()}</span>"
                f"<span style='color:#E2E8F0;font-size:14px;font-weight:600'>{t['title']}</span>{detail}</td></tr>")
        return "".join(rows)

    def _digest_html(self, tasks, nice_date, ghost=None):
        ghost = ghost or []
        body = self._rows_html(tasks) or ("<tr><td style='padding:18px 12px;color:#94A3B8'>"
                                          "Board's clear — no urgent moves waiting on you this morning.</td></tr>")
        ghost_section = ""
        if ghost:
            ghost_section = (
                f"<div style='color:#F59E0B;font-size:12px;font-weight:800;letter-spacing:1px;margin:22px 0 8px'>"
                f"WENT GHOST — {len(ghost)} showed interest, re-engage</div>"
                f"<table style='width:100%;border-collapse:collapse;background:#0F172A;"
                f"border:1px solid #1E293B;border-radius:10px'>{self._rows_html(ghost)}</table>")
        ace_section = ""
        try:  # ACE P5: what the autonomous engine did overnight + what the OS spent
            a = self._autonomy_digest() or {}
            s = a.get("summary") or {}
            if a.get("mode") and a.get("mode") != "off":
                bits = (f"mode {a.get('mode')} · {s.get('autoSends', 0)} auto-texts "
                        f"({a.get('sentToday', 0)}/{a.get('cap', 0)} today) · "
                        f"{s.get('shadowDrafts', 0)} drafts queued · "
                        f"{s.get('escalations', 0)} escalations · "
                        f"{a.get('callReadyWaiting', 0)} call-ready waiting · "
                        f"{s.get('blocked', 0)} blocked by gates")
                ace_section = (
                    f"<div style='color:#8B5CF6;font-size:12px;font-weight:800;letter-spacing:1px;"
                    f"margin:22px 0 8px'>ACE OVERNIGHT</div>"
                    f"<div style='color:#94A3B8;font-size:12.5px'>{bits}</div>")
            if a.get("costLine"):
                ace_section += (f"<div style='color:#64748B;font-size:11.5px;margin-top:8px'>"
                                f"💸 {a.get('costLine')}</div>")
        except Exception:  # noqa: BLE001
            pass
        return (
            f"<div style='background:#0B1220;padding:28px;font-family:-apple-system,Segoe UI,sans-serif'>"
            f"<div style='max-width:560px;margin:0 auto'>"
            f"<div style='color:#4F7CFF;font-size:12px;font-weight:800;letter-spacing:2px'>FORGE REI OS</div>"
            f"<h1 style='color:#F8FAFC;font-size:22px;margin:6px 0 2px'>Do Today — {nice_date}</h1>"
            f"<div style='color:#94A3B8;font-size:13px;margin-bottom:18px'>{len(tasks)} urgent moves on the board"
            f"{f' · {len(ghost)} to re-engage' if ghost else ''}. Check them off on the dashboard.</div>"
            f"<table style='width:100%;border-collapse:collapse;background:#0F172A;"
            f"border:1px solid #1E293B;border-radius:10px'>{body}</table>"
            f"{ghost_section}"
            f"{ace_section}"
            f"</div></div>")

    # -- the 9 AM loop ------------------------------------------------------------
    def _seconds_until_run(self):
        now = _now_local()
        nxt = now.replace(hour=RUN_HOUR, minute=0, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        return max(60, (nxt - now).total_seconds())

    def run_forever(self):
        while True:
            try:
                time.sleep(self._seconds_until_run())
                # Clean house first: judge every tagged thread, demote the sellers who
                # aren't actually interested — THEN build today's list from what's left.
                # Verdicts cache per thread, so the build's own gate re-uses them free.
                try:
                    import legit_check
                    legit_check.audit_tagged(self.scout, self.screener)
                except Exception as e:  # noqa: BLE001
                    self.last_error = f"legit audit: {e}"
                self.build(email=True)
                # Marcus (lead agent) reads the fresh board + issues the day's orders.
                try:
                    import marcus_lead
                    marcus_lead.directives(self.scout, self.screener, self.marcus,
                                           self, trigger="morning")
                except Exception as e:  # noqa: BLE001
                    self.last_error = f"directives: {e}"
                forge_heartbeat.beat("do_today", 86400, "Do Today digest",
                                     error=self.last_error, stale_mult=1.1)
            except Exception as e:  # noqa: BLE001
                self.last_error = str(e)
                forge_heartbeat.beat("do_today", 86400, "Do Today digest",
                                     error=self.last_error, stale_mult=1.1)
                time.sleep(300)
