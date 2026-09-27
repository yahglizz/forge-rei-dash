import time
import unittest
from unittest import mock

import daycare_supabase as daycare


LOCATION_ID = "11111111-1111-4111-8111-111111111111"
PROFILE_ID = "22222222-2222-4222-8222-222222222222"
CHILD_ID = "33333333-3333-4333-8333-333333333333"


class ETEveningClock(daycare.datetime):
    """01:30 UTC on Jan 2, 2030 = 8:30pm Jan 1 in Philadelphia (the box's UTC day is ahead)."""
    @classmethod
    def now(cls, tz=None):
        return daycare.datetime(2030, 1, 2, 1, 30, tzinfo=daycare.timezone.utc).astimezone(tz)


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

    def test_allow_http_is_loopback_only(self):
        # Without allow_http, plain HTTP from loopback is NOT secure.
        self.assertFalse(daycare.request_is_secure({}, "127.0.0.1"))
        with mock.patch.object(daycare, "CONFIG", config(allow_http=True)):
            # allow_http lets the loopback owner through over plain HTTP...
            self.assertTrue(daycare.request_is_secure({}, "127.0.0.1"))
            self.assertTrue(daycare.request_is_secure({}, "::1"))
            # ...but never a tailnet/public client.
            self.assertFalse(daycare.request_is_secure({}, "100.80.10.20"))

    def test_autoadmin_only_when_enabled_loopback_and_admin_configured(self):
        # Disabled by default → no auto session.
        bridge = daycare.SupabaseBridge(config())
        self.assertIsNone(bridge.autoadmin_session("127.0.0.1"))
        # Enabled but non-loopback → refused.
        enabled = config(
            autoadmin=True,
            test_profiles=(("admin", "BL-ADM-301", "123456"),),
        )
        bridge = daycare.SupabaseBridge(enabled)
        self.assertIsNone(bridge.autoadmin_session("100.80.10.20"))
        # Enabled + loopback + admin creds → mints once, then reuses the cached session.
        minted = session()
        with mock.patch.object(bridge, "login", return_value=(minted, {"role": "admin"})) as login:
            daycare._SESSIONS[minted.sid] = minted
            first = bridge.autoadmin_session("127.0.0.1")
            second = bridge.autoadmin_session("::1")
        self.assertIs(first, minted)
        self.assertIs(second, minted)
        login.assert_called_once_with("BL-ADM-301", "123456")

    def test_autoadmin_returns_none_when_no_admin_profile(self):
        enabled = config(autoadmin=True, test_profiles=(("manager", "BL-MGR-201", "123456"),))
        bridge = daycare.SupabaseBridge(enabled)
        self.assertIsNone(bridge.autoadmin_session("127.0.0.1"))

    def test_autoadmin_refuses_proxied_request(self):
        # Tailscale Serve fronts the box on 127.0.0.1 but always adds forwarding
        # headers. A loopback peer WITH proxy headers is a tailnet visitor, not the
        # SSH-tunnel owner → refused, even with autoadmin enabled + admin creds.
        enabled = config(autoadmin=True, test_profiles=(("admin", "BL-ADM-301", "123456"),))
        bridge = daycare.SupabaseBridge(enabled)
        minted = session()
        with mock.patch.object(bridge, "login", return_value=(minted, {"role": "admin"})):
            daycare._SESSIONS[minted.sid] = minted
            # Serve request (X-Forwarded-Proto set) → refused.
            self.assertIsNone(
                bridge.autoadmin_session("127.0.0.1", {"X-Forwarded-Proto": "https"}))
            self.assertIsNone(
                bridge.autoadmin_session("127.0.0.1", {"X-Forwarded-For": "100.80.10.20"}))
            # Direct tunnel (no forwarding headers) → still works.
            self.assertIs(bridge.autoadmin_session("127.0.0.1", {}), minted)

    def test_autoadmin_allows_proxied_request_when_open_access(self):
        # FORGE_DAYCARE_OPEN trades the daycare PIN for Tailscale device auth: a
        # Serve-fronted tailnet client is auto-admitted instead of refused. The
        # loopback-peer requirement is kept even then, so a raw non-Serve hit to
        # the dashboard port still falls through to the login.
        opened = config(autoadmin=True, open_access=True,
                        test_profiles=(("admin", "BL-ADM-301", "123456"),))
        bridge = daycare.SupabaseBridge(opened)
        minted = session()
        with mock.patch.object(bridge, "login", return_value=(minted, {"role": "admin"})):
            daycare._SESSIONS[minted.sid] = minted
            self.assertIs(
                bridge.autoadmin_session("127.0.0.1", {"X-Forwarded-Proto": "https"}),
                minted)
            # Not loopback (direct :7799 hit from a tailnet IP) → still refused.
            self.assertIsNone(
                bridge.autoadmin_session("100.80.10.20", {"X-Forwarded-Proto": "https"}))

    def test_is_owner_loopback_distinguishes_tunnel_from_serve(self):
        self.assertTrue(daycare.is_owner_loopback({}, "127.0.0.1"))
        self.assertTrue(daycare.is_owner_loopback({"User-Agent": "curl"}, "::1"))
        self.assertFalse(daycare.is_owner_loopback({"X-Forwarded-Proto": "https"}, "127.0.0.1"))
        self.assertFalse(daycare.is_owner_loopback({"Tailscale-User-Login": "a@b.c"}, "127.0.0.1"))
        self.assertFalse(daycare.is_owner_loopback({}, "100.80.10.20"))

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

    def test_enrollment_date_defaults_to_the_eastern_calendar_day(self):
        active = session()
        with mock.patch.object(daycare, "datetime", ETEveningClock), \
                mock.patch.object(daycare.BRIDGE, "rest", side_effect=lambda *a, **k: [k["body"]]) as rest:
            result = daycare.save_child(active, {"child": {
                "first_name": "Sam", "last_name": "Test", "birth_date": "2022-01-01"}})
        self.assertEqual("2030-01-01", rest.call_args.kwargs["body"]["enrollment_date"])
        self.assertEqual("2030-01-01", result["child"]["enrollment_date"])

    def test_child_update_keeps_the_stored_enrollment_date_unless_one_is_sent(self):
        active = session()
        child = {"first_name": "Sam", "last_name": "Test", "birth_date": "2022-01-01", "id": CHILD_ID}
        existing = {"id": CHILD_ID, "guardian_profile_id": PROFILE_ID}
        for sent, expected in ((None, None), ("2025-09-02", "2025-09-02")):
            body = dict(child, enrollment_date=sent) if sent else child
            with mock.patch.object(daycare, "_ensure_location_record", return_value=existing), \
                    mock.patch.object(daycare.BRIDGE, "rest", side_effect=lambda *a, **k: [k["body"]]) as rest:
                daycare.save_child(active, {"child": body})
            method, table = rest.call_args.args[1:3]
            self.assertEqual(("PATCH", "children"), (method, table))
            self.assertEqual(expected, rest.call_args.kwargs["body"].get("enrollment_date"))
            self.assertEqual(sent is not None, "enrollment_date" in rest.call_args.kwargs["body"])

    def test_behavior_move_defaults_to_the_eastern_calendar_day(self):
        active = session()
        with mock.patch.object(daycare, "datetime", ETEveningClock), \
                mock.patch.object(daycare, "_ensure_location_record", return_value={"id": CHILD_ID}), \
                mock.patch.object(daycare.BRIDGE, "rest", side_effect=lambda *a, **k: [k["body"]]) as rest:
            daycare.set_behavior(active, {"child_id": CHILD_ID, "color": "yellow"})
        self.assertEqual("2030-01-01", rest.call_args.kwargs["body"]["behavior_date"])

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

    # ── Blessing Coins ───────────────────────────────────────────────────────
    # The ledger rules the DB enforces (award>0, redemption<0, adjustment needs a
    # note) have to hold on the way IN too, or the owner gets a raw Postgres error
    # instead of a usable message. Balance is derived, never stored.

    def test_coin_balance_sums_the_whole_ledger_not_the_capped_feed(self):
        active = session()
        child_a = "66666666-6666-4666-8666-666666666666"
        child_b = "77777777-7777-4777-8777-777777777777"
        with mock.patch.object(
            daycare, "_child_ids", return_value=[child_a, child_b]
        ), mock.patch.object(
            daycare.BRIDGE,
            "rest",
            side_effect=[
                [{"id": "item-1", "name": "Cookies", "cost": 20, "active": True}],
                [  # full ledger — balances come from here
                    {"child_id": child_a, "amount": 10},
                    {"child_id": child_a, "amount": 15},
                    {"child_id": child_a, "amount": -20},
                    {"child_id": child_b, "amount": 5},
                ],
                [{"id": "tx-1", "child_id": child_a, "amount": -20}],  # capped feed
            ],
        ):
            result = daycare.get_rewards(active)
        self.assertEqual(5, result["balances"][child_a])
        self.assertEqual(5, result["balances"][child_b])
        self.assertEqual(4, result["ledgerCount"])
        self.assertEqual(1, len(result["coins"]))
        self.assertEqual(daycare.AWARD_REASONS, result["awardReasons"])

    def test_award_rejects_non_positive_amounts_and_requires_a_child(self):
        active = session()
        child_id = "66666666-6666-4666-8666-666666666666"
        with mock.patch.object(
            daycare, "_ensure_location_record",
            return_value={"id": child_id, "location_id": LOCATION_ID},
        ):
            for bad in (0, -5):
                with self.assertRaises(daycare.DaycareError) as rejected:
                    daycare.award_coins(active, {"child_ids": [child_id], "amount": bad,
                                                 "reason_label": "Sharing"})
                self.assertEqual(400, rejected.exception.status)
        with self.assertRaises(daycare.DaycareError) as empty:
            daycare.award_coins(active, {"child_ids": [], "amount": 5, "reason_label": "Sharing"})
        self.assertEqual(400, empty.exception.status)

    def test_award_writes_one_positive_row_per_child_with_the_actor(self):
        active = session()
        kids = ["66666666-6666-4666-8666-666666666666", "77777777-7777-4777-8777-777777777777"]
        with mock.patch.object(
            daycare, "_ensure_location_record",
            side_effect=[{"id": kid, "location_id": LOCATION_ID} for kid in kids],
        ), mock.patch.object(
            daycare.BRIDGE, "rest", return_value=[{"id": "tx"}]
        ) as rest:
            result = daycare.award_coins(active, {"child_ids": kids, "amount": 10,
                                                  "reason_label": "Sharing"})
        self.assertEqual(2, result["awarded"])
        self.assertEqual(2, rest.call_count)
        for call in rest.call_args_list:
            body = call.kwargs["body"]
            self.assertEqual("award", body["kind"])
            self.assertEqual(10, body["amount"])
            self.assertEqual(PROFILE_ID, body["actor_id"])

    def test_adjustment_requires_a_note_and_a_non_zero_amount(self):
        active = session()
        child_id = "66666666-6666-4666-8666-666666666666"
        with mock.patch.object(
            daycare, "_ensure_location_record",
            return_value={"id": child_id, "location_id": LOCATION_ID},
        ):
            with self.assertRaises(daycare.DaycareError) as no_note:
                daycare.adjust_coins(active, {"child_id": child_id, "amount": -5})
            self.assertEqual(400, no_note.exception.status)
            with self.assertRaises(daycare.DaycareError) as zero:
                daycare.adjust_coins(active, {"child_id": child_id, "amount": 0, "note": "typo"})
            self.assertEqual(400, zero.exception.status)

    def test_redemption_is_stored_negative_at_the_catalog_cost(self):
        active = session()
        child_id = "66666666-6666-4666-8666-666666666666"
        item_id = "88888888-8888-4888-8888-888888888888"
        with mock.patch.object(
            daycare, "_ensure_location_record",
            side_effect=[
                {"id": child_id, "location_id": LOCATION_ID},
                {"id": item_id, "name": "Cookies", "cost": 20},
            ],
        ), mock.patch.object(
            daycare.BRIDGE, "rest", return_value=[{"id": "tx"}]
        ) as rest:
            result = daycare.redeem_reward(active, {"child_id": child_id, "reward_item_id": item_id})
        body = rest.call_args.kwargs["body"]
        self.assertEqual("redemption", body["kind"])
        self.assertEqual(-20, body["amount"])
        self.assertEqual("Cookies", body["reason_label"])
        self.assertEqual(item_id, body["reward_item_id"])
        self.assertEqual(20, result["cost"])

    def test_retiring_a_prize_patches_active_and_never_deletes(self):
        active = session()
        item_id = "88888888-8888-4888-8888-888888888888"
        with mock.patch.object(
            daycare, "_ensure_location_record",
            return_value={"id": item_id, "name": "Cookies", "cost": 20, "active": True},
        ), mock.patch.object(
            daycare.BRIDGE, "rest", return_value=[{"id": item_id, "active": False}]
        ) as rest:
            daycare.set_reward_item_active(active, {"id": item_id, "active": False})
        self.assertEqual("PATCH", rest.call_args.args[1])
        self.assertEqual({"active": False}, rest.call_args.kwargs["body"])

    # ── Blessings Pass ───────────────────────────────────────────────────────
    def test_get_pass_reads_active_center_tables_then_leaderboard_rpc(self):
        active = session()
        season_id = "99999999-9999-4999-8999-999999999999"
        with mock.patch.object(
            daycare.BRIDGE, "rest",
            side_effect=[[{"id": season_id}], [{"id": "r1"}], [{"id": "k1"}], [{"id": "c1"}]],
        ) as rest, mock.patch.object(
            daycare.BRIDGE, "rpc", return_value=[{"child_id": "x", "days": 3}]
        ) as rpc:
            result = daycare.get_pass(active)
        calls = rest.call_args_list
        self.assertEqual(["pass_seasons", "pass_rewards", "pass_ranks", "pass_claims"],
                         [call.args[2] for call in calls])
        self.assertEqual({"GET"}, {call.args[1] for call in calls})
        self.assertEqual(f"eq.{LOCATION_ID}", calls[0].kwargs["query"]["location_id"])
        self.assertEqual(f"in.({season_id})", calls[1].kwargs["query"]["season_id"])
        self.assertEqual(f"eq.{LOCATION_ID}", calls[2].kwargs["query"]["location_id"])
        rpc.assert_called_once_with(active, "pass_leaderboard", {})
        self.assertEqual([{"child_id": "x", "days": 3}], result["leaderboard"])
        self.assertEqual(1, len(result["claims"]))

    def test_fulfill_pass_claim_calls_rpc_with_validated_id(self):
        active = session()
        claim_id = "99999999-9999-4999-8999-999999999999"
        with mock.patch.object(daycare.BRIDGE, "rpc", return_value={"id": claim_id}) as rpc:
            result = daycare.fulfill_pass_claim(active, {"claimId": claim_id})
            with self.assertRaises(daycare.DaycareError) as bad:
                daycare.fulfill_pass_claim(active, {"claim_id": "not-a-uuid"})
        rpc.assert_called_once_with(active, "fulfill_pass_claim", {"p_claim": claim_id})
        self.assertEqual({"ok": True, "claim": {"id": claim_id}}, result)
        self.assertEqual(400, bad.exception.status)



def http_error(status, payload):
    import io
    import json
    import urllib.error
    return urllib.error.HTTPError(
        "https://example.supabase.co/x", status, "err", {}, io.BytesIO(json.dumps(payload).encode()))


class DaycareTimesheetTests(unittest.TestCase):
    """Time sheets, paper key-in, pickup approval, CCIS, invoice periods (bridge mocked)."""
    ATTENDANCE_ID = "44444444-4444-4444-8444-444444444444"
    CLASSROOM_ID = "55555555-5555-4555-8555-555555555555"

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

    # --- invoice billing period -------------------------------------------------
    def _invoice(self, **extra):
        body = {"guardian_id": PROFILE_ID, "description": "Tuition", "amount": 100,
                "issued_on": "2026-10-01", "due_on": "2026-10-01", **extra}
        with mock.patch.object(daycare.BRIDGE, "rest",
                               side_effect=lambda *a, **k: [k["body"]] if a[1] == "POST" else [{"id": PROFILE_ID}]) as rest:
            daycare.save_invoice(session(), {"invoice": body})
        return rest.call_args.kwargs["body"]

    def test_invoice_period_is_optional_and_both_or_neither(self):
        self.assertNotIn("period_start", self._invoice())
        written = self._invoice(period_start="2026-09-01", period_end="2026-09-30")
        self.assertEqual(("2026-09-01", "2026-09-30"), (written["period_start"], written["period_end"]))
        cleared = self._invoice(period_start=None, period_end=None)
        self.assertEqual((None, None), (cleared["period_start"], cleared["period_end"]))
        for bad in ({"period_start": "2026-09-01"}, {"period_end": "2026-09-30"},
                    {"period_start": "2026-09-30", "period_end": "2026-09-01"},
                    {"period_start": "2026-09-01", "period_end": "September"}):
            with self.assertRaises(daycare.DaycareError) as error:
                self._invoice(**bad)
            self.assertEqual(400, error.exception.status, bad)

    # --- pickup decline ---------------------------------------------------------
    def _decline(self, record, ensure):
        with mock.patch.object(daycare.BRIDGE, "rest",
                               side_effect=lambda *a, **k: [record] if a[1] == "GET" else [dict(record, pickup_requested_at=None)]) as rest, \
                mock.patch.object(daycare, "_ensure_location_record", side_effect=ensure) as ensure_mock:
            try:
                return daycare.decline_pickup(session(), {"attendance_id": self.ATTENDANCE_ID}), rest, ensure_mock
            except daycare.DaycareError as error:
                return error, rest, ensure_mock

    def test_decline_pickup_clears_the_request_on_the_open_row(self):
        record = {"id": self.ATTENDANCE_ID, "child_id": CHILD_ID, "checked_out_at": None,
                  "pickup_requested_at": "2026-09-27T20:00:00Z"}
        result, rest, ensure = self._decline(record, lambda *a: {"id": CHILD_ID})
        ensure.assert_called_once_with(mock.ANY, "children", CHILD_ID)
        patch = rest.call_args
        self.assertEqual(("PATCH", "attendance"), patch.args[1:3])
        self.assertEqual({"pickup_requested_at": None}, patch.kwargs["body"])
        self.assertEqual({"id": f"eq.{self.ATTENDANCE_ID}", "checked_out_at": "is.null"}, patch.kwargs["query"])
        self.assertTrue(result["ok"])

    def test_decline_pickup_refuses_another_centers_child_and_rows_without_a_request(self):
        record = {"id": self.ATTENDANCE_ID, "child_id": CHILD_ID, "checked_out_at": None,
                  "pickup_requested_at": "2026-09-27T20:00:00Z"}

        def elsewhere(*_):
            raise daycare.DaycareError(404, "Children was not found", "not_found")
        error, rest, _ = self._decline(record, elsewhere)
        self.assertEqual(404, error.status)
        self.assertEqual(["GET"], [c.args[1] for c in rest.call_args_list])
        for closed in ({"pickup_requested_at": None}, {"checked_out_at": "2026-09-27T21:00:00Z"}):
            error, rest, _ = self._decline(dict(record, **closed), lambda *a: {"id": CHILD_ID})
            self.assertEqual(409, error.status)
            self.assertEqual(["GET"], [c.args[1] for c in rest.call_args_list])
        with self.assertRaises(daycare.DaycareError):
            daycare.decline_pickup(session(), {"attendance_id": "nope"})

    # --- paper key-in -----------------------------------------------------------
    def test_paper_entry_calls_the_rpc_with_wall_clock_times(self):
        row = {"id": self.ATTENDANCE_ID, "source": "paper"}
        with mock.patch.object(daycare, "_ensure_location_record", return_value={"id": CHILD_ID}) as ensure, \
                mock.patch.object(daycare.BRIDGE, "rpc", return_value=row) as rpc:
            result = daycare.record_paper_attendance(session(), {
                "child_id": CHILD_ID, "date": "2026-09-26", "time_in": "07:45:00", "time_out": "16:30", "note": "  "})
            daycare.record_paper_attendance(session(), {
                "child_id": CHILD_ID, "date": "2026-09-26", "time_in": "07:45", "time_out": ""})
        ensure.assert_called_with(mock.ANY, "children", CHILD_ID)
        first, second = rpc.call_args_list
        self.assertEqual(("record_paper_attendance", {"p_child": CHILD_ID, "p_date": "2026-09-26",
                                                       "p_in": "07:45", "p_out": "16:30", "p_note": None}), first.args[1:])
        self.assertEqual(None, second.args[2]["p_out"])
        self.assertTrue(first.kwargs["surface_errors"])
        self.assertEqual(row, result["attendance"])
        with mock.patch.object(daycare, "_ensure_location_record", return_value={"id": CHILD_ID}):
            for bad in ({"time_in": "7am"}, {"time_in": "07:45", "time_out": "25:00"}, {"time_in": "07:45", "date": None}):
                with self.assertRaises(daycare.DaycareError) as error:
                    daycare.record_paper_attendance(session(), {"child_id": CHILD_ID, "date": "2026-09-26", **bad})
                self.assertEqual(400, error.exception.status)

    def test_rpc_surfaces_the_databases_own_sentence_only_when_asked(self):
        bridge = daycare.BRIDGE
        refusal = {"code": "23505", "message": "This day is already recorded in the app. Use Close record to correct the pickup."}
        with mock.patch.object(bridge, "_urlopen_json", side_effect=lambda *a, **k: (_ for _ in ()).throw(http_error(409, refusal))):
            with self.assertRaises(daycare.DaycareError) as shown:
                bridge.rpc(session(), "record_paper_attendance", {}, surface_errors=True)
            with self.assertRaises(daycare.DaycareError) as hidden:
                bridge.rpc(session(), "record_paper_attendance", {})
        self.assertEqual((409, refusal["message"]), (shown.exception.status, shown.exception.message))
        self.assertEqual("That daycare record conflicts with an existing record", hidden.exception.message)
        internal = {"code": "XX000", "message": "relation secret_table does not exist"}
        with mock.patch.object(bridge, "_urlopen_json", side_effect=lambda *a, **k: (_ for _ in ()).throw(http_error(400, internal))):
            with self.assertRaises(daycare.DaycareError) as generic:
                bridge.rpc(session(), "record_paper_attendance", {}, surface_errors=True)
        self.assertNotIn("secret_table", generic.exception.message)

    def test_postgres_own_errors_with_our_codes_stay_generic(self):
        bridge = daycare.BRIDGE
        builtin = {"code": "23505", "message": 'duplicate key value violates unique constraint "attendance_child_id_attendance_date_key"'}
        with mock.patch.object(bridge, "_urlopen_json", side_effect=lambda *a, **k: (_ for _ in ()).throw(http_error(409, builtin))):
            with self.assertRaises(daycare.DaycareError) as hidden:
                bridge.rpc(session(), "record_paper_attendance", {}, surface_errors=True)
        self.assertNotIn("attendance_child_id", hidden.exception.message)

    def test_check_out_keeps_notes_and_needs_a_real_time_for_a_past_day(self):
        open_row = [{"id": self.ATTENDANCE_ID, "checked_out_at": None}]
        calls = []
        def rest(*args, **kwargs):
            calls.append((args, kwargs))
            return open_row if args[1] == "GET" else [{"id": self.ATTENDANCE_ID}]
        with mock.patch.object(daycare, "_ensure_location_record", return_value={"id": CHILD_ID}), \
                mock.patch.object(daycare, "_today_et", return_value=daycare.date(2026, 9, 27)), \
                mock.patch.object(daycare.BRIDGE, "rest", side_effect=rest):
            daycare.set_attendance(session(), {"child_id": CHILD_ID, "date": "2026-09-27", "action": "check-out"})
            self.assertNotIn("notes", calls[-1][1]["body"], "a check-out must not blank the custody trail")
            with self.assertRaises(daycare.DaycareError) as missing:
                daycare.set_attendance(session(), {"child_id": CHILD_ID, "date": "2026-09-25", "action": "check-out"})
            self.assertEqual(400, missing.exception.status)
            daycare.set_attendance(session(), {"child_id": CHILD_ID, "date": "2026-09-25", "action": "check-out", "time": "17:15"})
            self.assertEqual("2026-09-25T17:15:00-04:00", calls[-1][1]["body"]["checked_out_at"])

    # --- time sheets ------------------------------------------------------------
    def test_timesheets_passes_the_request_to_the_function(self):
        sheet = {"location": {"id": LOCATION_ID, "name": "ATOB", "full_day_hours": 5}, "classrooms": [], "totals": {}}
        with mock.patch.object(daycare.BRIDGE, "edge_function", return_value=sheet) as edge:
            result = daycare.get_timesheets(session(), {
                "mode": "summary", "start": "2026-09-01", "end": "2026-09-30",
                "classroom_id": self.CLASSROOM_ID, "group": "ccis"})
            daycare.get_timesheets(session(), {"mode": "blank", "date": "2026-09-28", "classroom_id": None})
        summary, blank = edge.call_args_list
        self.assertEqual(("timesheets", {"mode": "summary", "classroom_id": self.CLASSROOM_ID,
                                         "start": "2026-09-01", "end": "2026-09-30", "group": "ccis"}), summary.args[1:])
        self.assertEqual({"mode": "blank", "classroom_id": None, "date": "2026-09-28"}, blank.args[2])
        self.assertTrue(summary.kwargs["surface_errors"])
        self.assertEqual({"ok": True, **sheet}, result)
        for bad in ({"mode": "csv"}, {"mode": "pdf", "start": "2026-09-01", "end": "x"},
                    {"mode": "summary", "start": "2026-09-01", "end": "2026-09-30", "group": "vip"},
                    {"mode": "summary", "start": "2026-09-01", "end": "2026-09-30", "classroom_id": "room"}):
            with self.assertRaises(daycare.DaycareError) as error:
                daycare.get_timesheets(session(), bad)
            self.assertEqual(400, error.exception.status)

    def test_timesheets_surfaces_the_functions_error_but_provisioning_stays_generic(self):
        bridge = daycare.BRIDGE
        too_long = {"error": "Pick a range of 62 days or fewer."}
        with mock.patch.object(bridge, "_urlopen_json", side_effect=lambda *a, **k: (_ for _ in ()).throw(http_error(400, too_long))):
            with self.assertRaises(daycare.DaycareError) as shown:
                daycare.get_timesheets(session(), {"mode": "summary", "start": "2026-01-01", "end": "2026-09-30"})
            with self.assertRaises(daycare.DaycareError) as provision:
                bridge.edge_function(session(), "provision-user", {"action": "ensure-guardian"})
        self.assertEqual((400, too_long["error"]), (shown.exception.status, shown.exception.message))
        self.assertEqual((400, "The daycare request was not accepted"), (provision.exception.status, provision.exception.message))
        with mock.patch.object(bridge, "_urlopen_json", return_value={"error": "Only management can run time sheets"}):
            with self.assertRaises(daycare.DaycareError) as ok_error:
                bridge.edge_function(session(), "timesheets", {}, surface_errors=True)
            with self.assertRaises(daycare.DaycareError) as provision_ok_error:
                bridge.edge_function(session(), "provision-user", {})
        self.assertEqual("Only management can run time sheets", ok_error.exception.message)
        self.assertEqual("Daycare account provisioning failed", provision_ok_error.exception.message)

    def test_full_day_hours_is_one_to_twelve_on_the_active_center(self):
        with mock.patch.object(daycare.BRIDGE, "rest", side_effect=lambda *a, **k: [dict(k["body"], id=LOCATION_ID)]) as rest:
            result = daycare.save_full_day_hours(session(), {"full_day_hours": "6.5"})
            for bad in (0, 12.5, "", None, "five"):
                with self.assertRaises(daycare.DaycareError):
                    daycare.save_full_day_hours(session(), {"full_day_hours": bad})
        self.assertEqual(1, rest.call_count)
        self.assertEqual(("PATCH", "locations"), rest.call_args.args[1:3])
        self.assertEqual({"id": f"eq.{LOCATION_ID}"}, rest.call_args.kwargs["query"])
        self.assertEqual({"ok": True, "full_day_hours": 6.5}, result)

    # --- CCIS on the child ------------------------------------------------------
    def test_child_ccis_is_written_only_when_sent_and_validated(self):
        base = {"first_name": "Sam", "last_name": "Test", "birth_date": "2022-01-01"}
        with mock.patch.object(daycare.BRIDGE, "rest", side_effect=lambda *a, **k: [k["body"]]) as rest:
            daycare.save_child(session(), {"child": base})
            self.assertNotIn("ccis", rest.call_args.kwargs["body"])
            self.assertNotIn("ccis_case_id", rest.call_args.kwargs["body"])
            daycare.save_child(session(), {"child": dict(base, ccis=True, ccis_case_id="  CW-1234  ")})
            self.assertEqual((True, "CW-1234"), (rest.call_args.kwargs["body"]["ccis"], rest.call_args.kwargs["body"]["ccis_case_id"]))
            daycare.save_child(session(), {"child": dict(base, ccis=False, ccis_case_id="")})
            self.assertEqual((False, None), (rest.call_args.kwargs["body"]["ccis"], rest.call_args.kwargs["body"]["ccis_case_id"]))
            for bad in ({"ccis": "yes"}, {"ccis_case_id": "X" * 41}):
                with self.assertRaises(daycare.DaycareError) as error:
                    daycare.save_child(session(), {"child": dict(base, **bad)})
                self.assertEqual(400, error.exception.status)


if __name__ == "__main__":
    unittest.main()
