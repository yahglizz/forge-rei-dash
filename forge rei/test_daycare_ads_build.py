"""test_daycare_ads_build.py — Build PAUSED through Pipeboard inside the best existing ad set (2026-10-18).

FakePB replaces pipeboard_io.call itself, so the REAL pipeboard_io functions (structure, upload_image,
create_creative, create_ad, set_status, set_budget) run and every Meta tool call + its exact args is
recorded. Fixtures mirror the live account's read-only shapes (2026-10-18): CBO campaigns
(campaign daily_budget), a website/pixel ad set (OFFSITE_CONVERSIONS, asset_feed_spec link_urls,
CTA SIGN_UP, no lead form) and an instant-form ad set (destination ON_AD, link_data call_to_action
lead_gen_form_id, link "http://fb.me/"). No network, no Telegram, no Meta, no Higgsfield.

Run: cd "forge rei" && python3 test_daycare_ads_build.py
"""
import contextlib
import copy
import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from test_daycare_adgen import Base  # noqa: E402
import daycare_ads_autopilot as ap  # noqa: E402
import daycare_ads_studio as studio  # noqa: E402
import daycare_ads_tg as tg  # noqa: E402
import daycare_growth  # noqa: E402
import forge_ops  # noqa: E402
import pipeboard_io as pb  # noqa: E402
import telegram_io  # noqa: E402

WEB_CREATIVE = {"id": "CRWEB", "object_story_spec": {"page_id": "939494549239823", "instagram_user_id": "17841439350588476"},
                "asset_feed_spec": {"call_to_action_types": ["SIGN_UP"],
                                    "link_urls": [{"website_url": "https://www.atouchofblessing.com/"}]},
                "url_tags": "utm_source=facebook&utm_medium=paid_social"}
FORM_CREATIVE = {"id": "CRFORM", "object_story_spec": {"page_id": "939494549239823", "instagram_user_id": "17841439350588476",
                 "link_data": {"link": "http://fb.me/", "call_to_action": {"type": "GET_OFFER",
                                                                          "value": {"lead_gen_form_id": "1424500112855377"}}}}}


class FakePB:
    def __init__(self, cbo=True):
        self.calls, self.new_status, self.hide_new, self.wrong_adset, self.n = [], None, False, False, 0
        self.camps = [{"id": "CWEB", "name": "daycare ads pt1", "objective": "OUTCOME_LEADS", "status": "PAUSED",
                       **({"daily_budget": "3500"} if cbo else {})},
                      {"id": "CFORM", "name": "New Leads Campaign", "objective": "OUTCOME_LEADS", "status": "PAUSED",
                       **({"daily_budget": "5000"} if cbo else {})}]
        self.sets = [{"id": "SWEB", "name": "Website — Philly Radius", "campaign_id": "CWEB", "status": "PAUSED",
                      "optimization_goal": "OFFSITE_CONVERSIONS", "destination_type": "UNDEFINED",
                      **({} if cbo else {"daily_budget": "2000"})},
                     {"id": "SFORM", "name": "New Leads Ad Set", "campaign_id": "CFORM", "status": "PAUSED",
                      "optimization_goal": "LEAD_GENERATION", "destination_type": "ON_AD",
                      **({} if cbo else {"daily_budget": "2000"})}]
        self.ads = [{"id": "AWEB", "name": "Flyer — Website", "adset_id": "SWEB", "campaign_id": "CWEB", "status": "PAUSED",
                     "creative": {"id": "CRWEB"}},
                    {"id": "AWEB2", "name": "Flyer — Website - Copy", "adset_id": "SWEB", "campaign_id": "CWEB",
                     "status": "PAUSED", "creative": {"id": "CRWEB"}},
                    {"id": "AFORM", "name": "New Leads Ad", "adset_id": "SFORM", "campaign_id": "CFORM", "status": "PAUSED",
                     "creative": {"id": "CRFORM"}}]
        self.creatives = {"CRWEB": WEB_CREATIVE, "CRFORM": FORM_CREATIVE}

    def _obj(self, pool, oid):
        return next((x for x in pool if x["id"] == oid), None)

    def call(self, tool, args=None, timeout=60):
        a = copy.deepcopy(args or {})
        self.calls.append((tool, a))
        dry = a.get("dry_run")
        if tool == "get_campaigns":
            return {"data": copy.deepcopy(self.camps)}
        if tool == "get_adsets":
            return {"data": copy.deepcopy(self.sets)}
        if tool == "get_ads":
            return {"data": [copy.deepcopy(x) for x in self.ads if not (self.hide_new and x["id"].startswith("NEW"))]}
        if tool == "get_account_info":
            return {"account_status_label": "ACTIVE"}
        if tool == "get_creative_details":
            return copy.deepcopy(self.creatives[a["creative_id"]])
        if tool == "upload_ad_image":
            return {"images": {"x": {"hash": "H1"}}}
        if tool == "create_ad_creative":
            return {"success": True} if dry else {"id": "CRNEW"}
        if tool == "create_ad":
            if dry:
                return {"success": True}
            self.n += 1
            aid = f"NEW{self.n}"
            self.ads.append({"id": aid, "name": a["name"], "creative": {"id": a["creative_id"]},
                             "adset_id": "SOTHER" if self.wrong_adset else a["adset_id"],
                             "campaign_id": self._obj(self.sets, a["adset_id"])["campaign_id"],
                             "status": self.new_status or a["status"]})
            return {"id": aid}
        if tool in ("update_ad", "update_adset", "update_campaign"):
            pool, key = {"update_ad": (self.ads, "ad_id"), "update_adset": (self.sets, "adset_id"),
                         "update_campaign": (self.camps, "campaign_id")}[tool]
            o = self._obj(pool, a[key])
            if o and not dry:
                if "status" in a:
                    o["status"] = a["status"]
                if "daily_budget" in a:
                    o["daily_budget"] = str(a["daily_budget"])
            return {"success": True}
        raise AssertionError(f"unexpected Pipeboard tool {tool}")

    def writes(self):
        return [(t, a) for t, a in self.calls if t in ("upload_ad_image", "create_ad_creative", "create_ad",
                                                         "update_ad", "update_adset", "update_campaign")]

    def statuses_written(self):
        return [a.get("status") for t, a in self.writes() if "status" in a]


REPORT = {"accountId": "act_1", "via": "pipeboard",
          "dateRange": {"label": "Maximum", "since": "2026-03-01", "until": "2026-10-17", "tz": "America/New_York"},
          "ads": [{"id": "AWEB", "leads": 11, "spend": 289.2}, {"id": "AWEB2", "leads": 2, "spend": 62.22},
                  {"id": "AFORM", "leads": 0, "spend": 0.0}, {"id": "DELETED", "leads": 4, "spend": 46.3}]}


class BuildBase(Base):
    def setUp(self):
        super().setUp()
        self.fake, self.sent = FakePB(), []
        self.report = copy.deepcopy(REPORT)

        def fake_api(method, payload, timeout=15, token=None):
            self.sent.append((method, copy.deepcopy(payload)))
            return {"ok": True, "result": {"message_id": len(self.sent)}}
        os.environ.update(TELEGRAM_BOT_TOKEN="T0K", TELEGRAM_CHAT_ID="111", TELEGRAM_CHAT_DAYCARE="-200",
                          FORGE_DAYCARE_ADS_MODE="shadow", FORGE_DAYCARE_ADS_CARDS="1")
        for p in (mock.patch.object(pb, "call", lambda *a, **k: self.fake.call(*a, **k)),
                  mock.patch.object(daycare_growth, "ads_report", lambda **k: copy.deepcopy(self.report)),
                  mock.patch.object(telegram_io, "_api", fake_api),
                  mock.patch.object(telegram_io, "STATE", self.td / "telegram.json"),
                  mock.patch.object(ap, "STATE", self.td / "ads.json"),
                  mock.patch.object(tg, "STORE", self.td / "cards.json"),
                  mock.patch.object(tg, "_SYNC", True),
                  mock.patch.object(ap, "_VERIFY_WAIT", 0),
                  mock.patch.object(studio, "_BUILD_VERIFY_WAIT", 0),
                  mock.patch.object(ap, "configured", return_value=True),
                  mock.patch.object(ap, "_account", return_value="act_1"),
                  mock.patch.object(ap, "_creds", contextlib.nullcontext),
                  mock.patch.object(forge_ops, "paused", return_value=False),
                  mock.patch("agency_ads.create_ad", side_effect=AssertionError("Graph path used"))):
            p.start()
            self.addCleanup(p.stop)
        studio._TARGET_CACHE.update(at=0.0, val=None)
        studio._save([{"id": "i1", "title": "Concept 1: Trust", "headline": "A second home",
                       "primaryText": "Warm, licensed care.", "cta": "CONTACT_US", "status": "image",
                       "imageUrl": "https://cdn.example.test/img1.png", "meta": {}}])

    def tool_seq(self):
        return [t for t, _ in self.fake.writes()]

    def args(self, tool):
        return next(a for t, a in self.fake.calls if t == tool and not a.get("dry_run"))

    def tearDown(self):
        # the invariant of the whole build path: it never writes ACTIVE (only the launch tap may)
        if not getattr(self, "launched", False):
            self.assertNotIn("ACTIVE", self.fake.statuses_written())


class Build(BuildBase):
    def test_happy_path_order_and_shape(self):
        r = studio.build_paused("i1")
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.tool_seq(), ["upload_ad_image", "create_ad_creative", "create_ad"])
        reads_after = [t for t, _ in self.fake.calls[[t for t, _ in self.fake.calls].index("create_ad") + 1:]]
        self.assertIn("get_ads", reads_after)                                    # verify after create
        cr = self.args("create_ad_creative")
        self.assertEqual((cr["page_id"], cr["instagram_actor_id"], cr["link_url"], cr["url_tags"]),
                         ("939494549239823", "17841436257715501", "https://www.atouchofblessing.com/",
                          "utm_source=facebook&utm_medium=paid_social"))   # real @atouchofblessing2.3, not the template's Page-backed id
        self.assertEqual((cr["image_hash"], cr["call_to_action_type"], cr["ai_media"]), ("H1", "CONTACT_US", True))
        self.assertNotIn("lead_gen_form_id", cr)
        ad = self.args("create_ad")
        self.assertEqual((ad["adset_id"], ad["status"]), ("SWEB", "PAUSED"))
        idea = studio._find("i1")
        m = idea["meta"]
        self.assertEqual(idea["status"], "built")
        self.assertEqual((m["via"], m["adsetId"], m["campaignId"], m["adId"], m["creativeId"]),
                         ("pipeboard", "SWEB", "CWEB", "NEW1", "CRNEW"))
        self.assertEqual((m["evidence"]["leads"], m["evidence"]["cpl"], m["evidence"]["source"]), (13, 27.03, "Meta via Pipeboard"))
        self.assertFalse(m["launchable"])
        self.assertIn("CBO", m["blockers"][0])
        n = len(self.fake.writes())
        self.assertTrue(studio.build_paused("i1")["noop"])                       # idempotent
        self.assertEqual(len(self.fake.writes()), n)

    def test_lead_form_template(self):
        self.report["ads"] = [{"id": "AFORM", "leads": 5, "spend": 50.0}]
        r = studio.build_paused("i1")
        self.assertTrue(r["ok"], r)
        cr = self.args("create_ad_creative")
        self.assertEqual(cr["lead_gen_form_id"], "1424500112855377")             # read from the live creative
        self.assertEqual(cr["call_to_action_type"], "SIGN_UP")                   # CONTACT_US → instant-form CTA
        self.assertEqual(cr["link_url"], studio.TOUR_LINK)                        # never the fb.me placeholder
        self.assertEqual(self.args("create_ad")["adset_id"], "SFORM")

    def test_no_adset_refused(self):
        self.report["ads"] = [{"id": "AWEB", "leads": 0, "spend": 40.0}, {"id": "DELETED", "leads": 9, "spend": 9.0}]
        r = studio.build_paused("i1")
        self.assertEqual(r["code"], "no_adset")
        self.assertIn("nothing proven", r["error"])
        self.assertEqual(self.fake.writes(), [])

    def test_unknown_evidence_refused(self):
        with mock.patch.object(daycare_growth, "ads_report", side_effect=pb.PipeboardError("HTTP 502")):
            r = studio.build_paused("i1")
        self.assertEqual(r["code"], "evidence")
        self.assertEqual(self.fake.writes(), [])

    def test_no_image_refused(self):
        studio._update("i1", {"imageUrl": ""})
        self.assertEqual(studio.build_paused("i1")["code"], "no_image")
        self.assertEqual(self.fake.writes(), [])

    def test_ad_not_paused_aborts(self):
        self.fake.new_status = "ACTIVE"                                          # Meta ignored our PAUSED
        r = studio.build_paused("i1")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "not_paused")
        self.assertEqual(self.tool_seq()[-1], "update_ad")
        self.assertEqual(self.fake.writes()[-1][1]["status"], "PAUSED")
        self.assertNotEqual(studio._find("i1")["status"], "built")
        self.assertEqual(studio._find("i1")["buildError"]["adId"], "NEW1")

    def test_verify_mismatch(self):
        self.fake.hide_new = True
        r = studio.build_paused("i1")
        self.assertEqual(r["code"], "verify")
        self.assertIn("not in the account read", r["error"])
        self.assertNotEqual(studio._find("i1")["status"], "built")
        self.fake.hide_new, self.fake.wrong_adset = False, True
        studio._update("i1", {"buildError": None})
        r = studio.build_paused("i1")
        self.assertEqual(r["code"], "verify")
        self.assertIn("landed in ad set SOTHER", r["error"])

    def test_graph_only_without_pipeboard(self):
        with mock.patch.object(studio, "create_ad", return_value={"ok": True}) as g, \
                mock.patch.object(studio, "build_paused", return_value={"ok": True}) as p:
            studio.build("i1")
            self.assertEqual((g.call_count, p.call_count), (0, 1))
            with mock.patch.object(ap, "configured", return_value=False):
                studio.build("i1")
            self.assertEqual((g.call_count, p.call_count), (1, 1))

    def test_no_active_status_in_build_source(self):
        src = (HERE / "daycare_ads_studio.py").read_text()
        body = src[src.index("def build_paused("):src.index("def _note_build_error(")]
        for line in body.splitlines():
            if "set_status(" in line:
                self.assertIn('"PAUSED"', line)
        self.assertNotRegex(body, r'status["\']?\s*[:=]\s*["\']ACTIVE')
        pbsrc = (HERE / "pipeboard_io.py").read_text()
        cad = pbsrc[pbsrc.index("def create_ad("):pbsrc.index("def clear_cache(")]
        self.assertIn('"status": "PAUSED"', cad)
        self.assertNotIn("status=", cad.split(")", 1)[0])                         # no status parameter to misuse


class LaunchAfterBuild(BuildBase):
    def _abo(self):
        self.fake = FakePB(cbo=False)

    def test_cbo_launch_refused_and_card_says_so_up_front(self):
        self.cli_on()
        tg_card = tg._new("concept", "i1", imageUrl="https://cdn.example.test/img1.png", title="T")
        self.assertIn("Launch it in Meta yourself", tg._target_line())
        self.assertIn("Builds into “Website — Philly Radius” — 13 leads", tg._target_line())
        tg.h_build(tg_card["id"])
        text = self.sent[-1][1].get("caption") or self.sent[-1][1].get("text")
        self.assertIn("Joined ad set “Website — Philly Radius”", text)
        self.assertIn("13 leads, CPL $27 on $351", text)
        self.assertIn("Maximum 2026-03-01→2026-10-17, America/New_York; Meta via Pipeboard", text)
        self.assertIn("Launch this one in Meta yourself", text)
        btns = [b["callback_data"] for row in self.sent[-1][1]["reply_markup"]["inline_keyboard"] for b in row]
        self.assertFalse(any(b.startswith("adslaunch:") for b in btns))
        self.assertTrue(any(b.startswith("adskeep:") for b in btns))
        self.assertEqual(ap.launch("i1", 10)["code"], "budget_type")

    def test_other_active_ad_in_adset_refuses_launch(self):
        self._abo()
        self.fake.ads[1]["status"] = "ACTIVE"                                    # a live sibling we did not build
        self.assertTrue(studio.build_paused("i1")["ok"])
        m = studio._find("i1")["meta"]
        self.assertFalse(m["launchable"])
        self.assertIn("other ad(s) in this ad set are switched on", m["blockers"][0])
        r = ap.launch("i1", 10)
        self.assertEqual(r["code"], "others")
        self.assertIn("Flyer — Website - Copy", r["error"])
        self.assertNotIn("ACTIVE", self.fake.statuses_written())                 # nothing switched on

    def test_campaign_would_start_another_adset(self):
        self._abo()
        self.fake.sets.append({"id": "S3", "name": "Old set", "campaign_id": "CWEB", "status": "ACTIVE", "daily_budget": "1000"})
        self.assertTrue(studio.build_paused("i1")["ok"])
        r = ap.launch("i1", 10)
        self.assertEqual(r["code"], "others")
        self.assertIn("Old set", r["error"])

    def test_clean_abo_adset_launches_and_undoes(self):
        self._abo()
        self.assertTrue(studio.build_paused("i1")["ok"])
        self.assertTrue(studio._find("i1")["meta"]["launchable"])
        self.launched = True
        r = ap.launch("i1", 10)
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.fake._obj(self.fake.sets, "SWEB")["daily_budget"], "1000")
        self.assertEqual({self.fake._obj(self.fake.ads, "NEW1")["status"], self.fake._obj(self.fake.sets, "SWEB")["status"],
                          self.fake._obj(self.fake.camps, "CWEB")["status"]}, {"ACTIVE"})
        self.assertEqual(self.fake._obj(self.fake.ads, "AWEB")["status"], "PAUSED")   # siblings untouched
        self.assertTrue(ap.undo(r["action"]["aid"])["ok"])
        self.assertEqual(self.fake._obj(self.fake.camps, "CWEB")["status"], "PAUSED")

    def test_build_failure_is_a_plain_card(self):
        tg_card = tg._new("concept", "i1", imageUrl="https://cdn.example.test/img1.png", title="T")
        self.report["ads"] = []
        tg.h_build(tg_card["id"])
        text = self.sent[-1][1]["text"]
        self.assertIn("⚠ Build failed — no existing ad set", text)
        self.assertIn("Nothing was switched on", text)
        self.assertNotIn("Traceback", text)
        with mock.patch.object(studio, "build", side_effect=RuntimeError("boom")):
            c2 = tg._new("concept", "i1", imageUrl="u", title="T")
            tg.h_build(c2["id"])
        self.assertIn("build stopped (RuntimeError)", self.sent[-1][1]["text"])


class TemplateIdentity(unittest.TestCase):
    """A Build puts new ads under the real Instagram account, even when the template ad carries the
    old Page-backed identity (17841439350588476). Added 2026-10-31 with the ad identity switch."""

    def test_our_page_gets_the_real_account(self):
        self.assertEqual(studio._template(WEB_CREATIVE)["instagram"], "17841436257715501")

    def test_creative_with_no_identity_gets_it_too(self):
        cr = {"object_story_spec": {"page_id": studio.PAGE_ID}}
        self.assertEqual(studio._template(cr)["instagram"], "17841436257715501")

    def test_another_page_keeps_its_own_identity(self):
        cr = {"object_story_spec": {"page_id": "111", "instagram_user_id": "999"}}
        self.assertEqual(studio._template(cr)["instagram"], "999")       # never cross brands

    def test_empty_override_falls_back_to_the_template(self):
        with mock.patch.object(studio, "IG_ACTOR", ""):
            self.assertEqual(studio._template(WEB_CREATIVE)["instagram"], "17841439350588476")


if __name__ == "__main__":
    unittest.main()
