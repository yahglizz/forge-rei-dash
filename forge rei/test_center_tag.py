"""Auto center tags + the simpler tap cards (owner 2026-11-12).
Run: FORGE_MARCUS=0 python3 -m unittest test_center_tag   (no network: GHL client + boards faked)."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

if "slack_io" not in sys.modules:
    os.environ["FORGE_SLACK_CONFIG_DIR"] = tempfile.mkdtemp(prefix="slack_cfg_")
os.environ.setdefault("FORGE_MARCUS", "0")

import daycare_center_tag as ct  # noqa: E402
import daycare_pipeline  # noqa: E402
import dash_live  # noqa: E402
import slack_io  # noqa: E402
import telegram_agent as ta  # noqa: E402

L921, L2318, L1923 = "loc-921-n-18th", "loc-2318-cecil-b-moore", "loc-1923-cecil-b-moore"


def card(cid, name="Ava", centers=(), amt=False):
    return {"opportunityId": "o" + cid, "contactId": cid, "name": name, "stageName": "Contacted",
            "centers": list(centers), "center": centers[0] if len(centers) == 1 else "", "amt": amt}


class FakeGHL:
    configured = True
    location_id = "LOC"

    def __init__(self, contacts):
        self.contacts, self.posts = contacts, []

    def get(self, path, params=None, retries=3):
        if path.endswith("/customFields"):
            return {"customFields": [{"id": "F1", "name": "Preferred Location"}, {"id": "F2", "name": "Tour Location"},
                                     {"id": "F3", "name": "Child DOB"}, {"id": "F4", "name": "Pickup Location"},
                                     {"id": "F5", "name": "SMS Center"}]}
        cid = path.rsplit("/", 1)[-1]
        return {"contact": self.contacts.get(cid) or {}}

    def post(self, path, body=None, retries=2):
        self.posts.append((path, body))
        return {"ok": True}

    def delete(self, path, body=None, retries=2):
        raise AssertionError("the tagger never removes a tag")


class FakeLive(FakeGHL):
    """The live GHL read used by the agents' gate: any contact not listed is a clean untagged one."""
    def __init__(self, live, field="2318"):
        super().__init__({})
        self.live, self.field = live, field

    def get(self, path, params=None, retries=3):
        if path.endswith("/customFields"):
            return FakeGHL.get(self, path)
        cid = path.rsplit("/", 1)[-1]
        return {"contact": self.live.get(cid) or contact({"F1": self.field})}


def contact(fields=None, tags=(), first="Ava"):
    return {"firstName": first, "lastName": "L", "tags": list(tags),
            "customFields": [{"id": k, "value": v} for k, v in (fields or {}).items()]}


class CenterTagTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cards, self.amt = [], []
        self.live = {}                                  # contactId -> live GHL contact ({} = clean default)
        self.field = "2318"                             # what a clean live contact's Preferred Location says
        self.age = 0                                    # seconds old the boards are
        boards = lambda b=None: {"fetchedAt": (time.time() - self.age) * 1000, "stageSource": "live", "error": None,
                                 "cards": self.amt if b == "amt" else self.cards}
        env = {k: v for k, v in os.environ.items() if not k.startswith("SLACK_") and k != "FORGE_DAYCARE_AUTO_CENTER"}
        self.patches = [mock.patch.object(slack_io, "STATE", Path(self.tmp.name)),
                        mock.patch.dict(os.environ, env, clear=True),
                        mock.patch.object(daycare_pipeline, "_load", boards),
                        mock.patch.dict(sys.modules, {"action_log": mock.MagicMock()}),
                        mock.patch.object(ct, "_live_client", lambda: FakeLive(self.live, self.field))]
        for p in self.patches:
            p.start()
        ct._FIELDS.update(at=0.0, ids={})
        ct._RESERVED.clear()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    # center_from_text ----------------------------------------------------------------
    def test_center_from_text_needs_exactly_one_atob_center(self):
        cases = {"2318 Cecil B. Moore Ave": "atob-two", "the 921 one": "atob-one", "921 N 18th St": "atob-one",
                 "A Touch of Blessings 2 & 3 — 2318 Cecil B. Moore Ave.": "atob-two",
                 "921 or 2318": None, "1923 Cecil B. Moore": None, "AMT": None, "Cecil B Moore": None,
                 "921 (A Mother's Touch)": None, "": None, None: None, "the 9210 building": None,
                 # parent-typed text that merely contains the digits: not a center answer
                 "N 18th": None, "1456 N 18th St": None, "215-555-2318": None, "Suite 921": None, "Apt 921": None,
                 "call 267-916-0166 about 921": None, "https://x.com/921": None, "me@921.com": None,
                 "x" * 90 + " 921": None,
                 # AMT in any spelling / width
                 "ＡＭＴ 921": None, "A.M.T. 921": None, "a m t 921": None, "921 mothers touch": None,
                 "921 Mom's Touch": None, "921 ENTITY-AMT": None, "1923": None, "2318 Cecil": "atob-two"}
        for text, want in cases.items():
            self.assertEqual(ct.center_from_text(text), want, text)

    # the agents' gate ----------------------------------------------------------------
    def test_safe_to_add_only_untagged_atob_families(self):
        self.cards = [card("c1"), card("c2", centers=[L921]), card("c3", amt=True), card("c4", centers=[L921, L1923]),
                      card("c5", name="ZZ Test"), card("c6"), card("c7", centers=[L1923])]
        self.amt = [card("c6")]
        self.assertFalse(ct.safe_to_add("c1", L2318.upper())[0])     # exact tag string only
        yes = ct.safe_to_add("c1", L2318)
        self.assertEqual(yes, (True, ""))
        for cid in ("c2", "c3", "c4", "c5", "c6", "c7", "nobody"):
            self.assertFalse(ct.safe_to_add(cid, L2318)[0], cid)
        self.assertFalse(ct.safe_to_add("c1", L1923)[0])            # AMT tag: never
        self.assertFalse(ct.safe_to_add("c1", "family-contact-form")[0])
        with mock.patch.object(daycare_pipeline, "_load", lambda b=None: {}):   # boards never read
            self.assertFalse(ct.safe_to_add("c1", L921)[0])

    def test_safe_to_add_rereads_the_live_contact_and_fails_closed(self):
        self.cards = [card("c1"), card("c2"), card("c3")]
        f = {"F1": "921"}
        self.live = {"c1": contact(f, tags=[L2318]),                              # stale board: GHL already tagged
                     "c2": contact(f, tags=["entity-amt"]),
                     "c3": contact(f, tags=["website-lead"])}
        self.assertFalse(ct.safe_to_add("c1", L921)[0])
        self.assertFalse(ct.safe_to_add("c2", L921)[0])
        self.assertTrue(ct.safe_to_add("c3", L921)[0])
        ct._RESERVED.clear()
        with mock.patch.object(ct, "_live_client", lambda: None):                # no GHL client: a card
            self.assertFalse(ct.safe_to_add("c3", L921)[0])
        boom = FakeLive({})
        boom.get = mock.Mock(side_effect=RuntimeError("GHL down"))
        with mock.patch.object(ct, "_live_client", lambda: boom):
            self.assertFalse(ct.safe_to_add("c3", L921)[0])

    def test_a_second_auto_write_for_the_same_family_is_a_card_until_the_claim_expires(self):
        self.cards = [card("c1")]
        self.field = "921"
        self.assertTrue(ct.safe_to_add("c1", L921)[0])                    # first writer claims the family
        self.assertEqual(ct.safe_to_add("c1", L921), (False, "another center tag for this family is already in flight"))
        n, g = self._run({"c1": contact({"F1": "921"})}, keep=True)       # the box loop waits too
        self.assertEqual((n, g.posts), (0, []))
        ct._RESERVED["c1"] -= ct.RESERVE_SEC + 1                          # claim expired: the live re-read decides
        self.assertTrue(ct.safe_to_add("c1", L921)[0])

    def test_agent_needs_the_same_field_evidence_as_the_loop(self):
        self.cards = [card("c1"), card("c2"), card("c3")]
        self.live = {"c1": contact({}),                                           # chat said 921, the form says nothing
                     "c2": contact({"F1": "921"}),                               # the form names the OTHER center
                     "c3": contact({"F1": "2318", "F2": "921"})}                 # conflicting fields
        self.assertEqual(ct.safe_to_add("c1", L921), (False, "the family's own fields do not name this center"))
        self.assertFalse(ct.safe_to_add("c2", L2318)[0])
        self.assertFalse(ct.safe_to_add("c3", L2318)[0])
        self.assertTrue(ct.safe_to_add("c2", L921)[0])

    def test_boards_must_be_fresh_live_and_clean_for_both_paths(self):
        self.cards = [card("c1")]
        self.age = ct.FRESH_SEC + 60                                              # stale
        self.assertFalse(ct.safe_to_add("c1", L2318)[0])
        self.assertEqual(self._run({"c1": contact({"F1": "2318"})})[0], 0)
        self.age = 0
        real = daycare_pipeline._load
        for bad in ({"error": "boom"}, {"stageSource": "cached"}, {"fetchedAt": 0}):
            with mock.patch.object(daycare_pipeline, "_load", lambda b=None, bad=bad: {**real(b), **bad}):
                self.assertFalse(ct.safe_to_add("c1", L2318)[0], bad)
                self.assertEqual(self._run({"c1": contact({"F1": "2318"})})[0], 0, bad)
        self.assertTrue(ct.safe_to_add("c1", L2318)[0])

    def test_kill_switch_stops_the_agent_path_too(self):
        self.cards = [card("c1")]
        os.environ["FORGE_DAYCARE_AUTO_CENTER"] = "0"
        self.assertEqual(ct.safe_to_add("c1", L2318), (False, "automatic center tags are off"))
        del os.environ["FORGE_DAYCARE_AUTO_CENTER"]

    def test_unreadable_live_tags_are_not_an_untagged_family(self):
        self.cards = [card("c1")]
        no_tags = {"firstName": "Ava", "lastName": "L", "customFields": [{"id": "F1", "value": "2318"}]}
        self.live = {"c1": no_tags}
        self.assertFalse(ct.safe_to_add("c1", L2318)[0])
        self.assertEqual(self._run({"c1": no_tags})[0], 0)

    def test_daily_caps_hold_for_both_paths_and_the_loop_says_so_once(self):
        self.cards = [card(f"c{i}") for i in range(4)]
        with mock.patch.object(ct, "DAILY", {"loop": 2, "agent": 1}), mock.patch.object(slack_io, "send") as send, \
                mock.patch.object(slack_io, "chat_for", lambda b=None: "CH"):
            self.assertTrue(ct.safe_to_add("c0", L2318)[0])
            self.assertEqual(ct.safe_to_add("c1", L2318),
                             (False, "today's automatic center-tag cap for agents is spent"))
            n, _ = self._run({f"c{i}": contact({"F1": "2318"}) for i in range(4)})
            self.assertEqual(n, 2)                                                # loop cap, separate from the agent cap
            caps = [c for c in send.call_args_list if "paused for today" in c.args[0]]
            self.assertEqual(len(caps), 1)

    def test_only_exact_center_field_names_count(self):
        self.cards = [card("c1"), card("c2")]
        n, g = self._run({"c1": contact({"F4": "921"}),                            # "Pickup Location": not read
                          "c2": contact({"F5": "2318"})})                          # "SMS Center": read
        self.assertEqual((n, [p for p, _ in g.posts]), (1, ["/contacts/c2/tags"]))

    def test_any_ambiguous_field_vetoes_the_family(self):
        self.cards = [card("c1")]
        n, g = self._run({"c1": contact({"F1": "2318", "F2": "1923 Cecil B. Moore"})})
        self.assertEqual((n, g.posts), (0, []))

    def test_names_shown_to_the_owner_are_one_clean_line(self):
        self.assertEqual(ct._clean_name("Ava\u202e\n\x00 Smith"), "Ava Smith")
        self.assertEqual(len(ct._clean_name("x" * 500)), 60)
        self.assertEqual(ct._clean_name(None), "a family")

    def test_dash_live_gate_is_auto_only_for_the_safe_single_center_add(self):
        self.cards = [card("c1"), card("c2", centers=[L921])]
        need = lambda body: dash_live._arg_needs_tap("/api/daycare/ghl/tag", body)
        self.assertFalse(need({"contact_id": "c1", "add": [L2318]}))                       # auto
        self.assertTrue(need({"contact_id": "c2", "add": [L2318]}))                        # already has a center
        self.assertTrue(need({"contact_id": "c1", "add": [L1923]}))                        # AMT
        self.assertTrue(need({"contact_id": "c1", "add": [L921, L2318]}))                  # two centers
        self.assertTrue(need({"contact_id": "c1", "add": [L921], "remove": [L2318]}))      # a move
        self.assertTrue(need({"contact_id": "c1", "add": ["family-contact-form"]}))        # intake/login tag
        self.assertTrue(need({"contact_id": "c1", "remove": [L921]}))
        self.assertFalse(need({"contact_id": "c1", "add": ["enrolled"]}))                  # unchanged AUTO

    # the loop ------------------------------------------------------------------------
    def _run(self, contacts, **kw):
        if not kw.pop("keep", False):
            slack_io._write(ct._STATE, {})               # no cool-down / claim left from an earlier pass
            ct._RESERVED.clear()
        g = FakeGHL(contacts)
        return ct.run(self.cards, g, force=True, **kw), g

    def test_run_tags_only_what_the_parent_named_and_only_once(self):
        self.cards = [card("c1", "Seara"), card("c2", "Amy"), card("c3", "Bo"), card("c4", "Cy"), card("c5", "ZZ T"),
                      card("c6", "Di"), card("c7", "Ed", centers=[L921])]
        self.amt = [card("c6")]
        contacts = {"c1": contact({"F1": "A Touch of Blessings 2 & 3 — 2318 Cecil B. Moore Ave."}),
                    "c2": contact({"F1": "921", "F2": "2318"}),                    # conflict
                    "c3": contact({"F1": "1923 Cecil B. Moore"}),                  # AMT
                    "c4": contact({"F3": "921"}),                                  # not a center field
                    "c5": contact({"F1": "921"}),
                    "c6": contact({"F1": "921"}),                                  # on the AMT board
                    "c7": contact({"F1": "2318"})}                                 # already has a center
        n, g = self._run(contacts)
        self.assertEqual(n, 1)
        self.assertEqual(g.posts, [("/contacts/c1/tags", {"tags": [L2318]})])
        n2, g2 = self._run(contacts, keep=True)                                    # cooled down: no re-read
        self.assertEqual((n2, g2.posts), (0, []))

    def test_run_rechecks_contact_before_writing_and_respects_switches(self):
        self.cards = [card("c1")]
        # the board is stale: GHL already has a loc- tag on the contact
        n, g = self._run({"c1": contact({"F1": "921"}, tags=[L2318])})
        self.assertEqual((n, g.posts), (0, []))
        n, g = self._run({"c1": contact({"F1": "921"}, tags=["entity-amt"])})
        self.assertEqual((n, g.posts), (0, []))
        os.environ["FORGE_DAYCARE_AUTO_CENTER"] = "0"
        ct._FIELDS.update(at=0.0, ids={})
        self.assertEqual(ct.run(self.cards, FakeGHL({"c1": contact({"F1": "921"})}), force=True), 0)
        del os.environ["FORGE_DAYCARE_AUTO_CENTER"]
        g = FakeGHL({"c1": contact({"F1": "921"})})
        self.assertEqual(ct.run(self.cards, g), 0)                                 # not the box (FORGE_MARCUS=0)
        self.assertEqual(g.posts, [])
        with mock.patch.object(daycare_pipeline, "_load", lambda b=None: {}):      # boards unread
            self.assertEqual(ct.run(self.cards, g, force=True), 0)

    def test_run_caps_reads_per_pass(self):
        self.cards = [card(f"c{i}") for i in range(30)]
        n, g = self._run({f"c{i}": contact({"F1": "921"}) for i in range(30)})
        self.assertEqual(n, ct.MAX_TAGS)
        self.assertEqual(len(g.posts), ct.MAX_TAGS)


class BatchGateTests(unittest.TestCase):
    """dash_live._write: a batch that edits a family's loc- tags more than once is one card."""
    def test_two_center_adds_for_one_family_in_a_batch_become_a_card(self):
        col = {"actions": [], "done": [], "auto": 0}
        dash_live._TL.c = col
        calls = [{"path": "/api/daycare/ghl/tag", "body": {"contact_id": "c1", "add": [L921]}},
                 {"path": "/api/daycare/ghl/tag", "body": {"contact_id": "c1", "add": [L2318]}}]
        with mock.patch.object(ct, "safe_to_add", lambda cid, tag: (True, "")), \
                mock.patch.object(ta, "allowed", lambda b, m, p: (True, "")), \
                mock.patch.object(ta, "_queue", lambda *a, **k: "tok"), \
                mock.patch.object(dash_live, "_reserve_day", lambda *a, **k: True), \
                mock.patch.object(dash_live, "write_business", lambda a: "daycare"), \
                mock.patch.object(dash_live, "_recently_tainted", lambda a: False):
            out = dash_live._write("api_post_batch", {"calls": calls, "summary": "s"}, "solomon", col)
            self.assertTrue(out.get("queued"))
            self.assertIn("more than one center-tag edit", out["note"])
            col2 = {"actions": [], "done": [], "auto": 0}
            dash_live._TL.c = col2
            with mock.patch.object(ta, "_http", lambda *a, **k: {"ok": True}):
                ok = dash_live._write("api_post_batch", {"calls": calls[:1] + [
                    {"path": "/api/daycare/ghl/tag", "body": {"contact_id": "c2", "add": [L2318]}}], "summary": "s"},
                    "solomon", col2)
            self.assertTrue(ok.get("done"))                               # two DIFFERENT families: both auto
        dash_live._TL.c = None


class CardWordingTests(unittest.TestCase):
    def test_tag_card_is_one_plain_line_with_no_route_or_json(self):
        with mock.patch.object(ta, "_family_name", lambda cid: "Seara Peterson"):
            text, buttons = ta.card({"agent": "solomon", "tok": "t1", "path": "/api/daycare/ghl/tag",
                                     "body": {"contact_id": "c1", "add": [L2318]}, "summary": "model words"})
        self.assertEqual(text, "🟡 <b>Solomon wants to:</b> Tag Seara Peterson → 2318 Cecil B. Moore")
        for bad in ("POST", "/api/", "{", "writes data", "model words"):
            self.assertNotIn(bad, text)
        self.assertEqual([b["text"] for b in buttons[0]], ["✅ Do it", "❌ Cancel"])

    def test_other_routes_keep_the_model_summary_and_one_compact_detail_line(self):
        text, _ = ta.card({"agent": "dyson", "tok": "t2", "path": "/api/agency/calls/log",
                           "body": {"lead": "Acme", "note": "left vm"}, "summary": "Log the call"})
        self.assertIn("Dyson wants to:</b> Log the call", text)
        self.assertIn("<i>agency/calls/log · lead: Acme, note: left vm</i>", text)
        self.assertNotIn("POST", text)
        risky, _ = ta.card({"agent": "marcus", "tok": "t3", "path": "/api/marcus/approve",
                            "body": {"id": "x"}, "summary": "Send reply"})
        self.assertIn("✉️ sends / approves", risky)                                  # real risk labels stay

    def test_tap_footer_is_empty_on_plain_success_and_keeps_what_the_owner_needs(self):
        self.assertEqual(ta.footer({"ok": True, "contactId": "c1", "added": [L921], "removed": []}), "")
        self.assertIn("482913", ta.footer({"ok": True, "pin": "482913", "login": "ava"}))     # PIN shown once
        self.assertIn("https://x", ta.footer({"ok": True, "url": "https://x"}))
        with mock.patch.object(ta, "_family_name", lambda cid: "Seara"), \
                mock.patch.object(ta, "_http", lambda *a, **k: {"ok": True, "contactId": "c1", "added": [L921]}), \
                mock.patch.object(ta, "allowed", lambda *a: (True, "")), mock.patch.object(ta, "_log_tap"), \
                mock.patch.object(ta, "_hook"), mock.patch.object(ta, "_load", lambda: {"t": {
                    "business": "daycare", "path": "/api/daycare/ghl/tag", "body": {"contact_id": "c1", "add": [L921]},
                    "summary": "x", "chat": "dash", "ts": __import__("time").time(), "agent": "solomon"}}), \
                mock.patch.object(ta.forge_atomic, "atomic_write_json"):
            out = ta.confirm("t", "dash")
        self.assertEqual(out, {"ok": True, "message": "Tag Seara → 921 N 18th"})

    def test_card_never_hides_or_cuts_what_the_tap_runs(self):
        long_note = "n" * 400
        text, _ = ta.card({"agent": "solomon", "tok": "t", "path": "/api/hub/task", "summary": "model",
                           "body": {"agentId": "marcus", "title": "T" * 300, "note": long_note}})
        self.assertIn("T" * 300, text)
        self.assertIn(long_note, text)                                                 # full, not cut at 140
        extra, _ = ta.card({"agent": "solomon", "tok": "t", "path": "/api/hub/task", "summary": "benign words",
                            "body": {"agentId": "marcus", "title": "x", "business": "wholesale"}})
        self.assertIn("benign words", extra)                                           # key the template hides: no template
        self.assertIn("business: wholesale", extra)                                    # ...and the field is on the card
        tag_extra, _ = ta.card({"agent": "solomon", "tok": "t", "path": "/api/daycare/ghl/tag", "summary": "Tag Ava",
                                "body": {"contact_id": "c1", "add": [L921], "remove": ["enrolled"], "force": True}})
        self.assertIn("force: True", tag_extra)
        note, _ = ta.card({"agent": "orion", "tok": "t", "path": "/api/knowledge/post", "summary": "x",
                           "body": {"text": "k" * 700, "agent": "orion"}})
        self.assertIn("k" * 700, note)
        with mock.patch.object(ta, "_family_name", lambda cid: None):
            unknown, _ = ta.card({"agent": "solomon", "tok": "t", "path": "/api/daycare/ghl/tag", "summary": "x",
                                  "body": {"contact_id": "zz9", "add": [L921]}})
        self.assertIn("contact zz9", unknown)                                          # an id, not "a contact"

    def test_batch_rows_are_plain_lines(self):
        with mock.patch.object(ta, "_family_name", lambda cid: "Ava"):
            self.assertEqual(ta.line("/api/daycare/ghl/tag", {"contact_id": "c1", "add": [L921]}), "Tag Ava → 921 N 18th")
        self.assertEqual(ta.line("/api/x/y", {"a": 1}), "x/y · a: 1")


if __name__ == "__main__":
    unittest.main()
