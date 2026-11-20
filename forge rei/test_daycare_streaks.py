"""On-time payment streaks, dash side: Slack feed (format, routing, dedupe, stamp-after-send, inert
switches), invoice discount (math, description, fail-open), and the Billing reads. All fakes, no network.
Run: FORGE_MARCUS=0 python3 -m unittest test_daycare_streaks  (from `forge rei/`)."""
import os
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

if "slack_io" not in sys.modules:
    os.environ["FORGE_SLACK_CONFIG_DIR"] = tempfile.mkdtemp(prefix="slack_cfg_")

import daycare_billing_link as bl  # noqa: E402
import daycare_streak_slack as feed  # noqa: E402
import daycare_supabase as daycare  # noqa: E402
import slack_io  # noqa: E402

PAY, DAYCARE = "CPAY001", "CDAY001"
ATOB = "11111111-1111-1111-1111-111111111111"
AMT = "44444444-4444-4444-4444-444444444444"
GUARDIAN = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
INVOICE = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def event(eid="e1", **over):
    row = {"id": eid, "invoice_id": INVOICE, "guardian_id": GUARDIAN, "location_id": ATOB,
           "parent_name": "Dana Smith", "paid_amount": 215, "click_at": "2026-11-16T15:00:00Z",
           "due_on": "2026-11-16", "week_of": "2026-11-16", "on_time": True, "streak_after": 4,
           "tier_pct_after": 0, "slack_eligible": True, "slack_posted_at": None}
    row.update(over)
    return row


def session(location=ATOB):
    return daycare.Session(sid="s", access_token="t", refresh_token="r", token_expires_at=9e12, created_at=0,
                           absolute_expires_at=9e12, idle_expires_at=9e12, profile_checked_at=9e12,
                           profile={"id": "p1", "location_id": location, "role": "admin"})


class MessageTests(unittest.TestCase):
    def test_on_time_line_names_the_next_milestone(self):
        self.assertEqual(feed.compose(event()),
                         "Payment confirmed — Dana Smith — $215.00 — week of Nov 16 — streak 4 (next: 10% at 6)")
        self.assertEqual(feed.compose(event(streak_after=6, tier_pct_after=10, paid_amount="1,5".replace(",", ""))),
                         "Payment confirmed — Dana Smith — $15.00 — week of Nov 16 — streak 6 (next: 25% at 15)")

    def test_top_tier_has_no_next(self):
        self.assertEqual(feed.compose(event(streak_after=15, tier_pct_after="25.00", paid_amount="1234.5")),
                         "Payment confirmed — Dana Smith — $1,234.50 — week of Nov 16 — streak 15 (top tier: 25%)")

    def test_center_tiers_replace_the_defaults(self):
        self.assertIn("(next: 5% at 5)", feed.compose(event(), [(5, Decimal("5.00")), (9, Decimal("12.5"))]))
        self.assertIn("(next: 12.5% at 9)", feed.compose(event(streak_after=5), [(9, Decimal("12.5")), (5, 5)]))

    def test_late_and_missed_lines(self):
        self.assertEqual(feed.compose(event(on_time=False, streak_after=0, week_of="2026-11-02")),
                         "Late payment — Dana Smith — $215.00 — week of Nov 2 — streak reset to 0")
        self.assertEqual(feed.compose(event(on_time=False, streak_after=0, paid_amount=None)),
                         "Missed payment — Dana Smith — week of Nov 16 — streak reset to 0")

    def test_parent_name_only_escaped_and_never_a_child(self):
        line = feed.compose(event(parent_name="Dana <b>& Co</b>", child_name="Maya", child={"first_name": "Maya"}))
        self.assertIn("Dana &lt;b&gt;&amp; Co&lt;/b&gt;", line)
        self.assertNotIn("Maya", line)
        self.assertIn("A family", feed.compose(event(parent_name=" ")))

    def test_week_falls_back_to_the_due_date(self):
        self.assertIn("week of Nov 16", feed.compose(event(week_of=None)))
        self.assertIn("week of unknown", feed.compose(event(week_of=None, due_on=None)))


class FeedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.api, self.rpcs, self.rows, self.mark_fails = [], [], [event()], False
        env = {k: v for k, v in os.environ.items() if not k.startswith("SLACK_") and k != "FORGE_CHAT_TRANSPORT"}
        env.update({"SLACK_BOT_TOKEN": "xoxb-test", "FORGE_CHAT_TRANSPORT": "both",
                    "SLACK_CHANNEL_DAYCARE": DAYCARE, "SLACK_CHANNEL_DAYCARE_PAYMENTS": PAY})
        self.patches = [
            mock.patch.object(slack_io, "STATE", Path(self.tmp.name)),
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(slack_io, "_api", self._fake_api),
            mock.patch.object(daycare, "billing_rpc", self._fake_rpc),
            mock.patch.object(daycare, "streak_tiers", lambda s, loc: daycare.DEFAULT_STREAK_TIERS),
            mock.patch.object(feed, "_SESSION", None),
        ]
        for p in self.patches:
            p.start()
        self.api_ok = True
        self.logins = 0

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def _fake_api(self, method, token, **params):
        self.api.append((method, params))
        return {"ok": self.api_ok, "channel": params.get("channel"), "ts": f"1.{len(self.api)}"}

    def _fake_rpc(self, sess, name, body, *, write=True):
        self.rpcs.append((name, body, write))
        if name == "streak_events_unposted":
            return [r for r in self.rows if not r.get("slack_posted_at")]
        if name == "streak_mark_posted":
            if self.mark_fails:
                raise daycare.DaycareError(502, "upstream", "upstream_error")
            for r in self.rows:
                if r["id"] == body["p_event"]:
                    r["slack_posted_at"] = "now"
            return None
        raise AssertionError(name)

    def _session_fn(self):
        self.logins += 1
        return session()

    def posts(self):
        return [(p["channel"], p["text"]) for m, p in self.api if m == "chat.postMessage"]

    def marks(self):
        return [b["p_event"] for n, b, _ in self.rpcs if n == "streak_mark_posted"]

    def test_posts_once_to_the_payments_room_then_stamps(self):
        out = feed.run_once(self._session_fn)
        self.assertEqual((out["ok"], out["posted"], out["failed"]), (True, 1, 0))
        self.assertEqual(self.posts(), [(PAY, "Payment confirmed — Dana Smith — $215.00 — week of Nov 16 — "
                                              "streak 4 (next: 10% at 6)")])
        self.assertEqual(self.marks(), ["e1"])
        self.assertEqual(self.rpcs[0], ("streak_events_unposted", {"p_limit": feed.LIMIT}, False))
        self.assertEqual(feed.run_once(self._session_fn)["posted"], 0)       # stamped: nothing left
        self.assertEqual(len(self.posts()), 1)
        self.assertEqual(self.logins, 1)                                     # the lane keeps its login

    def test_slack_refusal_is_not_stamped_and_retries(self):
        self.api_ok = False
        out = feed.run_once(self._session_fn)
        self.assertEqual((out["posted"], out["failed"]), (0, 1))
        self.assertEqual(self.marks(), [])
        self.api_ok = True
        self.assertEqual(feed.run_once(self._session_fn)["posted"], 1)
        self.assertEqual(self.marks(), ["e1"])

    def test_failed_stamp_does_not_post_twice(self):
        self.mark_fails = True
        out = feed.run_once(self._session_fn)
        self.assertFalse(out["ok"])
        self.assertEqual(len(self.posts()), 1)
        self.mark_fails = False
        out = feed.run_once(self._session_fn)                                # same key inside the dedupe window
        self.assertEqual((out["posted"], len(self.posts())), (1, 1))
        self.assertEqual(self.marks(), ["e1", "e1"])
        self.assertEqual(self.logins, 2)                                     # a failed tick logs in fresh

    def test_inert_without_the_channel_or_with_slack_off(self):
        with mock.patch.dict(os.environ):
            del os.environ["SLACK_CHANNEL_DAYCARE_PAYMENTS"]
            self.assertTrue(feed.run_once(self._session_fn)["inert"])        # no fallback to #forge-daycare
        with mock.patch.dict(os.environ, {"FORGE_CHAT_TRANSPORT": "telegram"}):
            self.assertTrue(feed.run_once(self._session_fn)["inert"])
        with mock.patch.dict(os.environ):
            del os.environ["FORGE_CHAT_TRANSPORT"]                           # unset = telegram
            self.assertTrue(feed.run_once(self._session_fn)["inert"])
        with mock.patch.dict(os.environ, {"SLACK_ONLY_TEST": "1", "SLACK_TEST_CHANNEL_ID": "CTEST01"}):
            self.assertTrue(feed.run_once(self._session_fn)["inert"])
        self.assertEqual((self.api, self.rpcs, self.logins), ([], [], 0))    # no Slack, no database, no login

    def test_amt_ineligible_and_unplaced_rows_are_never_posted(self):
        self.rows = [event("amt", location_id=AMT), event("no", slack_eligible=False),
                     event("lost", location_id=None), event("ok")]
        out = feed.run_once(self._session_fn)
        self.assertEqual((out["posted"], out["skipped"]), (1, 3))
        self.assertEqual(self.marks(), ["ok"])
        self.assertEqual([c for c, _ in self.posts()], [PAY])

    def test_no_session_or_a_database_error_posts_nothing(self):
        self.assertEqual(feed.run_once(lambda: None)["error"], "no daycare session")
        with mock.patch.object(daycare, "billing_rpc", side_effect=daycare.DaycareError(404, "x", "y")):
            out = feed.run_once(self._session_fn)
        self.assertEqual((out["ok"], out["error"]), (False, "DaycareError"))
        self.assertEqual(self.api, [])

    def test_room_is_known_to_slack_io_and_other_keys_keep_their_route(self):
        self.assertIn("daycare-payments", slack_io.TOPIC_KEYS)
        self.assertEqual(slack_io.topic_channel("daycare-payments"), PAY)
        self.assertTrue(slack_io.send("x", business="daycare", dedupe_key="daycare-lead:abcdefghijkl1234"))
        self.assertEqual(self.posts()[-1][0], DAYCARE)                       # no provable site -> main chat
        for name in ("streak_events_unposted", "streak_mark_posted", "streak_effective_discount"):
            self.assertIn(name, daycare._BILLING_RPCS)


class DiscountTests(unittest.TestCase):
    def _save(self, pct, *, rpc_error=None, **extra):
        body = {"guardian_id": GUARDIAN, "description": "Tuition", "amount": "200", "issued_on": "2026-11-16",
                "due_on": "2026-11-20", **extra}
        self.rpc_calls = []

        def rpc(sess, name, payload, **kwargs):
            self.rpc_calls.append((name, payload, kwargs))
            if rpc_error:
                raise rpc_error
            return pct

        def rest(*a, **k):
            if a[1] in ("POST", "PATCH"):
                return [dict(k["body"], id=INVOICE)]
            return [{"id": GUARDIAN, "location_id": ATOB}]

        with mock.patch.object(daycare.BRIDGE, "rest", side_effect=rest) as rest_mock, \
                mock.patch.object(daycare.BRIDGE, "rpc", side_effect=rpc):
            result = daycare.save_invoice(session(), {"invoice": body})
        written = next(c.kwargs["body"] for c in rest_mock.call_args_list if c.args[1] in ("POST", "PATCH"))
        return result, written

    def test_live_discount_lowers_the_amount_and_says_so(self):
        result, written = self._save(10)
        self.assertEqual(written["amount"], 180.0)
        self.assertEqual(written["description"], "Tuition · On-time discount 10%")
        self.assertEqual(result["discount"], {"pct": "10", "original_amount": "200.00", "amount": "180.00"})
        self.assertEqual(self.rpc_calls, [("streak_effective_discount",
                                           {"p_guardian": GUARDIAN, "p_location": ATOB},
                                           {"surface_errors": True, "write": False})])

    def test_rounding_and_the_shapes_postgrest_returns(self):
        self.assertEqual(self._save("25.00", amount="33.33")[1]["amount"], 25.0)   # 24.9975
        self.assertEqual(self._save([{"streak_effective_discount": 12.5}], amount="100")[1]["amount"],
                         87.5)
        self.assertEqual(self._save([10], amount="0.05")[1]["amount"], 0.05)        # 0.045 -> 0.05

    def test_zero_or_bad_pct_and_rpc_errors_bill_full_price(self):
        for pct in (0, "0.00", None, "abc", -5, 100, 250, [], {}):
            result, written = self._save(pct)
            self.assertEqual((written["amount"], written["description"]), (200.0, "Tuition"), pct)
            self.assertNotIn("discount", result)
        for error in (daycare.DaycareError(404, "no function", "upstream_error"), RuntimeError("boom")):
            with self.assertLogs("daycare_supabase", level="WARNING"):
                result, written = self._save(10, rpc_error=error)
            self.assertEqual((written["amount"], written["description"]), (200.0, "Tuition"))

    def test_only_at_creation_and_only_once(self):
        result, written = self._save(10, id=INVOICE)                         # an edit: a link may be out already
        self.assertEqual((written["amount"], self.rpc_calls), (200.0, []))
        result, written = self._save(10, description="Tuition · On-time discount 10%")
        self.assertEqual((written["amount"], self.rpc_calls), (200.0, []))
        for status in ("paid", "void"):
            self.assertEqual(self._save(10, status=status)[1]["amount"], 200.0)
            self.assertEqual(self.rpc_calls, [])

    def test_long_description_keeps_the_discount_note(self):
        written = self._save(10, description="x" * 1000)[1]
        self.assertTrue(written["description"].endswith(" · On-time discount 10%"))
        self.assertEqual(len(written["description"]), 1000)


class BillingReadTests(unittest.TestCase):
    def _rest(self, mode="live", streaks=None, tiers=None, fail=()):
        def rest(sess, method, table, **kwargs):
            if table in fail:
                raise daycare.DaycareError(400, "missing", "upstream_error")
            return {"billing_settings": [{"streak_mode": mode}] if mode else [],
                    "family_streaks": streaks or [], "streak_tiers": tiers or [],
                    "payment_streak_events": [event(slack_posted_at="2026-11-16T15:01:00Z")]}.get(table, [])
        return mock.patch.object(daycare.BRIDGE, "rest", side_effect=rest)

    def test_off_means_no_streak_reads_at_all(self):
        for mode in ("off", None, "LIVE-ish"):
            with self._rest(mode=mode) as rest:
                out = daycare.get_streaks(session())
            self.assertEqual(out, {"mode": "off", "tiers": [], "families": []})
            self.assertEqual([c.args[2] for c in rest.call_args_list], ["billing_settings"])

    def test_missing_tables_read_as_off_or_empty(self):
        with self._rest(fail=("billing_settings",)):
            self.assertEqual(daycare.get_streaks(session())["mode"], "off")
        with self._rest(mode="dry_run", fail=("family_streaks", "streak_tiers")):
            out = daycare.get_streaks(session())
        self.assertEqual(out, {"mode": "dry_run", "tiers": [[6, "10"], [15, "25"]], "families": []})

    def test_families_carry_tier_next_milestone_and_broken_flag(self):
        rows = [{"guardian_id": "g1", "current_streak": 7, "best_streak": 7, "tier_pct": "10.00",
                 "last_on_time_at": "2026-11-16T15:00:00Z"},
                {"guardian_id": "g2", "current_streak": 0, "best_streak": 9, "tier_pct": 0, "last_on_time_at": None},
                {"guardian_id": "g3", "current_streak": 20, "best_streak": 20, "tier_pct": 25, "last_on_time_at": None}]
        with self._rest(streaks=rows, tiers=[{"min_streak": 15, "discount_pct": "25.00"},
                                             {"min_streak": 6, "discount_pct": "10.00"}]):
            out = daycare.get_streaks(session())
        self.assertEqual(out["tiers"], [[6, "10"], [15, "25"]])
        g1, g2, g3 = out["families"]
        self.assertEqual((g1["current_streak"], g1["tier_pct"], g1["next"], g1["broken"]),
                         (7, "10", {"at": 15, "pct": "25"}, False))
        self.assertEqual((g2["next"], g2["broken"]), ({"at": 6, "pct": "10"}, True))
        self.assertEqual((g3["next"], g3["broken"]), (None, False))

    def test_timeline_carries_the_invoice_streak_event(self):
        with self._rest(), mock.patch.object(bl, "_refresh_delivery"), \
                mock.patch.object(daycare, "billing_rpc", return_value={"sends": [], "reminders": []}):
            out = bl.timeline(session(), INVOICE, None)
        self.assertEqual(out["streak_events"], [{"on_time": True, "streak_after": 4, "tier_pct_after": 0,
                                                 "paid_amount": 215, "click_at": "2026-11-16T15:00:00Z",
                                                 "due_on": "2026-11-16", "week_of": "2026-11-16",
                                                 "slack_posted_at": "2026-11-16T15:01:00Z"}])
        with self._rest(fail=("payment_streak_events",)), mock.patch.object(bl, "_refresh_delivery"), \
                mock.patch.object(daycare, "billing_rpc", return_value={"sends": []}):
            self.assertEqual(bl.timeline(session(), INVOICE, None)["streak_events"], [])


if __name__ == "__main__":
    unittest.main()
