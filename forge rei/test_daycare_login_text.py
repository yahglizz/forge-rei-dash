"""Create login -> the parent gets their sign-in by text. No network: GHL send is mocked."""
import unittest
from unittest import mock

import connector
import daycare_ghl
import daycare_replies

ATOB = "11111111-1111-1111-1111-111111111111"
AMT = "44444444-4444-4444-4444-444444444444"


class LoginTextCopyTests(unittest.TestCase):
    def test_atob_copy_and_link(self):
        self.assertEqual(
            daycare_ghl.login_text("Jasmine", "Mu'nir", "Jasmine Smith", "482913", ATOB),
            "Hi Jasmine! Mu'nir's A Touch of Blessings family app is ready.\n"
            "Sign in with your name: Jasmine Smith\n"
            "PIN: 482913\n"
            "Get the app: https://atouchofblessing.com/get-app\n"
            "Keep your PIN private. Questions? Just ask a staff member.")

    def test_unknown_location_defaults_to_atob(self):
        text = daycare_ghl.login_text("Jasmine", "Mu'nir", "Jasmine Smith", "482913", None)
        self.assertIn("A Touch of Blessings family app", text)
        self.assertIn("https://atouchofblessing.com/get-app\n", text)

    def test_mothers_touch_copy_and_link(self):
        text = daycare_ghl.login_text("Jasmine", "Mu'nir", "Jasmine Smith", "482913", AMT)
        self.assertIn("Mu'nir's A Mother's Touch family app is ready.", text)
        self.assertIn("Get the app: https://atouchofblessing.com/get-app-mothers-touch\n", text)
        self.assertNotIn("A Touch of Blessings", text)

    def test_missing_names_read_naturally(self):
        for parent, child in ((None, None), ("", "  "), ("I", "J")):
            text = daycare_ghl.login_text(parent, child, "Jasmine Smith", "482913", ATOB)
            self.assertTrue(text.startswith("Hi there! Your child's A Touch of Blessings"), text)

    def test_longest_possible_message_fits_manual_limit(self):
        # save_child caps names at 100 chars; the sign-in name is first + last.
        text = daycare_ghl.login_text("P" * 100, "C" * 100, "P" * 100 + " " + "L" * 100, "123456", AMT)
        self.assertLessEqual(len(text), daycare_replies.MANUAL_MAX_CHARS)


class EnrollTextsParentTests(unittest.TestCase):
    FAMILY = {"contact_id": "contact-1", "parent_first": "Jasmine", "parent_last": "Smith",
              "child_first": "Mu'nir", "email": "jasmine@example.com", "location_id": AMT}

    def enroll(self, provision, send):
        handler = object.__new__(connector.Handler)
        handler._daycare_family_child_body = lambda _s, fam: {
            "first_name": fam["child_first"], "last_name": "Smith", "location_id": fam["location_id"]}
        saved = {"ok": True, "child": {"id": "child-1"}}
        if provision is not None:
            saved["provision"] = provision
        handler._daycare_child_save = mock.Mock(return_value=saved)
        with mock.patch.object(connector.daycare_ghl, "form_child_id", return_value="child-1"), \
                mock.patch.object(connector.daycare_ghl, "record_form_child"), \
                mock.patch.object(connector.daycare_ghl, "dismiss", return_value={"ok": True}), \
                mock.patch.object(connector.daycare_replies, "send_manual", **send) as send_manual:
            result = connector.Handler._daycare_ghl_enroll(handler, None, {"family": dict(self.FAMILY)})
        return result, send_manual

    def test_new_login_is_texted_to_the_form_contact(self):
        result, send_manual = self.enroll(
            {"profile_id": "p1", "login_id": "Jasmine Smith", "pin": "482913"},
            {"return_value": {"ok": True, "sent": True}})
        send_manual.assert_called_once()
        client, contact_id, text = send_manual.call_args.args
        self.assertIs(client, connector.DAYCARE_GHL)
        self.assertEqual("contact-1", contact_id)
        self.assertEqual(text, daycare_ghl.login_text("Jasmine", "Mu'nir", "Jasmine Smith", "482913", AMT))
        self.assertEqual({"ok": True, "error": None}, result["provision"]["texted"])
        self.assertEqual({"ok": True}, result["dismissed"])

    def test_existing_account_without_pin_is_not_texted(self):
        result, send_manual = self.enroll(
            {"profile_id": "p1", "login_id": "Jasmine Smith", "existing": True},
            {"return_value": {"ok": True}})
        send_manual.assert_not_called()
        self.assertNotIn("texted", result["provision"])

    def test_no_login_created_is_not_texted(self):
        result, send_manual = self.enroll(None, {"return_value": {"ok": True}})
        send_manual.assert_not_called()
        self.assertNotIn("provision", result)

    def test_refused_send_is_reported_and_enroll_still_succeeds(self):
        result, _ = self.enroll(
            {"login_id": "Jasmine Smith", "pin": "482913"},
            {"return_value": {"ok": False, "error": "outside 8am–9pm ET texting window — send after 8am"}})
        self.assertTrue(result["ok"])
        self.assertEqual({"ok": False, "error": "outside 8am–9pm ET texting window — send after 8am"},
                         result["provision"]["texted"])

    def test_send_that_raises_never_fails_the_enroll_or_leaks_detail(self):
        result, _ = self.enroll(
            {"login_id": "Jasmine Smith", "pin": "482913"},
            {"side_effect": RuntimeError("Bearer secret-token 500")})
        self.assertTrue(result["ok"])
        self.assertEqual({"id": "child-1"}, result["child"])
        self.assertEqual({"ok": False, "error": "GHL send failed: RuntimeError"}, result["provision"]["texted"])


if __name__ == "__main__":
    unittest.main()
