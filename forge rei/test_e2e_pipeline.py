"""End-to-end pipeline test — fake leads from A to Z through the REAL engines.

Runs the actual production functions (Scout poll_once -> auto-screen bridge ->
Marcus screening -> conversation state -> ACE decide/consider/apply -> Atlas
deal prep -> Do Today) against an in-memory fake GHL and a canned fake Claude.
Zero network, zero real SMS, zero writes to production marcus_state/ (every
STATE file is pointed at a tempdir), zero vault writes (brain_io captured).

The connector's wiring (SCOUT.on_scored -> _auto_screen -> _ace_update_from_
screening) is reproduced synchronously so assertions are deterministic.
"""

import json
import tempfile
import time
import unittest
from pathlib import Path

import ace
import agent_bus
import agent_context
import brain_io
import conversation_engine
import deal_prep
import do_today
import forge_ops
import legit_check
import marcus_engine
import marcus_screening
import review_agent
import scout_triage
import send_ledger
import test_mode

NOW_MS = int(time.time() * 1000)


# ── fakes ────────────────────────────────────────────────────────────────────────────

class FakeGHL:
    """In-memory GHL. Serves the exact endpoints the engines hit; records writes."""

    def __init__(self):
        self.convos = []       # rows for /conversations/search
        self.threads = {}      # convId -> [ {direction, body, dateAdded} ] oldest-first
        self.posts = []        # (path, payload)
        self.puts = []
        self.deletes = []
        self.opps = {}         # contactId -> opportunity

    def add_lead(self, conv_id, contact_id, name, phone, thread):
        """thread: list of (direction, body) oldest-first. Last message drives the row."""
        msgs = [{"direction": d, "body": b, "dateAdded": NOW_MS - (len(thread) - i) * 60000}
                for i, (d, b) in enumerate(thread)]
        self.threads[conv_id] = msgs
        last = msgs[-1]
        self.convos.append({
            "id": conv_id, "contactId": contact_id, "fullName": name, "phone": phone,
            "lastMessageBody": last["body"], "lastMessageDate": last["dateAdded"],
            "lastMessageDirection": last["direction"],
        })

    def get(self, path, params=None):
        params = params or {}
        if path == "/conversations/search":
            rows = self.convos
            if params.get("contactId"):
                rows = [c for c in rows if c.get("contactId") == params["contactId"]]
            return {"conversations": rows}
        if path.startswith("/conversations/") and path.endswith("/messages"):
            cid = path.split("/")[2]
            newest_first = list(reversed(self.threads.get(cid, [])))
            return {"messages": {"messages": newest_first}}
        if path == "/opportunities/pipelines":
            return {"pipelines": [{
                "id": "pl1", "name": "Wholesaling Pipeline",
                "stages": [{"name": n, "id": f"st_{i}"} for i, n in enumerate(
                    ["New Lead", "Responded", "Warm", "Hot",
                     "Appointment Set", "Under Contract", "Closed / Won"])],
            }]}
        if path == "/opportunities/search":
            opp = self.opps.get(params.get("contact_id"))
            return {"opportunities": [opp] if opp else []}
        return {}

    def post(self, path, payload=None):
        self.posts.append((path, payload))
        if path == "/opportunities/":
            self.opps[payload["contactId"]] = dict(payload, id=f"opp_{payload['contactId']}")
        return {}

    def put(self, path, payload=None):
        self.puts.append((path, payload))
        return {}

    def delete(self, path, payload=None):
        self.deletes.append((path, payload))
        return {}

    def tag_posts(self, contact_id):
        return [pl for p, pl in self.posts if p == f"/contacts/{contact_id}/tags"]

    def sms_posts(self):
        return [(p, pl) for p, pl in self.posts if "message" in p.lower()]


class FakeMarcus:
    """Approval-inbox stand-in (same surface ACE + Do Today use). Never texts."""

    def __init__(self):
        self.proposals = {}
        self.approved = []
        self._n = 0

    def make_proposal_for(self, conv_id, contact_id=None, hint=None, seller_said=None):
        self._n += 1
        pid = f"p{self._n}"
        self.proposals[pid] = {
            "conversationId": conv_id, "contactId": contact_id, "hint": hint,
            "status": "pending", "ts": int(time.time() * 1000) + self._n,
            "sentReply": f"draft for {conv_id}",
        }
        return {"ok": True, "id": pid}

    def approve(self, pid):
        p = self.proposals.get(pid)
        if not p:
            return {"error": "no such proposal"}
        p["status"] = "sent"
        self.approved.append(pid)
        return {"ok": True}

    def proposals_list(self):
        return list(self.proposals.values())


# Canned Claude bodies keyed by which agent's system prompt shows up.
def make_claude_router(store):
    def _fake_claude(key, system, user, max_tokens=1200):
        if system.startswith("You are Scout"):
            return store.get("scout", "[]")
        if system.startswith("You are Marcus"):
            return store.get("marcus", "{}")
        if system.startswith("You are Atlas"):
            return store.get("atlas", "{}")
        # legit_check / anything else -> pass-through verdict
        return store.get("other", '{"legit": true, "urgency": "high", "reason": "engaged seller"}')
    return _fake_claude


SCREEN_REPORT_HOT = {
    "score": 9, "interest": "interested", "stage": "Hot Lead - Call Now",
    "sellerSituation": "Inherited the house, wants it gone fast.",
    "motivationLevel": "high",
    "sellerPsychology": "Decisive, money-motivated, wants speed and certainty.",
    "propertyStatus": "vacant",
    "conditionNotes": "roof is older, otherwise livable",
    "timeline": "2-3 weeks, wants it gone asap",
    "askingPrice": "$80,000",
    "missing": [],
    "redFlags": [],
    "whyCall": "Stated a price and urgency — call now.",
    "pathToContract": "Anchor off their ask, lock terms on the call.",
    "recommendedAction": "Call today",
    "checkBackDays": None, "nurtureDraft": None,
    "callPrep": {"opener": "hey maria, saw you want it gone quick",
                 "questions": ["how soon are you looking to close",
                               "what kind of shape is the roof in",
                               "is anyone living there now"],
                 "painPoints": ["holding costs", "distance"],
                 "avoid": ["don't lead with price"]},
}

SCREEN_REPORT_QUALIFYING = {
    "score": 6, "interest": "interested", "stage": "Needs More Info",
    "sellerSituation": "Thinking about selling, early.",
    "motivationLevel": "medium",
    "sellerPsychology": "Cautious, exploring options.",
    "propertyStatus": "unknown",
    "conditionNotes": "needs some work per the seller",
    "timeline": "unknown",
    "askingPrice": None,
    "missing": ["timeline", "occupancy", "price"],
    "redFlags": [],
    "whyCall": "Real interest, needs qualification.",
    "pathToContract": "Qualify the missing facts first.",
    "recommendedAction": "Qualify by text",
    "checkBackDays": None, "nurtureDraft": None,
    "callPrep": {"opener": "hey, appreciate you getting back",
                 "questions": ["how soon are you looking to sell",
                               "is it vacant right now or is someone living there"],
                 "painPoints": ["repairs piling up"],
                 "avoid": ["don't lead with price"]},
}

SCREEN_REPORT_NOT_READY = {
    "score": 3, "interest": "not_ready", "stage": "Follow-Up",
    "sellerSituation": "Not selling right now, open later.",
    "motivationLevel": "low",
    "sellerPsychology": "No urgency; keep it warm.",
    "propertyStatus": "owner-occupied",
    "conditionNotes": "not mentioned",
    "timeline": "maybe later this year",
    "askingPrice": None,
    "missing": ["condition", "price"],
    "redFlags": [],
    "whyCall": "Not yet — nurture.",
    "pathToContract": "Check back when the timing moves.",
    "recommendedAction": "Send a no-pressure check-back",
    "checkBackDays": 60,
    "nurtureDraft": "hey no worries at all — no rush on my end! ok if i check back in a couple months; just in case anything changes",
    "callPrep": {"opener": "", "questions": [], "painPoints": [],
                 "avoid": ["don't lead with price"]},
}

ATLAS_PREP = {
    "address": "12 Elm St", "askingPrice": 80000, "beds": 3, "baths": 1,
    "condition": "light rehab", "occupancy": "vacant",
    "timeline": "2-3 weeks",
    "motivationRead": "Inherited property, wants out fast.",
    "repairEstimate": "medium — older roof",
    "anchors": {"opening": 58000, "target": 66000, "walkaway": 80000},
    "anchorLogic": "Derived from the seller's stated $80k ask (72%/82%/100%).",
    "maoNote": "MAO = ARV x 0.70 - repairs - fee; pull comps for the zip to confirm ARV.",
    "callCard": ["open with rapport", "confirm timeline", "confirm roof scope",
                 "let her say the number first", "close on terms"],
    "redFlags": ["probate paperwork status unknown"],
}


# ── harness ──────────────────────────────────────────────────────────────────────────

class E2EBase(unittest.TestCase):
    """Every STATE file -> tempdir; Claude + GHL + vault + keys faked; real engines."""

    STATE_MODULES = (scout_triage, marcus_screening, deal_prep, do_today,
                     conversation_engine, ace, agent_bus, test_mode,
                     legit_check, send_ledger, forge_ops)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._orig = []

        def patch(obj, attr, val):
            self._orig.append((obj, attr, getattr(obj, attr)))
            setattr(obj, attr, val)

        for mod in self.STATE_MODULES:
            patch(mod, "STATE", tmp / f"{mod.__name__}.json")
        # ace keeps its call-ready queue in a SECOND file — leave it unpatched and the
        # suite writes fake leads into production marcus_state/call_ready.json.
        patch(ace, "CALL_READY", tmp / "call_ready.json")

        # No network, no keys from disk, no vault writes, no clock-out.
        self.claude = {}
        patch(review_agent, "_claude", make_claude_router(self.claude))
        patch(review_agent, "_api_key", lambda: "test-key")
        patch(scout_triage, "_scout_key", lambda: "test-key")
        patch(marcus_screening, "_marcus_key", lambda: "test-key")
        patch(deal_prep, "_atlas_key", lambda: "test-key")
        patch(forge_ops, "paused", lambda: False)
        patch(agent_context, "brain_context", lambda *a, **k: "")
        self.brain_writes = []
        patch(brain_io, "write_note",
              lambda rel, content, reason="": (self.brain_writes.append((rel, reason))
                                               or {"ok": True, "path": rel}))
        # Bus spy — real send still runs (tmp STATE), we just record what crossed it.
        self.bus = []
        real_send = agent_bus.send
        patch(agent_bus, "send",
              lambda frm, to, kind, text, data=None: (self.bus.append(
                  {"from": frm, "kind": kind, "text": text, "data": data or {}})
                  or real_send(frm, to, kind, text, data)))

        # The stack, wired exactly like connector.py (but synchronous).
        self.ghl = FakeGHL()
        self.scout = scout_triage.ScoutEngine(self.ghl.get, self.ghl.post, "loc1",
                                              ghl_put=self.ghl.put,
                                              ghl_delete=self.ghl.delete)
        self.screener = marcus_screening.Screener(self.ghl.get, "loc1",
                                                  scout=self.scout,
                                                  ghl_post=self.ghl.post)
        self.convo = conversation_engine.ConversationEngine()
        self.prep = deal_prep.DealPrep(self.scout, self.screener, self.ghl.get, "loc1")
        self.marcus = FakeMarcus()
        self.today = do_today.DoTodayEngine(self.scout, self.screener, self.marcus,
                                            self.ghl.get, self.ghl.post, "loc1",
                                            "yahjair@atouchofblessing.com")
        self.today.deal_prep = self.prep
        self.scout.on_scored = self._auto_screen   # connector._auto_screen, sync

    def tearDown(self):
        for obj, attr, val in reversed(self._orig):
            setattr(obj, attr, val)
        self._tmp.cleanup()

    # connector.py's _auto_screen + _ace_update_from_screening, run inline.
    def _auto_screen(self, rec):
        if not marcus_screening.AUTO_SCREEN:
            return
        cid = rec.get("contactId")
        self.screener.auto_screen(contact_id=cid, conv_id=rec.get("convId"))
        r = self.screener.screenings.get(cid) or {}
        conv_id = r.get("convId")
        if not conv_id:
            return
        crec = self.convo.update(conv_id, contact_id=cid, name=r.get("name"),
                                 report=r.get("report"),
                                 last_inbound_ms=r.get("updatedAt"))
        m = ace.mode()
        if crec and m != "off":
            msgs = self.scout._thread_transcript(conv_id) or []
            inb = [x["body"] for x in msgs
                   if x.get("direction") == "inbound" and (x.get("body") or "").strip()]
            last_in = inb[-1] if inb else None
            if m in ("supervised", "full"):
                ace.apply(conv_id, crec, r.get("report"), self.convo, self.marcus,
                          last_seller_msg=last_in, deal_prep=self.prep)
            else:
                ace.consider(conv_id, crec, r.get("report"), self.convo, self.marcus,
                             last_seller_msg=last_in)
                if (crec or {}).get("state") == "CALL_READY":
                    ace.call_ready_upsert(crec, r.get("report"), self.prep)


# ── scenario 1: hot / ASAP lead, A to Z ─────────────────────────────────────────────

class HotLeadAtoZ(E2EBase):
    def seed(self):
        self.ghl.add_lead("c1", "ct1", "Maria Lopez", "+15551230001", [
            ("outbound", "hey, saw your property on elm st — would you consider selling?"),
            ("inbound", "yes im interested in selling, looking to get $80,000, need it gone asap"),
        ])
        self.claude["scout"] = json.dumps(
            [{"i": 0, "intent": "ready", "motivation": 92,
              "askingPrice": 80000, "reason": "stated price, urgent"}])
        self.claude["marcus"] = json.dumps(SCREEN_REPORT_HOT)
        self.claude["atlas"] = json.dumps(ATLAS_PREP)

    def test_scout_scores_asap_and_alerts(self):
        self.seed()
        self.scout.poll_once()
        rec = self.scout.records["c1"]
        self.assertEqual("asap", rec["bucket"])
        self.assertEqual(92, rec["motivation"])
        self.assertEqual(80000, rec["askingPrice"])
        self.assertEqual("claude", rec["scoreSource"])
        self.assertIn("triage: asap", rec["proposedTags"])
        self.assertIn("motivated: high", rec["proposedTags"])
        hot = [b for b in self.bus if b["data"].get("type") == "hot_lead"]
        self.assertEqual(1, len(hot))
        self.assertEqual("ct1", hot[0]["data"]["contactId"])
        # second poll, same message: no re-score, no duplicate alert
        self.scout.poll_once()
        self.assertEqual(1, len([b for b in self.bus if b["data"].get("type") == "hot_lead"]))

    def test_auto_screen_produces_report_and_call_ready_state(self):
        self.seed()
        self.scout.poll_once()
        s = self.screener.screenings.get("ct1")
        self.assertIsNotNone(s, "auto-screen bridge never fired")
        self.assertTrue(s["auto"])
        rep = s["report"]
        self.assertEqual(9, rep["score"])
        self.assertEqual("Hot Lead - Call Now", rep["stage"])
        self.assertEqual("interested", rep["interest"])
        self.assertEqual("$80,000", rep["askingPrice"])
        self.assertIsNone(rep["nurtureDraft"])       # interested -> no nurture fields
        crec = self.convo.get("c1")
        self.assertIsNotNone(crec)
        self.assertEqual("CALL_READY", crec["state"])   # all 5 facts known
        self.assertTrue(all(crec["facts"].values()))
        self.assertTrue(self.brain_writes, "screening never mirrored to the brain")

    def test_atlas_prep_anchors_from_seller_ask_only(self):
        self.seed()
        self.scout.poll_once()
        out = self.prep.auto_prep_interested()
        self.assertEqual(1, len(out["prepped"]))
        p = self.prep.get("ct1")["prep"]
        a = p["anchors"]
        self.assertEqual(80000, p["askingPrice"])
        self.assertEqual(80000, a["walkaway"])          # walkaway = the ask, never above
        self.assertLess(a["opening"], a["target"])
        self.assertLessEqual(a["target"], a["walkaway"])
        # cached: same screening -> no second Claude call
        self.assertTrue(self.prep.prep("ct1").get("cached"))

    def test_hot_autotag_and_autopipeline_are_idempotent(self):
        self.seed()
        self.scout.poll_once()   # scores; autotag ran before scoring, so tags land next poll
        self.scout.poll_once()
        tags = self.ghl.tag_posts("ct1")
        self.assertEqual(1, len(tags))
        self.assertIn("triage: asap", tags[0]["tags"])
        self.assertIn("motivated: high", tags[0]["tags"])
        opp = self.ghl.opps.get("ct1")
        self.assertIsNotNone(opp, "hot lead never auto-landed in the pipeline")
        self.assertEqual("st_3", opp["pipelineStageId"])   # Hot stage
        self.scout.poll_once()   # third poll: no duplicates
        self.assertEqual(1, len(self.ghl.tag_posts("ct1")))
        self.assertEqual(1, len([p for p, _ in self.ghl.posts if p == "/opportunities/"]))

    def test_do_today_dedupes_to_one_task_text_back_first(self):
        self.seed()
        self.scout.poll_once()
        self.prep.auto_prep_interested()
        coll = self.today._collect()
        mine = [t for t in coll["today"] if t.get("contactId") == "ct1"]
        self.assertEqual(1, len(mine), f"expected one deduped task, got {mine}")
        self.assertEqual("reply", mine[0]["kind"])       # speed-to-lead: text back outranks call
        again = self.today._collect()
        self.assertEqual([t["id"] for t in coll["today"]],
                         [t["id"] for t in again["today"]])   # stable ids, no dupes

    def test_do_today_surfaces_anchored_call_after_we_text_back(self):
        self.seed()
        self.scout.poll_once()
        self.prep.auto_prep_interested()
        # Operator texted back; thread hasn't moved -> reply task suppressed, call surfaces.
        orig = send_ledger.last_reply_msg_date
        send_ledger.last_reply_msg_date = lambda conv_id: NOW_MS + 10
        try:
            coll = self.today._collect()
        finally:
            send_ledger.last_reply_msg_date = orig
        mine = [t for t in coll["today"] if t.get("contactId") == "ct1"]
        self.assertEqual(1, len(mine))
        self.assertEqual("call", mine[0]["kind"])
        self.assertIn("anchors", mine[0]["detail"])      # Atlas anchors arm the call

    def test_no_sms_and_no_autonomous_sends_with_ace_off(self):
        self.seed()
        self.scout.poll_once()
        self.prep.auto_prep_interested()
        self.assertEqual("off", ace.mode())
        self.assertEqual({}, self.marcus.proposals)      # ACE off -> Marcus never drafted
        self.assertEqual([], self.marcus.approved)
        self.assertEqual([], self.ghl.sms_posts())       # zero outbound messages, ever


# ── scenario 2: not-ready seller -> nurture, never screened automatically ──────────

class NurtureLead(E2EBase):
    def test_nurture_bucket_no_handoff_no_alert(self):
        self.ghl.add_lead("c2", "ct2", "Bob Ray", "+15551230002", [
            ("outbound", "hey, would you consider selling your place on oak ave?"),
            ("inbound", "not right now, maybe later in the year"),
        ])
        self.scout.poll_once()
        rec = self.scout.records["c2"]
        self.assertEqual("nurture", rec["bucket"])
        self.assertEqual("rule", rec["scoreSource"])     # deterministic, no Claude spent
        self.assertIsNone(self.screener.screenings.get("ct2"))   # not call-worthy -> no screen
        self.assertEqual([], [b for b in self.bus if b["data"].get("type") == "hot_lead"])
        self.scout.poll_once()
        self.assertEqual([], self.ghl.tag_posts("ct2"))  # auto-tag is hot-only

    def test_manual_screen_yields_gated_nurture_draft(self):
        self.ghl.add_lead("c2", "ct2", "Bob Ray", "+15551230002", [
            ("outbound", "hey, would you consider selling your place on oak ave?"),
            ("inbound", "not right now, maybe later in the year"),
        ])
        self.scout.poll_once()
        self.claude["marcus"] = json.dumps(SCREEN_REPORT_NOT_READY)
        out = self.screener.screen(contact_id="ct2")
        self.assertTrue(out.get("ok"), out)
        rep = self.screener.screenings["ct2"]["report"]
        self.assertEqual("not_ready", rep["interest"])
        self.assertEqual("Follow-Up", rep["stage"])
        self.assertEqual(60, rep["checkBackDays"])
        self.assertTrue(rep["nurtureDraft"])
        self.assertNotIn("!", rep["nurtureDraft"])       # voice scrub applied
        self.assertNotIn("—", rep["nurtureDraft"])
        self.assertEqual([], self.ghl.sms_posts())       # draft only — nothing sent


# ── scenario 3: DNC and our-own-message safety filters ──────────────────────────────

class SafetyFilters(E2EBase):
    def test_dnc_goes_dead_and_is_never_entertained(self):
        self.ghl.add_lead("c3", "ct3", "Ann Po", "+15551230003", [
            ("outbound", "hey, we buy houses — interested in an offer on maple dr?"),
            ("inbound", "STOP"),
        ])
        self.scout.poll_once()
        rec = self.scout.records["c3"]
        self.assertEqual("dead", rec["bucket"])
        self.assertEqual(["triage: dead"], rec["proposedTags"])   # no motivated tag on dead
        self.assertIsNone(self.screener.screenings.get("ct3"))
        out = self.screener.screen(contact_id="ct3")              # even a manual screen refuses
        self.assertIn("skipped", out)
        self.scout.poll_once()
        self.assertEqual([], self.ghl.tag_posts("ct3"))           # dead never auto-tags
        self.assertEqual([], self.ghl.sms_posts())

    def test_denial_wrong_number_is_ignored_not_screened(self):
        # "Did I call you? No" — a real example that used to fall through every bucket to
        # CONTINUE ("warm", 45) and burn a Marcus screening call. Must go straight to dead,
        # rule-scored (no Claude spent), never auto-screened, never on Do Today.
        self.ghl.add_lead("c6", "ct6", "Andy Bank", "+15551230006", [
            ("outbound", "hey, was this a good number to reach you about your property?"),
            ("inbound", "did I call you? No"),
        ])
        self.scout.poll_once()
        rec = self.scout.records["c6"]
        self.assertEqual("dead", rec["bucket"])
        self.assertEqual("rule", rec["scoreSource"])          # no Claude call spent
        self.assertEqual(["triage: dead"], rec["proposedTags"])
        self.assertIsNone(self.screener.screenings.get("ct6"))   # never auto-screened
        mine = [t for t in self.today._collect()["today"] if t.get("contactId") == "ct6"]
        self.assertEqual([], mine)                            # never a Do Today task
        out = self.screener.screen(contact_id="ct6")          # manual attempt also refuses
        self.assertIn("skipped", out)

    def test_identity_denial_variant_also_ignored(self):
        self.ghl.add_lead("c7", "ct7", "Wrong Person", "+15551230007", [
            ("outbound", "hi, reaching out about the house on birch ln"),
            ("inbound", "you have the wrong number, I don't know you"),
        ])
        self.scout.poll_once()
        rec = self.scout.records["c7"]
        self.assertEqual("dead", rec["bucket"])
        self.assertEqual("rule", rec["scoreSource"])
        self.assertEqual([], [b for b in self.bus if b["data"].get("type") == "hot_lead"])

    def test_who_is_this_variants_go_dead_free_no_screen(self):
        # Live example: Ernest Brown replied "Who are you?" to our follow-up. It used to
        # be HELP -> rule bucket "warm"/50, spending a Claude call before landing anywhere.
        # Must be caught free, straight to dead.
        self.ghl.add_lead("c8", "ct8", "Ernest Brown", "+15551230008", [
            ("outbound", "hi Ernest, just checking back in on the property, any thoughts?"),
            ("inbound", "Who are you?"),
        ])
        self.scout.poll_once()
        rec = self.scout.records["c8"]
        self.assertEqual("dead", rec["bucket"])
        self.assertEqual("rule", rec["scoreSource"])
        self.assertIsNone(self.screener.screenings.get("ct8"))

    def test_identity_denial_regex_catches_named_variants(self):
        # Live examples: "THIS IS NOT KRISTEN..." and "I am not geraldine" — a fixed
        # phrase list can't cover an arbitrary name, so this needs the regex path.
        self.ghl.add_lead("c9", "ct9", "Kristen Moffett", "+15551230009", [
            ("outbound", "Hi Kristen, still buying as-is for cash on 3140 Maeterlinck Ave?"),
            ("inbound", "THIS IS NOT KRISTEN. I've had this number for 5 years."),
        ])
        self.ghl.add_lead("c10", "ct10", "Geraldine Brown", "+15551230010", [
            ("outbound", "hi, reaching out about the property"),
            ("inbound", "I am not geraldine"),
        ])
        self.scout.poll_once()
        self.assertEqual("dead", self.scout.records["c9"]["bucket"])
        self.assertEqual("rule", self.scout.records["c9"]["scoreSource"])
        self.assertEqual("dead", self.scout.records["c10"]["bucket"])
        self.assertEqual("rule", self.scout.records["c10"]["scoreSource"])
        # sanity: real seller replies with "not" mid-sentence must NOT be caught
        self.assertFalse(marcus_engine._is_denial("I'm not interested in selling, thanks"))
        self.assertFalse(marcus_engine._is_denial("I am not selling right now"))

    def test_explicit_optout_is_dead_grade_even_without_stop_keyword(self):
        # Live example: Kristen Moffett's actual full reply — an explicit removal demand
        # that never says "stop" or "unsubscribe" (the only DNC_PHRASES matches), so it
        # currently only gets caught if Claude happens to read it right. Must be free +
        # deterministic so it never depends on Claude being up.
        self.ghl.add_lead("c11", "ct11", "Kristen Moffett", "+15551230011", [
            ("outbound", "Hi Kristen, following up about 3140 Maeterlinck Ave."),
            ("inbound", "I've had this number for 5 years and you people have been "
                        "bothering me. please LEAVE ME ALONE. REMOVE MY NUMBER FROM "
                        "YOUR WEBSITE."),
        ])
        self.scout.poll_once()
        rec = self.scout.records["c11"]
        self.assertEqual("dead", rec["bucket"])
        self.assertEqual("rule", rec["scoreSource"])
        self.assertIn("opt-out", rec["reason"])
        self.assertIsNone(self.screener.screenings.get("ct11"))
        out = self.screener.screen(contact_id="ct11")
        self.assertIn("skipped", out)

    def test_our_own_outreach_is_never_scored(self):
        # GHL sometimes mis-flags our blast as inbound — the seller-message filter drops it.
        self.ghl.add_lead("c5", "ct5", "Sam Hill", "+15551230005", [
            ("inbound", "Hey, I was calling about your property — we buy houses in any condition"),
        ])
        self.scout.poll_once()
        self.assertNotIn("c5", self.scout.records)
        self.assertEqual({}, self.screener.screenings)
        self.assertEqual([], self.bus)


# ── scenario 4: ACE autonomy ladder (off -> shadow -> supervised), all gated ───────

class AceLadder(E2EBase):
    def seed_qualifying(self):
        self.ghl.add_lead("c4", "ct4", "Joe King", "+15551230004", [
            ("outbound", "hey, would you consider selling the house on pine st?"),
            ("inbound", "im thinking about it, the place needs some updates honestly"),
        ])
        self.claude["scout"] = json.dumps(
            [{"i": 0, "intent": "warm", "motivation": 60,
              "askingPrice": None, "reason": "engaged, early"}])
        self.claude["marcus"] = json.dumps(SCREEN_REPORT_QUALIFYING)

    def test_shadow_drafts_but_never_sends(self):
        ace.set_mode("shadow")
        self.seed_qualifying()
        self.scout.poll_once()
        crec = self.convo.get("c4")
        self.assertEqual("QUALIFYING", crec["state"])
        pend = [p for p in self.marcus.proposals.values() if p["status"] == "pending"]
        self.assertEqual(1, len(pend), f"shadow should draft exactly one proposal: "
                                       f"{self.marcus.proposals} / ace={ace.status()}")
        self.assertIn("timeline", pend[0]["hint"])       # asks the top missing fact
        self.assertEqual([], self.marcus.approved)       # shadow NEVER sends
        self.assertEqual([], self.ghl.sms_posts())
        kinds = [e.get("kind") for e in ace.status().get("log", [])]
        self.assertIn("shadow_draft", kinds)

    def test_supervised_autosend_is_flagged_autonomous_and_capped(self):
        ace.set_mode("supervised")
        self.seed_qualifying()
        self.scout.poll_once()
        self.assertEqual(1, len(self.marcus.approved))   # one gated auto-send via approve()
        p = list(self.marcus.proposals.values())[0]
        self.assertTrue(p.get("autonomous"), "LOCKED CONTRACT: supervised send must be "
                                             "autonomous=True (full sms_guard stack)")
        self.assertTrue(p.get("ace"))
        st = ace.status()
        self.assertEqual(1, st.get("sentToday"))
        self.assertEqual(1, self.convo.get("c4")["replies"])
        kinds = [e.get("kind") for e in st.get("log", [])]
        self.assertIn("auto_send", kinds)

    def test_off_mode_never_touches_marcus(self):
        self.assertEqual("off", ace.mode())
        self.seed_qualifying()
        self.scout.poll_once()
        self.assertEqual({}, self.marcus.proposals)
        d = ace.decide(self.convo.get("c4"), SCREEN_REPORT_QUALIFYING, self.convo)
        self.assertEqual("stop", d["action"])
        self.assertEqual("ace off", d["reason"])

    def test_call_ready_escalates_instead_of_texting(self):
        ace.set_mode("shadow")
        self.ghl.add_lead("c1", "ct1", "Maria Lopez", "+15551230001", [
            ("outbound", "hey, saw your property on elm st — would you consider selling?"),
            ("inbound", "yes im interested in selling, looking to get $80,000, need it gone asap"),
        ])
        self.claude["scout"] = json.dumps(
            [{"i": 0, "intent": "ready", "motivation": 92,
              "askingPrice": 80000, "reason": "stated price, urgent"}])
        self.claude["marcus"] = json.dumps(SCREEN_REPORT_HOT)
        self.claude["atlas"] = json.dumps(ATLAS_PREP)
        self.scout.poll_once()
        self.assertEqual("CALL_READY", self.convo.get("c1")["state"])
        self.assertEqual({}, self.marcus.proposals)      # escalate = phone call, not a text
        ready = ace.call_ready_list().get("callReady") or []
        self.assertEqual(1, len(ready))
        self.assertEqual("ct1", ready[0]["contactId"])
        kinds = [e.get("kind") for e in ace.status().get("log", [])]
        self.assertIn("escalate", kinds)


if __name__ == "__main__":
    unittest.main(verbosity=2)
