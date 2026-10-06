"""Family Contact Form confirmation + multi-child cards (spec 2026-10-05). Pure — no I/O."""
import json
import unittest

import daycare_family_confirm as fc
import daycare_ghl as g
import daycare_replies as r

SENT = "2026-10-05T14:00:00+00:00"
T_SENT = 1791208800.0  # SENT as epoch seconds


def contact(tags=(), **cf):
    return {"id": "c1", "firstName": "maria", "lastName": "lopez", "email": "ana@x.com",
            "phone": "+12155550100", "tags": list(tags),
            "customFields": [{"id": k, "value": v} for k, v in cf.items()]}


def msg(body, t, direction="inbound"):
    from datetime import datetime, timezone
    return {"direction": direction, "messageType": "TYPE_SMS", "body": body,
            "dateAdded": datetime.fromtimestamp(t, tz=timezone.utc).isoformat()}


class Classify(unittest.TestCase):
    def test_plain_yeses(self):
        for b in ("YES", "yes!", "Y", "Yes it's correct", "yep", "Confirmed", "ok", "👍"):
            self.assertEqual(fc.classify(b), "yes", b)

    def test_hedged_or_other(self):
        for b in ("yes but my phone changed", "No that's wrong", "who is this?", "not yet"):
            self.assertEqual(fc.classify(b), "other", b)

    def test_stop(self):
        self.assertEqual(fc.classify("STOP"), "opt_out")


class Decide(unittest.TestCase):
    def c(self):
        return contact(tags=[fc.PENDING_TAG], **{fc.CF_CONFIRM_SENT: SENT})

    def test_yes_after_send_confirms(self):
        v = fc.decide(self.c(), [msg("Yes", T_SENT + 300)], T_SENT + 400)
        self.assertEqual(v["state"], "confirmed")

    def test_yes_before_send_is_ignored(self):
        v = fc.decide(self.c(), [msg("yes", T_SENT - 3600)], T_SENT + 400)
        self.assertEqual(v["state"], "waiting")

    def test_question_is_surfaced_not_confirmed(self):
        v = fc.decide(self.c(), [msg("what is this for?", T_SENT + 60)], T_SENT + 400)
        self.assertEqual((v["state"], v["reply"]), ("replied", "what is this for?"))

    def test_no_reply_after_48h(self):
        self.assertEqual(fc.decide(self.c(), [], T_SENT + 49 * 3600)["state"], "no_reply")

    def test_outbound_never_counts(self):
        v = fc.decide(self.c(), [msg("Reply YES to confirm", T_SENT + 1, "outbound")], T_SENT + 60)
        self.assertEqual(v["state"], "waiting")


class Cards(unittest.TestCase):
    def kids(self):
        return json.dumps([
            {"name": "Maria Lopez", "dob": "2022-01-01", "group": "Pre-K", "loc": "loc-921-n-18th", "shirt": "4T"},
            {"name": "Juan Lopez", "dob": "2024-05-05", "group": "Toddlers", "loc": "loc-1923-cecil-b-moore"},
        ])

    def test_one_card_per_child_with_own_key_and_location(self):
        c = contact(tags=["family-contact-form", "enrolled"], **{
            g.CF_PARENT_NAME: "Ana Lopez", g.CF_CHILD_NAME: "Maria Lopez, Juan Lopez",
            g.CF_CHILDREN_JSON: self.kids()})
        a, b = g.family_cards(c, now=T_SENT)
        self.assertEqual((a["card_id"], b["card_id"]), ("c1", "c1#1"))
        self.assertEqual((a["child_first"], b["child_first"]), ("Maria", "Juan"))
        self.assertEqual(b["location_tag"], "loc-1923-cecil-b-moore")
        self.assertEqual(b["classroom_label"], "Toddler")
        self.assertEqual(a["shirt_size"], "4T")
        self.assertTrue(a["ready"] and b["ready"])
        self.assertEqual(g.card_contact_id(b["card_id"]), "c1")

    def test_legacy_contact_is_one_card_exactly_as_before(self):
        c = contact(tags=["family-contact-form", "enrolled", "loc-921-n-18th"],
                    **{g.CF_PARENT_NAME: "Ana Lopez", g.CF_CHILD_NAME: "Maria Lopez"})
        cards = g.family_cards(c, now=T_SENT)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["card_id"], "c1")

    def test_readiness_lists_what_login_needs(self):
        c = contact(tags=["family-contact-form", "enrolled"], **{g.CF_PARENT_NAME: "Ana Lopez",
                                                                  g.CF_CHILD_NAME: "Maria"})
        c["email"] = ""
        card = g.family_cards(c, now=T_SENT)[0]
        self.assertFalse(card["ready"])
        self.assertIn("location", card["missing"])
        self.assertIn("parent email", card["missing"])

    def test_confirm_state(self):
        base = {g.CF_PARENT_NAME: "Ana", g.CF_CONFIRM_SENT: SENT}
        pend = g.family_cards(contact(tags=["family-contact-form", "family-confirm-pending"], **base), now=T_SENT + 60)[0]
        late = g.family_cards(contact(tags=["family-contact-form", "family-confirm-pending"], **base), now=T_SENT + 49 * 3600)[0]
        done = g.family_cards(contact(tags=["family-contact-form", "family-confirmed"], **base), now=T_SENT)[0]
        self.assertEqual((pend["confirm_state"], late["confirm_state"], done["confirm_state"]),
                         ("pending", "no_reply", "confirmed"))


class ReplyDeskHold(unittest.TestCase):
    def test_plain_yes_to_confirm_text_needs_no_draft(self):
        c = {"tags": ["family-confirm-pending"]}
        ok, code = r.gate(c, [msg("YES", T_SENT - 600)], T_SENT)
        self.assertEqual((ok, code), (False, "family_confirm"))

    def test_hedged_reply_still_reaches_the_desk(self):
        c = {"tags": ["family-confirm-pending"]}
        ok, code = r.gate(c, [msg("yes but my email changed", T_SENT - 600)], T_SENT)
        self.assertNotEqual(code, "family_confirm")


if __name__ == "__main__":
    unittest.main()
