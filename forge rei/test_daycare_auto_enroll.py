"""Family Contact Form -> app, hands-free. No network: GHL cards + enroll are faked."""
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import daycare_auto_enroll as ae

TODAY = date(2026, 10, 7)


def card(cid="c1", first="Ava", last="Stone", dob="2022-03-01", loc="loc-1923-cecil-b-moore",
         pf="Dana", pl="Stone", phone="+12155550123", email="d@x.com", enrolled=True, missing=None):
    return {"contact_id": cid, "card_id": cid, "child_first": first, "child_last": last, "child_dob": dob,
            "location_tag": loc, "parent_first": pf, "parent_last": pl, "phone": phone, "email": email,
            "enrolled": enrolled, "missing": missing or []}


class ReviewTests(unittest.TestCase):
    def test_clean_card_is_ready(self):
        ready, held = ae.review([card()], TODAY)
        self.assertEqual((len(ready), len(held)), (1, 0))

    def test_leads_are_ignored_not_held(self):
        ready, held = ae.review([card(enrolled=False, missing=["not enrolled"])], TODAY)
        self.assertEqual((ready, held), ([], []))

    def test_missing_data_held_with_reason(self):
        _, held = ae.review([card(missing=["child birth date"])], TODAY)
        self.assertIn("child birth date", held[0]["reasons"])

    def test_bad_birth_dates_held(self):
        for dob in ("2000-01-05", "2027-01-01"):
            _, held = ae.review([card(dob=dob)], TODAY)
            self.assertTrue(any("looks wrong" in r for r in held[0]["reasons"]), dob)

    def test_test_records_and_foreign_phone_held(self):
        self.assertTrue(ae.review([card(first="ZZTest")], TODAY)[1])
        self.assertTrue(ae.review([card(phone="+81392543647")], TODAY)[1])

    def test_short_parent_name_held(self):
        self.assertTrue(ae.review([card(pl="G")], TODAY)[1])

    def test_same_contact_split_across_centers_and_dup_first_name_held(self):
        cards = [card(first="Khy'Anna", loc="loc-1923-cecil-b-moore"),
                 {**card(first="Khy'Anna-Lewis", loc="loc-921-n-18th"), "card_id": "c1#1"},
                 {**card(first="Kha'Yr", loc="loc-921-n-18th"), "card_id": "c1#2"}]
        ready, held = ae.review(cards, TODAY)
        self.assertEqual((len(ready), len(held)), (0, 3))

    def test_siblings_at_one_center_are_fine(self):
        cards = [card(first="Ava"), {**card(first="Noah", dob="2020-05-05"), "card_id": "c1#1"}]
        self.assertEqual(len(ae.review(cards, TODAY)[0]), 2)

    def test_same_child_on_two_contacts_held(self):
        _, held = ae.review([card(cid="a"), card(cid="b", phone="+12155550999")], TODAY)
        self.assertEqual(len(held), 2)


class RunOnceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [mock.patch.object(ae, "STATE", Path(self.tmp.name) / "s.json"),
                        mock.patch.object(ae.daycare_ghl, "is_dismissed", return_value=False)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def _run(self, cards, enroll, text="0"):
        with mock.patch.dict("os.environ", {"FORGE_DAYCARE_AUTO_ENROLL_TEXT": text}), \
             mock.patch.object(ae.daycare_ghl, "pending_families", return_value=cards), \
             mock.patch.object(ae.daycare_login_queue, "enqueue", return_value={"ok": True}) as q:
            out = ae.run_once(object(), lambda: "sess", enroll)
        return out, q

    def test_enrolls_ready_card_and_holds_text_by_default(self):
        calls = []

        def enroll(session, family, text_login):
            calls.append((family["location_id"], text_login))
            return {"child": {"guardian_profile_id": "p1"}, "provision": {}}
        out, q = self._run([card()], enroll)
        self.assertEqual(out["enrolled"], ["Ava"])
        self.assertEqual(calls, [("44444444-4444-4444-4444-444444444444", False)])
        self.assertEqual(ae.view()["waiting_for_text"], 1)
        q.assert_not_called()

    def test_text_knob_on_hands_held_logins_to_queue(self):
        enroll = lambda s, f, t: {"child": {"guardian_profile_id": "p1"}, "provision": {"texted": {"queued": True}}}  # noqa: E731
        self._run([card()], lambda s, f, t: {"child": {"guardian_profile_id": "p1"}, "provision": {}})
        out, q = self._run([], enroll, text="1")
        q.assert_called_once()
        self.assertEqual(ae.view()["waiting_for_text"], 0)

    def test_failures_counted_and_give_up(self):
        def boom(s, f, t):
            raise RuntimeError("x")
        for _ in range(ae.MAX_TRIES):
            out, _ = self._run([card()], boom)
            self.assertEqual(out["failed"][0]["error"], "RuntimeError")
        out, _ = self._run([card()], boom)
        self.assertIn("gave up", out["failed"][0]["error"])

    def test_held_cards_never_enrolled(self):
        enroll = mock.Mock()
        out, _ = self._run([card(first="ZZTest")], enroll)
        enroll.assert_not_called()
        self.assertEqual(len(out["held"]), 1)

    def test_dry_run_changes_nothing(self):
        enroll = mock.Mock()
        with mock.patch.object(ae.daycare_ghl, "pending_families", return_value=[card()]):
            out = ae.run_once(object(), lambda: "s", enroll, dry_run=True)
        enroll.assert_not_called()
        self.assertEqual(out["would_enroll"], ["Ava (loc-1923-cecil-b-moore)"])


if __name__ == "__main__":
    unittest.main()
