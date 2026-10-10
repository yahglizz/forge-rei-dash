"""python3 -m unittest test_daycare_family_forms — read-through to the form project's Blob store."""
import json
import unittest
from unittest import mock

import daycare_family_forms as ff

GOOD = "family-forms/atob/2026-10/20261009T183205Z__a1B2c3__Maria_Lopez__Ana_Lopez.pdf"
ENV = {"FAMILY_FORMS_READ_KEY": "k" * 40}


class FamilyForms(unittest.TestCase):
    def setUp(self):
        ff._cache.update(at=0.0, forms=None)

    def test_unconfigured_is_a_hint_not_an_error(self):
        out = ff.view({})
        self.assertTrue(out["ok"])
        self.assertFalse(out["configured"])
        self.assertEqual(out["forms"], [])

    def test_view_keeps_only_well_formed_paths_and_labels_brand(self):
        body = json.dumps({"ok": True, "forms": [
            {"path": GOOD, "brand": "atob", "child": "Maria Lopez"},
            {"path": "../../etc/passwd", "brand": "atob"},
            {"path": "family-forms/xyz/2026-10/x.pdf"}]}).encode()
        with mock.patch.object(ff, "_get", return_value=body):
            out = ff.view(ENV, now=100.0)
        self.assertEqual([f["path"] for f in out["forms"]], [GOOD])
        self.assertEqual(out["forms"][0]["brand_label"], "A Touch of Blessings")

    def test_outage_serves_last_good_list_flagged_stale(self):
        with mock.patch.object(ff, "_get", return_value=json.dumps({"forms": [{"path": GOOD, "brand": "atob"}]}).encode()):
            ff.view(ENV, now=100.0)
        with mock.patch.object(ff, "_get", side_effect=ff.FormsError(502, "Forms store unavailable")):
            out = ff.view(ENV, now=200.0)  # past the 30s cache
        self.assertTrue(out["stale"])
        self.assertEqual(len(out["forms"]), 1)

    def test_outage_with_no_cache_reports_error_without_leaking_anything(self):
        with mock.patch.object(ff, "_get", side_effect=ff.FormsError(502, "Forms store unavailable")):
            out = ff.view(ENV, now=100.0)
        self.assertEqual(out["error"], "Forms store unavailable")
        self.assertNotIn("kkkk", json.dumps(out))

    def test_fetch_pdf_refuses_bad_paths_before_any_network_call(self):
        with mock.patch.object(ff, "_get") as get:
            for bad in ("", None, "../x.pdf", GOOD + "/../..", "family-forms/atob/x.pdf"):
                with self.assertRaises(ff.FormsError):
                    ff.fetch_pdf(ENV, bad)
            get.assert_not_called()

    def test_fetch_pdf_only_returns_a_pdf(self):
        with mock.patch.object(ff, "_get", return_value=b"<html>login</html>"):
            with self.assertRaises(ff.FormsError):
                ff.fetch_pdf(ENV, GOOD)
        with mock.patch.object(ff, "_get", return_value=b"%PDF-1.4\n..."):
            self.assertTrue(ff.fetch_pdf(ENV, GOOD).startswith(b"%PDF-"))

    def test_download_name_is_ascii(self):
        self.assertEqual(ff.download_name(GOOD), "ATOB-Family-Form_Maria_Lopez_2026-10-09.pdf")


if __name__ == "__main__":
    unittest.main()
