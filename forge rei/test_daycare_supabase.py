import time
import unittest
from unittest import mock

import daycare_supabase as daycare


LOCATION_ID = "11111111-1111-4111-8111-111111111111"
PROFILE_ID = "22222222-2222-4222-8222-222222222222"


def config(**overrides):
    values = {
        "url": "https://example.supabase.co",
        "publishable_key": "publishable-test-key",
        "location_id": LOCATION_ID,
        "login_domain": "login.blessings.app",
        "live": True,
        "writes_enabled": True,
        "allow_http": False,
        "allowed_origins": ("https://forge-reios.tail0a2dda.ts.net",),
    }
    values.update(overrides)
    return daycare.DaycareConfig(**values)


def session(**overrides):
    now = time.time()
    values = {
        "sid": "session_id_abcdefghijklmnopqrstuvwxyz0123456789",
        "access_token": "server-only-access-token",
        "refresh_token": "server-only-refresh-token",
        "token_expires_at": now + 1800,
        "created_at": now,
        "absolute_expires_at": now + 3600,
        "idle_expires_at": now + 900,
        "profile_checked_at": now,
        "profile": {
            "id": PROFILE_ID,
            "location_id": LOCATION_ID,
            "role": "manager",
            "active": True,
            "display_name": "Test Manager",
        },
    }
    values.update(overrides)
    return daycare.Session(**values)


class DaycareSecurityTests(unittest.TestCase):
    def setUp(self):
        daycare.clear_sessions()
        self.original_config = daycare.CONFIG
        self.original_bridge = daycare.BRIDGE
        daycare.CONFIG = config()
        daycare.BRIDGE = daycare.SupabaseBridge(daycare.CONFIG)

    def tearDown(self):
        daycare.clear_sessions()
        daycare.CONFIG = self.original_config
        daycare.BRIDGE = self.original_bridge

    def test_config_requires_location_and_never_needs_service_role(self):
        self.assertTrue(config().configured)
        self.assertFalse(config(location_id="").configured)
        self.assertFalse(hasattr(config(), "service_role_key"))

    def test_cookie_is_opaque_secure_http_only_and_strict(self):
        value = daycare.session_cookie("opaque_session_value_abcdefghijklmnopqrstuvwxyz")
        self.assertIn("Secure", value)
        self.assertIn("HttpOnly", value)
        self.assertIn("SameSite=Strict", value)
        self.assertNotIn("access-token", value)
        self.assertNotIn("refresh-token", value)
        self.assertEqual(
            daycare.session_id_from_cookie(value),
            "opaque_session_value_abcdefghijklmnopqrstuvwxyz",
        )

    def test_forwarded_https_only_trusted_from_loopback(self):
        headers = {"X-Forwarded-Proto": "https"}
        self.assertTrue(daycare.request_is_secure(headers, "127.0.0.1"))
        self.assertTrue(daycare.request_is_secure(headers, "::1"))
        self.assertFalse(daycare.request_is_secure(headers, "100.80.10.20"))
        self.assertFalse(daycare.request_is_secure({}, "127.0.0.1"))

    def test_write_origin_is_exact_and_required(self):
        headers = {
            "X-Forwarded-Proto": "https",
            "Origin": "https://forge-reios.tail0a2dda.ts.net",
        }
        daycare.validate_write_request(headers, "127.0.0.1")
        with self.assertRaises(daycare.DaycareError) as rejected:
            daycare.validate_write_request(
                {**headers, "Origin": "https://evil.example"}, "127.0.0.1"
            )
        self.assertEqual(rejected.exception.status, 403)

    def test_session_idle_and_absolute_expiry_return_401(self):
        expired = session(idle_expires_at=time.time() - 1)
        daycare._SESSIONS[expired.sid] = expired
        with self.assertRaises(daycare.DaycareError) as error:
            daycare.BRIDGE.require_session(expired.sid)
        self.assertEqual(error.exception.status, 401)
        self.assertNotIn(expired.sid, daycare._SESSIONS)

    def test_login_returns_public_profile_but_keeps_jwts_server_side(self):
        bridge = daycare.BRIDGE
        auth_payload = {
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
            "expires_in": 3600,
            "user": {"id": PROFILE_ID},
        }
        profile_rows = [{
            "id": PROFILE_ID,
            "location_id": LOCATION_ID,
            "role": "admin",
            "active": True,
            "display_name": "Admin User",
        }]
        with mock.patch.object(
            bridge, "_urlopen_json", side_effect=[auth_payload, profile_rows]
        ):
            created, public = bridge.login("BL-ADM-001", "123456")
        self.assertEqual(public["role"], "admin")
        self.assertNotIn("access_token", public)
        self.assertNotIn("refresh_token", public)
        self.assertEqual(daycare._SESSIONS[created.sid].access_token, "access-secret")
        self.assertNotIn("access-secret", daycare.session_cookie(created.sid))

    def test_test_profile_login_needs_private_flag_and_mapping(self):
        bridge = daycare.SupabaseBridge(config())
        with self.assertRaises(daycare.DaycareError) as disabled:
            bridge.login_test_profile("admin")
        self.assertEqual(disabled.exception.status, 403)
        test_config = config(
            test_mode=True,
            test_profiles=(("admin", "BL-ADM-301", "123456"),),
        )
        bridge = daycare.SupabaseBridge(test_config)
        expected = (session(), {"role": "admin"})
        with mock.patch.object(bridge, "login", return_value=expected) as login:
            self.assertEqual(bridge.login_test_profile("admin"), expected)
        login.assert_called_once_with("BL-ADM-301", "123456")
        with self.assertRaises(daycare.DaycareError) as missing:
            bridge.login_test_profile("manager")
        self.assertEqual(missing.exception.status, 403)

    def test_parent_and_wrong_location_cannot_login_to_forge(self):
        bridge = daycare.BRIDGE
        with self.assertRaises(daycare.DaycareError) as role_error:
            bridge._authorize_profile({
                "id": PROFILE_ID, "active": True, "role": "parent",
                "location_id": LOCATION_ID,
            })
        self.assertEqual(role_error.exception.status, 403)
        with self.assertRaises(daycare.DaycareError) as location_error:
            bridge._authorize_profile({
                "id": PROFILE_ID, "active": True, "role": "manager",
                "location_id": "33333333-3333-4333-8333-333333333333",
            })
        self.assertEqual(location_error.exception.code, "location_mismatch")

    def test_validation_rejects_bad_ids_ranges_and_storage_traversal(self):
        for callback in (
            lambda: daycare.require_uuid("not-a-uuid"),
            lambda: daycare.require_date("07/14/2026", "date"),
            lambda: daycare.require_number("nan", "amount"),
            lambda: daycare.validate_storage_path("child/../secret"),
        ):
            with self.assertRaises(daycare.DaycareError) as error:
                callback()
            self.assertEqual(error.exception.status, 400)

    def test_nested_ui_log_payload_is_accepted(self):
        active = session()
        log = {
            "child_id": "33333333-3333-4333-8333-333333333333",
            "log_date": "2026-07-14",
            "occurred_at": "2026-07-14T09:30",
            "activity": "Reading",
            "nap_minutes": None,
        }
        with mock.patch.object(
            daycare, "_ensure_location_record", return_value={"id": log["child_id"]}
        ), mock.patch.object(
            daycare.BRIDGE, "rest", return_value=[{"id": "log-id", **log}]
        ) as rest:
            result = daycare.save_log(active, {"log": log})
        self.assertTrue(result["ok"])
        self.assertIsNone(rest.call_args.kwargs["body"]["nap_minutes"])

    def test_nested_payment_payload_maps_to_atomic_rpc(self):
        active = session()
        invoice_id = "44444444-4444-4444-8444-444444444444"
        with mock.patch.object(
            daycare, "_ensure_location_record", return_value={"id": invoice_id}
        ), mock.patch.object(
            daycare.BRIDGE, "rpc", return_value={"id": "payment-id"}
        ) as rpc:
            result = daycare.record_invoice_payment(active, {
                "invoice_id": invoice_id,
                "payment": {"amount": 25, "method_label": "Cash", "provider": "manual"},
            })
        self.assertEqual(result["payment"]["id"], "payment-id")
        self.assertEqual(rpc.call_args.args[1], "record_invoice_payment")
        self.assertEqual(rpc.call_args.args[2]["p_amount"], 25.0)

    def test_message_upload_generates_policy_scoped_path_and_top_level_url(self):
        active = session()
        thread_id = "55555555-5555-4555-8555-555555555555"
        with mock.patch.object(
            daycare, "_ensure_location_record", return_value={"id": thread_id}
        ), mock.patch.object(
            daycare.BRIDGE,
            "storage_sign",
            side_effect=lambda _session, bucket, path, upload: {
                "bucket": bucket,
                "path": path,
                "signedUrl": "https://upload.example/signed",
                "token": "signed-upload-token",
            },
        ):
            result = daycare.sign_media(active, {
                "purpose": "message",
                "thread_id": thread_id,
                "filename": "family note.pdf",
                "content_type": "application/pdf",
            }, upload=True)
        self.assertEqual(result["upload_url"], "https://upload.example/signed")
        self.assertTrue(result["path"].startswith(f"chat/{thread_id}/"))
        self.assertNotIn(" ", result["path"])

    def test_signed_read_infers_message_bucket_from_path(self):
        active = session()
        thread_id = "66666666-6666-4666-8666-666666666666"
        with mock.patch.object(
            daycare, "_ensure_location_record", return_value={"id": thread_id}
        ), mock.patch.object(
            daycare.BRIDGE,
            "storage_sign",
            return_value={
                "bucket": "message-attachments",
                "path": f"chat/{thread_id}/note.pdf",
                "signedUrl": "https://read.example/signed",
                "token": None,
            },
        ):
            result = daycare.sign_media(
                active, {"path": f"chat/{thread_id}/note.pdf"}, upload=False)
        self.assertEqual(result["url"], "https://read.example/signed")

    def test_new_child_cannot_silently_drop_entered_guardian_details(self):
        active = session()
        with self.assertRaises(daycare.DaycareError) as error:
            daycare.save_child(active, {
                "child": {
                    "first_name": "Sam",
                    "last_name": "Test",
                    "birth_date": "2022-01-01",
                    "guardian_first_name": "Alex",
                    "guardian_last_name": "Test",
                },
            })
        self.assertEqual(error.exception.status, 400)
        self.assertIn("guardian_email", error.exception.message)

    def test_staff_edit_preserves_nested_profile_role_when_ui_omits_role(self):
        active = session(profile={
            "id": PROFILE_ID,
            "location_id": LOCATION_ID,
            "role": "admin",
            "active": True,
        })
        staff_id = "77777777-7777-4777-8777-777777777777"
        target_profile_id = "88888888-8888-4888-8888-888888888888"
        with mock.patch.object(
            daycare,
            "_ensure_location_record",
            return_value={"id": staff_id, "profile_id": target_profile_id},
        ), mock.patch.object(
            daycare.BRIDGE,
            "rest",
            side_effect=[
                [{"id": target_profile_id, "role": "admin", "active": True}],
                [{"id": target_profile_id, "role": "admin"}],
                [{"id": staff_id, "profile_id": target_profile_id}],
            ],
        ) as rest:
            result = daycare.save_staff(active, {
                "staff": {
                    "id": staff_id,
                    "first_name": "Avery",
                    "last_name": "Director",
                    "job_title": "Director",
                    "hourly_rate": 40,
                },
            })
        self.assertTrue(result["ok"])
        profile_patch = rest.call_args_list[1]
        self.assertEqual(profile_patch.kwargs["body"]["role"], "admin")

    def test_thread_response_contains_ui_sender_and_participant_aliases(self):
        active = session()
        thread_id = "99999999-9999-4999-8999-999999999999"
        message_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        with mock.patch.object(
            daycare, "_ensure_location_record", return_value={"id": thread_id, "title": "Family"}
        ), mock.patch.object(
            daycare.BRIDGE,
            "rest",
            side_effect=[
                [{
                    "id": message_id,
                    "sender_id": PROFILE_ID,
                    "profiles": {"first_name": "Test", "last_name": "Manager"},
                }],
                [{"thread_id": thread_id, "profile_id": PROFILE_ID}],
            ],
        ):
            result = daycare.get_thread(active, thread_id)
        self.assertTrue(result["thread"]["messages"][0]["mine"])
        self.assertEqual(result["thread"]["messages"][0]["sender_name"], "Test Manager")
        self.assertEqual(
            result["thread"]["thread_participants"], result["thread"]["participants"])


if __name__ == "__main__":
    unittest.main()
