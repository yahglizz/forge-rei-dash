"""test_daycare_ads_tg.py — Solomon · Ads Telegram approval cards + the guarded launch (2026-10-17).

No network, no real Higgsfield, no Meta write, no real Telegram: a fake `hf` shim (from
test_daycare_adgen), a fake Telegram transport (telegram_io._api), and a FakeMeta that stands in
for every pipeboard_io read AND write and records each call.

Run: cd "forge rei" && python3 test_daycare_ads_tg.py
"""
import ast
import contextlib
import copy
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from test_daycare_adgen import Base  # noqa: E402 — shim + env + no-network base
import daycare_ads_autopilot as ap  # noqa: E402
import daycare_ads_studio as studio  # noqa: E402
import daycare_ads_tg as tg  # noqa: E402
import forge_ops  # noqa: E402
import higgsfield_io as hf  # noqa: E402
import telegram_io  # noqa: E402

WRITES = ("set_status", "set_budget", "create_ad", "create_creative", "upload_image")


class FakeMeta:
    """Every pipeboard_io function the autopilot touches. Writes mutate the fake account (unless
    dry_run, or the object is in `ignore` — to simulate Meta not taking a write)."""

    def __init__(self):
        self.calls, self.health, self.ignore, self.rows = [], "ACTIVE", set(), []
        self.s = {"campaigns": [{"id": "C1", "name": "Live", "status": "ACTIVE"}],
                  "adsets": [{"id": "S1", "name": "Live set", "status": "ACTIVE", "campaign_id": "C1",
                              "daily_budget": "5000"}],
                  "ads": [{"id": "A1", "name": "Dead ad", "status": "ACTIVE", "adset_id": "S1", "campaign_id": "C1"},
                          {"id": "A2", "name": "Good ad", "status": "ACTIVE", "adset_id": "S1", "campaign_id": "C1"}]}

    def add_built(self, budget="2000"):
        self.s["campaigns"].append({"id": "C9", "name": "[Nova] T", "status": "PAUSED"})
        self.s["adsets"].append({"id": "S9", "name": "T set", "status": "PAUSED", "campaign_id": "C9",
                                 "daily_budget": budget})
        self.s["ads"].append({"id": "A9", "name": "[Nova] T", "status": "PAUSED", "adset_id": "S9", "campaign_id": "C9"})

    def _obj(self, kind, oid):
        pool = {"campaign": "campaigns", "adset": "adsets", "ad": "ads"}[kind]
        return next((x for x in self.s[pool] if x["id"] == oid), None)

    def structure(self, acct):
        self.calls.append(("structure", acct))
        return copy.deepcopy(self.s)

    def account_info(self, acct):
        return {"account_status_label": self.health}

    def set_status(self, kind, oid, status, dry_run=False):
        self.calls.append(("set_status", kind, oid, status, dry_run))
        if not dry_run and (kind, oid) not in self.ignore and self._obj(kind, oid):
            self._obj(kind, oid)["status"] = status
        return {"success": True}

    def set_budget(self, kind, oid, cents, dry_run=False):
        self.calls.append(("set_budget", kind, oid, cents, dry_run))
        if not dry_run and (kind, oid) not in self.ignore and self._obj(kind, oid):
            self._obj(kind, oid)["daily_budget"] = str(cents)
        return {"success": True}

    def create_ad(self, *a, **k):
        self.calls.append(("create_ad", a, False))
        return "AX"

    def create_creative(self, *a, **k):
        self.calls.append(("create_creative", a, False))
        return "CR"

    def upload_image(self, *a, **k):
        self.calls.append(("upload_image", a, False))
        return "H"

    def daily_ad_rows(self, *a):
        return self.rows

    def window_ad_rows(self, *a):
        return []

    def writes(self, real_only=True):
        return [c for c in self.calls if c[0] in WRITES and not (real_only and c[-1] is True)]

    def patch(self):
        return mock.patch.multiple(ap.pb, **{k: getattr(self, k) for k in (
            "structure", "account_info", "set_status", "set_budget", "create_ad", "create_creative",
            "upload_image", "daily_ad_rows", "window_ad_rows")})


class TgBase(Base):
    """+ fake Telegram transport, temp autopilot/cards state, FakeMeta, inline background work."""

    def setUp(self):
        super().setUp()
        self.sent, self.meta = [], FakeMeta()
        self.photo_fail = False

        def fake_api(method, payload, timeout=15, token=None):
            self.sent.append((method, copy.deepcopy(payload)))
            if method == "sendPhoto" and self.photo_fail:
                return {"ok": False, "description": "Bad Request: wrong file identifier"}
            return {"ok": True, "result": {"message_id": len(self.sent)}}
        os.environ.update(TELEGRAM_BOT_TOKEN="T0K", TELEGRAM_CHAT_ID="111", TELEGRAM_CHAT_DAYCARE="-200",
                          TELEGRAM_ALLOWED_IDS="", FORGE_DAYCARE_ADS_MAX_DAILY="", HIGGSFIELD_AUTO_CREDITS="",
                          FORGE_DAYCARE_ADS_LAUNCH_BUDGETS="", FORGE_DAYCARE_ADS_CARDS="1",
                          FORGE_DAYCARE_ADS_MODE="shadow", FORGE_DAYCARE_ADS_CREATIVE="1")
        for p in (mock.patch.object(telegram_io, "_api", fake_api),
                  mock.patch.object(telegram_io, "STATE", self.td / "telegram.json"),
                  mock.patch.object(ap, "STATE", self.td / "ads.json"),
                  mock.patch.object(tg, "STORE", self.td / "cards.json"),
                  mock.patch.object(tg, "_SYNC", True),
                  mock.patch.object(ap, "_VERIFY_WAIT", 0),
                  mock.patch.object(ap, "configured", return_value=True),
                  mock.patch.object(ap, "_account", return_value="act_1"),
                  mock.patch.object(ap, "_creds", contextlib.nullcontext),
                  mock.patch.object(ap, "_claude_key", return_value=""),
                  mock.patch.object(forge_ops, "paused", return_value=False),
                  self.meta.patch()):
            p.start()
            self.addCleanup(p.stop)

    # helpers
    def buttons(self, payload=None):
        out = []
        for _m, p in ([("", payload)] if payload else self.sent):
            for row in ((p.get("reply_markup") or {}).get("inline_keyboard") or []):
                out += row
        return out

    def data_of(self, prefix):
        return [b["callback_data"] for b in self.buttons() if b["callback_data"].startswith(prefix + ":")]

    @staticmethod
    def arg(data):
        """callback_data → the handler's arg (telegram_io strips '<prefix>:')."""
        return data.split(":", 1)[1]

    def card(self, cid):
        return tg._get(cid)

    def fake_ideas(self):
        """studio.ideas without Claude: 3 saved concepts per call, unique ids."""
        k = {"n": 0}

        def ideas(account=None, extra="", feed=None):
            k["n"] += 1
            rows = [{"id": f"idea{k['n']}_{i}", "title": f"Concept {i}: Trust", "headline": "A second home",
                     "primaryText": "Warm, licensed care in North Philly.", "cta": "SIGN_UP", "format": "1:1",
                     "imagePrompt": f"sunlit reading corner {i}, no children, 1:1", "status": "draft",
                     "evidence": "last_90d Meta via Pipeboard: 13 leads", "assets": [], "meta": {}}
                    for i in range(3)]
            studio._save(studio._load() + rows)
            return {"ok": True, "next": rows}
        return mock.patch.object(studio, "ideas", ideas)

    def built_idea(self, image=True):
        self.meta.add_built()
        studio._save([{"id": "i1", "title": "Trust", "status": "built", "imageUrl": "https://img.test/x.png",
                       "meta": {"campaignId": "C9", "adsetId": "S9", "adId": "A9", "account": "act_1",
                                "imageUrl": "https://img.test/x.png" if image else "", "url": "https://fb.test/am"}}])


# ── wiring ─────────────────────────────────────────────────────────────────────────────────
class Wiring(unittest.TestCase):
    def test_handler_table_registered(self):
        self.assertEqual(set(tg.handlers()), {"adsapply", "adsskip", "adsundo", "adsbuild", "adsalt",
                                              "adsdrop", "adslaunch", "adsagain", "adskeep"})
        src = (HERE / "connector.py").read_text()
        block = src[src.index("telegram_io.set_actions({"):]
        block = block[:block.index("\n})")]
        self.assertIn("**daycare_ads_tg.handlers()", block)
        tree = ast.parse(src)
        fns = {n.name: ast.get_source_segment(src, n) for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        self.assertEqual(fns["_handle_daycare_post"].count('"/api/daycare/adgen/cards"'), 2)
        self.assertIn('"/api/daycare/adgen/cards"', fns["_handle_daycare_get"])
        self.assertNotIn("launch(", fns["_handle_daycare_post"].split("adgen/cards")[1][:400],
                         "no HTTP route may launch")

    def test_partner_can_ask_but_it_is_a_spend_card(self):
        import telegram_agent as ta
        self.assertIn(("adgen/cards", "💸 spends image credits"), ta._RISKY)
        self.assertIn("/api/daycare/adgen/cards", (HERE / "telegram_agent.py").read_text())
        self.assertFalse(any(d in "/api/daycare/adgen/cards" for d in ta.DENY))

    def test_launch_only_reachable_from_tap_handlers(self):
        for f in HERE.glob("*.py"):
            if f.name in ("daycare_ads_autopilot.py", "daycare_ads_tg.py") or f.name.startswith("test_"):
                continue
            self.assertNotIn("ap.launch(", f.read_text(errors="ignore"), f.name)
            self.assertNotIn("daycare_ads_autopilot.launch(", f.read_text(errors="ignore"), f.name)


# ── optimize cards ─────────────────────────────────────────────────────────────────────────
PROPS = [
    {"aid": "a1", "kind": "budget", "level": "adset", "id": "S1", "name": "Live set", "from": 5000, "to": 3750,
     "status": "proposed", "reason": "7d CPL $62 on $124 vs $40 target — cut 25% (skill: rollback 20-30%)",
     "evidence": {"spend14": 300.0, "leads14": 4, "cpl14": 75.0, "cpl7": 62.0, "leads7": 2, "tcpl": 40,
                  "dailyBudget": 50.0, "freq": 2.1}},
    {"aid": "a2", "kind": "status", "level": "ad", "id": "A1", "name": "Dead ad", "from": "ACTIVE", "to": "PAUSED",
     "status": "proposed", "reason": "$140 spent (≥3×TCPL) and zero leads — dead concept",
     "evidence": {"spend14": 140.0, "leads14": 0, "cpl14": None, "tcpl": 40}},
]
RUN = {"day": "2026-10-17", "tcpl": 40, "totalBudget": 50.0}


class OptimizeCards(TgBase):
    def test_text_has_rule_numbers_window_source_guard(self):
        t = tg.optimize_text(PROPS[0], RUN)
        for s in ("Cut the daily budget of adset “Live set” from $50 to $38/day",
                  "7d CPL $62 on $124 vs $40 target",                       # the rule that fired
                  "14 days 2026-10-03→2026-10-16", "CPL $75 vs $40 target",   # numbers + window
                  "7 days 2026-10-10→2026-10-16: CPL $62 on 2 leads",
                  "Meta via Pipeboard", "America/New_York", "$100/day account ceiling", "active now $50"):
            self.assertIn(s, t)
        self.assertIn("Pause ad “Dead ad”", tg.optimize_text(PROPS[1], RUN))

    def test_one_card_per_proposal_deduped_and_callback_limits(self):
        ap.set_mode("shadow")
        out = tg.send_optimize_cards(RUN, PROPS)
        self.assertEqual(len(out), 2)
        self.assertTrue(all(c["sent"] for c in out))
        self.assertTrue(all(p["chat_id"] == "-200" for m, p in self.sent if m == "sendMessage"))   # daycare chat
        self.assertEqual(tg.send_optimize_cards(RUN, PROPS), [], "same proposals are never carded twice")
        for b in self.buttons():
            self.assertLessEqual(len(b["callback_data"].encode()), 64)
        self.assertEqual(len(self.data_of("adsapply")), 2)

    def test_no_cards_in_off_or_auto(self):
        for m in ("off", "auto"):
            ap.set_mode(m)
            self.assertEqual(tg.send_optimize_cards(RUN, PROPS), [])
        self.assertEqual(self.sent, [])

    def test_superseded_proposal_card_expires(self):
        ap.set_mode("shadow")
        tg.send_optimize_cards(RUN, PROPS)
        tg.send_optimize_cards(RUN, PROPS[:1])
        states = {c["ref"]: c["state"] for c in tg._load()["cards"]}
        self.assertEqual(states, {"a1": "pending", "a2": "expired"})


class ApplySkipUndo(TgBase):
    def _proposal(self):
        st = ap._load()
        rec = ap._record(st, dict(PROPS[1], status=None), "proposed", "shadow")
        ap._save(st)
        return rec["aid"]

    def test_apply_runs_the_guarded_approve_then_undo(self):
        ap.set_mode("shadow")
        aid = self._proposal()
        card = tg.send_optimize_cards(RUN)[0]
        self.assertEqual(self.meta.writes(), [])
        r = tg.h_apply(card["id"])
        self.assertIn("Applying", r["message"])
        self.assertEqual(self.card(card["id"])["state"], "applied")
        self.assertEqual([c[:5] for c in self.meta.writes(real_only=False)],
                         [("set_status", "ad", "A1", "PAUSED", True), ("set_status", "ad", "A1", "PAUSED", False)])
        self.assertEqual(tg.h_apply(card["id"])["error"], "already handled (applied)")   # single-use
        undo = self.data_of("adsundo")
        self.assertEqual(len(undo), 1)
        tg.h_undo(undo[0].split(":")[1])
        self.assertEqual(self.meta._obj("ad", "A1")["status"], "ACTIVE")
        self.assertEqual(next(a for a in ap._load()["actions"] if a["aid"] == aid)["status"], "undone")

    def test_apply_still_guarded_last_ad_standing(self):
        ap.set_mode("shadow")
        self._proposal()
        self.meta.s["ads"][1]["status"] = "PAUSED"            # A1 is now the last active ad in S1
        card = tg.send_optimize_cards(RUN)[0]
        tg.h_apply(card["id"])
        self.assertEqual(self.card(card["id"])["state"], "failed")
        self.assertEqual(self.meta.writes(real_only=False), [])
        self.assertIn("last active ad", self.sent[-1][1]["text"])

    def test_skip_and_off(self):
        ap.set_mode("shadow")
        aid = self._proposal()
        card = tg.send_optimize_cards(RUN)[0]
        ap.set_mode("off")
        self.assertIn("off", tg.h_apply(card["id"])["error"])
        self.assertEqual(self.card(card["id"])["state"], "pending")
        tg.h_skip(card["id"])
        self.assertEqual(next(a for a in ap._load()["actions"] if a["aid"] == aid)["status"], "rejected")
        self.assertEqual(self.meta.writes(real_only=False), [])


# ── concept cards ──────────────────────────────────────────────────────────────────────────
class ConceptCards(TgBase):
    def test_image_path_photo_card_with_build(self):
        self.cli_on()
        with self.fake_ideas():
            out = tg.send_concept_cards(3, "auto")
        self.assertTrue(out["ok"], out)
        photos = [p for m, p in self.sent if m == "sendPhoto"]
        self.assertEqual(len(photos), 3)
        self.assertEqual(photos[0]["photo"], "https://cdn.example.test/img1.png")
        self.assertEqual(photos[0]["chat_id"], "-200")
        self.assertIn("Preview ≈ 0.5 credits", photos[0]["caption"])
        self.assertLessEqual(len(photos[0]["caption"]), 1024)
        self.assertEqual(len(self.data_of("adsbuild")), 3)
        self.assertEqual(len(self.creates()), 3)
        self.assertEqual(hf.auto_spent_today(), 1.5)
        self.assertEqual(json.loads(hf.LEDGER.read_text())["days"][hf._today()]["entries"][0]["source"], "auto")
        self.assertEqual(self.meta.writes(real_only=False), [])

    def test_engine_not_ready_text_card_no_build(self):
        with self.fake_ideas():
            tg.send_concept_cards(1, "auto")
        self.assertEqual([m for m, _ in self.sent], ["sendMessage"])
        text = self.sent[0][1]["text"]
        self.assertIn("No preview image", text)
        self.assertIn("Install the Higgsfield CLI", text)
        self.assertEqual(self.data_of("adsbuild"), [])
        self.assertTrue(self.data_of("adsalt") and self.data_of("adsdrop"))
        cid = self.data_of("adsalt")[0].split(":")[1]
        self.assertIn("error", tg.h_build(cid))                     # no image → refused even if forged

    def test_unknown_cost_never_auto_generates(self):
        self.cli_on("badcost")
        with self.fake_ideas():
            tg.send_concept_cards(1, "auto")
        self.assertEqual(self.creates(), [])
        self.assertEqual(self.data_of("adsbuild"), [])
        self.assertIn("automatic previews only run on a quoted cost", self.sent[-1][1]["text"])

    def test_auto_cap(self):
        self.cli_on()
        os.environ["HIGGSFIELD_AUTO_CREDITS"] = "0.6"
        with self.fake_ideas():
            tg.send_concept_cards(2, "auto")
        self.assertEqual(len(self.creates()), 1)
        self.assertEqual(len(self.data_of("adsbuild")), 1)
        self.assertIn("HIGGSFIELD_AUTO_CREDITS", self.sent[-1][1]["text"])
        ok, _ = hf.cap_check(0.5, source="manual")                  # the owner's own taps keep the global cap
        self.assertTrue(ok)

    def test_throttles(self):
        self.cli_on()
        with self.fake_ideas():
            self.assertEqual(tg.send_concept_cards(3, "auto")["ok"], True)
            r = tg.send_concept_cards(3, "chat")
            self.assertIn("waiting for your tap", r["skipped"])         # ≥3 pending
            for c in tg._load()["cards"]:
                tg._set(c["id"], state="discarded")
            self.assertIn("already sent", tg.send_concept_cards(3, "auto")["skipped"])   # ≤3 auto/day
            with mock.patch.object(forge_ops, "paused", return_value=True):
                self.assertIn("clocked out", tg.send_concept_cards(1, "chat")["skipped"])
            ap.set_mode("off")
            self.assertIn("off", tg.send_concept_cards(1, "chat")["skipped"])
            self.assertFalse(tg.start_concept_cards(1)["ok"])
        self.assertEqual(len(self.creates()), 3)

    def test_alt_and_drop(self):
        self.cli_on()
        with self.fake_ideas():
            tg.send_concept_cards(1, "chat")
            cid = self.data_of("adsalt")[0].split(":")[1]
            tg.h_alt(cid)
        self.assertEqual(self.card(cid)["state"], "replaced")
        self.assertEqual(len(self.data_of("adsbuild")), 2)
        drop = self.data_of("adsdrop")[-1].split(":")[1]
        ref = self.card(drop)["ref"]
        tg.h_drop(drop)
        self.assertIsNone(studio._find(ref))
        self.assertIn("already handled", tg.h_drop(drop)["error"])

    def test_background_does_not_block(self):
        self.cli_on()
        tg._SYNC = False
        slow = threading.Event()

        def slow_ideas(*a, **k):
            slow.wait(2)
            return {"ok": False, "error": "x"}
        with mock.patch.object(studio, "ideas", slow_ideas):
            t0 = time.time()
            r = tg.start_concept_cards(2)
            self.assertLess(time.time() - t0, 0.5)
            self.assertTrue(r["queued"])
            self.assertEqual(self.sent, [])                         # nothing yet: the work is elsewhere
            slow.set()
            for _ in range(40):
                if self.sent:
                    break
                time.sleep(0.05)
        self.assertIn("couldn't draft", self.sent[-1][1]["text"])

    def test_send_photo_falls_back_to_link(self):
        self.photo_fail = True
        r = telegram_io.send_photo("daycare", "https://img.test/a.png", "x" * 2000,
                                   buttons=[[{"text": "b", "callback_data": "adsdrop:c1"}]], dedupe_key="k1")
        self.assertTrue(r["ok"])
        self.assertFalse(r["photo"])
        self.assertEqual(len(self.sent[0][1]["caption"]), 1024)
        self.assertEqual(self.sent[1][0], "sendMessage")
        self.assertIn("https://img.test/a.png", self.sent[1][1]["text"])
        self.assertTrue(self.buttons(self.sent[1][1]))
        self.assertEqual(telegram_io.send_photo("daycare", "u", "c", dedupe_key="k1")["skipped"], "dedupe")


# ── build → launch card ────────────────────────────────────────────────────────────────────
class BuildLaunchFlow(TgBase):
    def test_build_then_launch_then_undo(self):
        """Graph fallback (no Pipeboard at build time) still feeds the same launch card + guards.
        The Pipeboard build is covered in test_daycare_ads_build.py."""
        self.cli_on()
        with self.fake_ideas():
            tg.send_concept_cards(1, "chat")
        cid = self.data_of("adsbuild")[0].split(":")[1]
        built = {"ok": True, "detail": "created PAUSED", "url": "https://fb.test/am",
                 "campaignId": "C9", "adsetId": "S9", "adId": "A9"}
        self.meta.add_built()
        with mock.patch.object(studio, "meta_ready", return_value=True), \
                mock.patch.object(ap, "configured", return_value=False), \
                mock.patch("daycare_growth._daycare_creds", return_value={}), \
                mock.patch.object(studio, "AD_ACCOUNT", "act_1"), \
                mock.patch("agency_ads.create_ad", return_value=built) as ca:
            self.assertIn("Building", tg.h_build(cid)["message"])
        self.assertTrue(ca.call_args.kwargs.get("paused") is True or ca.call_args.args[1] is True)
        self.assertEqual(ca.call_args.args[0]["creative"]["picture"], "https://cdn.example.test/img1.png")
        idea = studio._find(self.card(cid)["ref"])
        self.assertEqual((idea["meta"]["campaignId"], idea["meta"]["adId"]), ("C9", "A9"))
        launches = self.data_of("adslaunch")
        self.assertEqual([d.rsplit(":", 1)[1] for d in launches], ["10", "20"])
        self.assertTrue(self.data_of("adskeep"))
        self.assertEqual(self.sent[-1][0], "sendPhoto")
        self.assertEqual(self.meta.writes(real_only=False), [], "building + carding never touch Meta via Pipeboard")
        tg.h_launch(self.arg(launches[0]))
        lcid = launches[0].split(":")[1]
        self.assertEqual(self.card(lcid)["state"], "launched")
        self.assertEqual((self.meta._obj("campaign", "C9")["status"], self.meta._obj("adset", "S9")["daily_budget"]),
                         ("ACTIVE", "1000"))
        self.assertIn("Launched", self.sent[-1][1]["text"])
        tg.h_undo(self.data_of("adsundo")[-1].split(":")[1])
        self.assertEqual({self.meta._obj(k, i)["status"] for k, i in (("campaign", "C9"), ("adset", "S9"), ("ad", "A9"))},
                         {"PAUSED"})
        for b in self.buttons():
            self.assertLessEqual(len(b["callback_data"].encode()), 64, b)

    def test_keep_paused(self):
        self.built_idea()
        card = tg._send_launch_card(studio._find("i1"))
        tg.h_keep(card["id"])
        self.assertEqual(self.card(card["id"])["state"], "kept")
        self.assertIn("already handled", tg.h_launch(f"{card['id']}:10")["error"])
        self.assertEqual(self.meta.writes(real_only=False), [])


# ── the launch guard matrix ────────────────────────────────────────────────────────────────
class LaunchGuards(TgBase):
    def setUp(self):
        super().setUp()
        self.built_idea()
        ap.set_mode("shadow")

    def refused(self, code, *a, **k):
        r = ap.launch(*a, **k)
        self.assertFalse(r["ok"], r)
        self.assertEqual(r["code"], code, r)
        self.assertEqual(self.meta.writes(real_only=False), [], f"{code}: no write, not even a dry run")
        return r

    def test_foreign_ids(self):
        self.refused("foreign", "nope", 10)
        studio._update("i1", {"meta": {"campaignId": "C9", "adsetId": "S9"}})       # no ad id recorded
        self.refused("foreign", "i1", 10)
        studio._update("i1", {"meta": {"campaignId": "C1", "adsetId": "S9", "adId": "A9", "imageUrl": "u"}})
        self.refused("foreign", "i1", 10)                         # ad set does not belong to that campaign
        studio._update("i1", {"meta": {"campaignId": "CX", "adsetId": "SX", "adId": "AX", "imageUrl": "u"}})
        self.refused("foreign", "i1", 10)                         # not in the live account
        studio._update("i1", {"status": "draft"})
        self.refused("foreign", "i1", 10)

    def test_budget_paused_off_health_ceiling(self):
        for bad in (15, "abc", 1000, None):
            self.refused("budget", "i1", bad)
        with mock.patch.object(forge_ops, "paused", return_value=True):
            self.refused("paused", "i1", 10)
        ap.set_mode("off")
        self.refused("off", "i1", 10)
        ap.set_mode("shadow")
        self.meta.health = "DISABLED"
        self.refused("health", "i1", 10)
        self.meta.health = "ACTIVE"
        self.meta.s["adsets"][0]["daily_budget"] = "9500"          # $95 active + $10 > $100
        self.refused("ceiling", "i1", 10)
        os.environ["FORGE_DAYCARE_ADS_MAX_DAILY"] = "8"
        self.refused("ceiling", "i1", 10)                          # a button above the ceiling itself

    def test_other_account_refused(self):
        studio._update("i1", {"meta": dict(studio._find("i1")["meta"], account="act_999")})
        self.refused("foreign", "i1", 10)
        studio._update("i1", {"meta": dict(studio._find("i1")["meta"], account="1")})   # same id, no prefix
        self.assertTrue(ap.launch("i1", 10)["ok"])

    def test_no_image_and_lifetime(self):
        self.built_idea(image=False)
        self.refused("no_image", "i1", 10)
        self.built_idea()
        self.meta._obj("adset", "S9")["lifetime_budget"] = "50000"
        self.refused("budget_type", "i1", 10)

    def test_write_order_verify_and_idempotent(self):
        r = ap.launch("i1", 20)
        self.assertTrue(r["ok"], r)
        w = [(c[0], c[1], c[2], c[-1]) for c in self.meta.writes(real_only=False)]
        expect = [("set_budget", "adset", "S9"), ("set_status", "ad", "A9"), ("set_status", "adset", "S9"),
                  ("set_status", "campaign", "C9")]
        self.assertEqual(w, [e + (True,) for e in expect] + [e + (False,) for e in expect])
        self.assertEqual([c[3] for c in self.meta.writes() if c[0] == "set_budget"], [2000])
        rec = r["action"]
        self.assertEqual((rec["kind"], rec["status"], rec["verified"], rec["budgetCents"]), ("launch", "executed", True, 2000))
        self.assertIn(rec, ap.status()["recent"])                   # shows in the Autopilot tab
        n = len(self.meta.calls)
        again = ap.launch("i1", 20)
        self.assertTrue(again["ok"] and again["noop"])
        self.assertEqual(len([c for c in self.meta.calls[n:] if c[0] in WRITES]), 0)
        self.assertEqual(ap.launch("i1", 10)["code"], "live")       # never silently re-budget a live ad

    def test_one_launch_per_day_unless_retapped(self):
        st = ap._load()
        st["lastLaunchAt"] = time.time() - 3600
        ap._save(st)
        self.refused("daily_limit", "i1", 10)
        self.assertTrue(ap.launch("i1", 10, second_ok=True)["ok"])

    def test_daily_limit_card_offers_explicit_second_tap(self):
        st = ap._load()
        st["lastLaunchAt"] = time.time() - 60
        ap._save(st)
        card = tg._send_launch_card(studio._find("i1"))
        tg.h_launch(f"{card['id']}:10")
        again = self.data_of("adsagain")
        self.assertEqual(len(again), 1)
        self.assertIn("error", tg.h_again(self.arg(again[0]).rsplit(":", 1)[0] + ":20"))   # amount must match
        tg.h_again(self.arg(again[0]))
        self.assertEqual(self.meta._obj("campaign", "C9")["status"], "ACTIVE")

    def test_verify_mismatch_rolls_back(self):
        self.meta.ignore = {("campaign", "C9")}                     # Meta silently keeps the campaign PAUSED
        r = ap.launch("i1", 10)
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "write")
        self.assertIn("Rolled back to PAUSED", r["error"])
        tail = [c[:4] for c in self.meta.writes()][-3:]
        self.assertEqual(tail, [("set_status", "campaign", "C9", "PAUSED"), ("set_status", "adset", "S9", "PAUSED"),
                                ("set_status", "ad", "A9", "PAUSED")])
        self.assertEqual((self.meta._obj("adset", "S9")["status"], self.meta._obj("ad", "A9")["status"]),
                         ("PAUSED", "PAUSED"))
        self.assertEqual(r["action"]["status"], "failed")

    def test_write_error_rolls_back(self):
        real = self.meta.set_status

        def boom(kind, oid, status, dry_run=False):
            if kind == "campaign" and status == "ACTIVE" and not dry_run:
                raise ap.pb.PipeboardError("Pipeboard HTTP 500")
            return real(kind, oid, status, dry_run)
        with mock.patch.object(ap.pb, "set_status", boom):
            r = ap.launch("i1", 10)
        self.assertEqual(r["code"], "write")
        self.assertEqual(self.meta._obj("ad", "A9")["status"], "PAUSED")

    def test_undo_pauses_all_three(self):
        r = ap.launch("i1", 10)
        u = ap.undo(r["action"]["aid"])
        self.assertTrue(u["ok"], u)
        self.assertEqual({self.meta._obj(k, i)["status"] for k, i in (("campaign", "C9"), ("adset", "S9"), ("ad", "A9"))},
                         {"PAUSED"})
        self.assertFalse(ap.undo(r["action"]["aid"])["ok"])          # once


# ── a whole simulated day: zero Meta writes until a tap ─────────────────────────────────────
class SimulatedDay(TgBase):
    def _rows(self):
        today = ap.local_now().date()
        rows = []
        for i in range(1, 15):
            d = (today - dt.timedelta(days=i)).isoformat()
            rows.append({"ad_id": "A1", "adset_id": "S1", "campaign_id": "C1", "day": d, "spend": "10",
                         "impressions": "1000", "clicks": "10", "actions": []})
            rows.append({"ad_id": "A2", "adset_id": "S1", "campaign_id": "C1", "day": d, "spend": "5",
                         "impressions": "800", "clicks": "12", "actions": [{"action_type": "lead", "value": "1"}]})
        return rows

    def test_shadow_day_writes_nothing_until_tapped(self):
        self.cli_on()                                               # engine READY: the old creative loop would build
        self.meta.rows = self._rows()
        ap.set_mode("shadow")
        with self.fake_ideas(), mock.patch("dropship_adspy.configured", return_value=False), \
                mock.patch("agency_ads.create_ad", side_effect=AssertionError("Meta Graph write")):
            res = ap.run_once(force=True)
        self.assertTrue(res["ok"], res)
        self.assertEqual(self.meta.writes(real_only=False), [], "a shadow day makes ZERO Meta writes")
        self.assertIn("concept cards", res["creative"]["why"])
        self.assertEqual(len(self.data_of("adsapply")), 2)          # pause A1 + scale S1
        self.assertEqual(len(self.data_of("adsbuild")), 3)          # 3 concept previews
        self.assertEqual(hf.auto_spent_today(), 1.5)
        for b in self.buttons():
            self.assertLessEqual(len(b["callback_data"].encode()), 64)
        pause = next(c for c in tg._load()["cards"] if c["kind"] == "optimize" and "Dead ad" in c["title"])
        tg.h_apply(pause["id"])                                     # ← the owner's tap
        self.assertEqual([c[:4] for c in self.meta.writes()], [("set_status", "ad", "A1", "PAUSED")])


# ── Higgsfield: ET-day ledger, HOME, lapse alert, background timeout ─────────────────────────
class HiggsfieldFixes(TgBase):
    def test_ledger_day_is_et_not_utc(self):
        utc = lambda *a: dt.datetime(*a, tzinfo=dt.timezone.utc).timestamp()  # noqa: E731
        os.environ["FORGE_TZ_OFFSET"] = "-4"
        with mock.patch.object(hf, "_now", return_value=utc(2026, 10, 18, 2, 0)):     # 22:00 ET Oct 17
            self.assertEqual(hf._today(), "2026-10-17")
            hf._ledger_add({"credits": 2, "source": "auto"})
            hf._ledger_add({"credits": 1, "source": "manual"})
        with mock.patch.object(hf, "_now", return_value=utc(2026, 10, 18, 3, 59)):    # 23:59 ET — same day
            self.assertEqual(hf.spent_today(), (3.0, 0))
            self.assertEqual(hf.auto_spent_today(), 2.0)
        with mock.patch.object(hf, "_now", return_value=utc(2026, 10, 18, 4, 1)):     # 00:01 ET Oct 18 — reset
            self.assertEqual(hf._today(), "2026-10-18")
            self.assertEqual(hf.spent_today(), (0.0, 0))
            self.assertEqual(hf.auto_spent_today(), 0.0)

    def test_cli_gets_a_deterministic_home(self):
        shim = self.td / "homehf"
        shim.write_text(f"#!{sys.executable}\nimport os,sys\nprint('higgsfield 1.2.2' if sys.argv[1:]==['version'] "
                        "else os.environ.get('HOME','NONE'))\n")
        shim.chmod(0o755)
        os.environ["HIGGSFIELD_CLI_BIN"] = str(shim)
        env = {k: v for k, v in os.environ.items() if k != "HOME"}
        with mock.patch.dict(os.environ, env, clear=True):
            os.environ["HIGGSFIELD_HOME"] = "/root-test"
            self.assertEqual(hf._run_cli(["x"])[1].strip(), "/root-test")
            del os.environ["HIGGSFIELD_HOME"]
            self.assertNotIn(hf._run_cli(["x"])[1].strip(), ("", "NONE"))   # passwd home, never empty

    def test_lapse_detected_and_hq_alert_once_a_day(self):
        self.cli_on()
        self.assertTrue(hf.cli_status(fresh=True)["ready"])
        self.cli_on("nologin")
        st = hf.status(fresh=True)
        self.assertTrue(st["cli"]["lapsed"])
        self.assertIn("lapsed", st["nextStep"])
        with self.fake_ideas():
            tg.send_concept_cards(1, "auto")
        alerts = [p for m, p in self.sent if m == "sendMessage" and "lapsed" in p["text"]]
        self.assertEqual(len(alerts), 2)                           # the HQ alert + the card's next step
        self.assertEqual(alerts[0]["chat_id"], "111", "the lapse alert goes to HQ, not the daycare chat")
        self.assertFalse(hf.alert_login_lapsed())                  # once per ET day

    def test_never_logged_in_is_not_lapsed(self):
        self.cli_on("nologin")
        self.assertFalse(hf.cli_status(fresh=True)["lapsed"])

    def test_background_hard_timeout(self):
        got = []
        done = threading.Event()
        hf.run_in_background(lambda: (time.sleep(0.6), {"ok": True})[1],
                             lambda r: (got.append(r), done.set()), timeout=0.1)
        self.assertTrue(done.wait(2))
        time.sleep(0.8)
        self.assertEqual(len(got), 1)
        self.assertTrue(got[0]["timedOut"])


# ── Telegram callback plumbing (the two-factor check is the real one) ─────────────────────────
class CallbackPlumbing(TgBase):
    def _cq(self, data, from_id="111", chat_id="-200", photo=True):
        msg = {"message_id": 7, "chat": {"id": chat_id}}
        msg.update({"photo": [{"file_id": "f"}], "caption": "concept"} if photo else {"text": "proposal"})
        return {"id": "q1", "from": {"id": from_id}, "data": data, "message": msg}

    def test_tap_routes_and_photo_caption_is_edited(self):
        self.cli_on()
        with self.fake_ideas():
            tg.send_concept_cards(1, "chat")
        drop = self.data_of("adsdrop")[0]
        telegram_io.set_actions(tg.handlers())
        self.sent.clear()
        telegram_io._handle_callback(self._cq(drop))
        methods = [m for m, _ in self.sent]
        self.assertIn("editMessageCaption", methods)
        self.assertNotIn("editMessageText", methods)
        edit = dict(self.sent)["editMessageCaption"]
        self.assertEqual(edit["reply_markup"], {"inline_keyboard": []})
        self.assertEqual(self.card(drop.split(":")[1])["state"], "discarded")

    def test_stranger_in_the_daycare_group_is_refused(self):
        self.cli_on()
        with self.fake_ideas():
            tg.send_concept_cards(1, "chat")
        build = self.data_of("adsbuild")[0]
        telegram_io.set_actions(tg.handlers())
        telegram_io._handle_callback(self._cq(build, from_id="999"))
        self.assertEqual(self.card(build.split(":")[1])["state"], "pending")
        self.assertIn("Not authorized", json.dumps(self.sent[-1][1]))


# ── box install scripts ────────────────────────────────────────────────────────────────────
class BoxScripts(unittest.TestCase):
    D = HERE / "deploy"

    def test_syntax_and_pins(self):
        for f in ("install-higgsfield-cli.sh", "higgsfield-login-box.sh"):
            subprocess.run(["bash", "-n", str(self.D / f)], check=True)
        s = (self.D / "install-higgsfield-cli.sh").read_text()
        self.assertIn("6a642f61f409a00d724de3079c1a7a25777eb1e49a2e0c3814e8a6ea3f49bb51", s)
        self.assertIn("8f38897cccf31d517566a0a8b698e0955328d03b7755cac6ff4e050b9828ec79", s)
        self.assertIn("releases/download/v${VERSION}", s)
        self.assertIn("SHA-256 MISMATCH", s)
        login = (self.D / "higgsfield-login-box.sh").read_text()
        self.assertNotIn("auth token", login.split("set -euo pipefail", 1)[1])

    def test_dry_runs_touch_no_network(self):
        td = Path(tempfile.mkdtemp())
        mark = td / "NETWORK"
        for tool in ("curl", "ssh", "wget", "lsof"):
            (td / tool).write_text(f"#!/bin/sh\necho {tool} >> {mark}\nexit 1\n")
            (td / tool).chmod(0o755)
        env = {"PATH": f"{td}:/usr/bin:/bin", "HOME": str(td)}
        out = subprocess.run(["bash", str(self.D / "install-higgsfield-cli.sh"), "--dry-run", "--arch", "amd64",
                              "--prefix", str(td / "bin")], capture_output=True, text=True, env=env, check=True).stdout
        self.assertIn("DRY RUN", out)
        self.assertIn("hf_1.2.2_linux_amd64.tar.gz", out)
        self.assertIn("HIGGSFIELD_CLI_BIN=", out)
        self.assertIn("HIGGSFIELD_HOME=/root", out)
        out2 = subprocess.run(["bash", str(self.D / "higgsfield-login-box.sh"), "--dry-run"], capture_output=True,
                              text=True, env=env, check=True).stdout
        for s in ("auth login --port 8765", "-L 8765:localhost:8765", "workspace list", "workspace set",
                  "account status"):
            self.assertIn(s, out2)
        self.assertFalse(mark.exists(), "a dry run must not call curl/ssh")


class ReadModel(TgBase):
    def test_cards_view(self):
        ap.set_mode("shadow")
        tg.send_optimize_cards(RUN, PROPS)
        v = tg.cards_view()
        self.assertEqual((v["pending"], v["counts"]), (2, {"pending": 2}))
        self.assertEqual({c["kind"] for c in v["cards"]}, {"optimize"})
        self.assertNotIn("ref", v["cards"][0])                      # ids stay server-side


if __name__ == "__main__":
    unittest.main()
