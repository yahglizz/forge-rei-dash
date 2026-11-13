"""agent_env: one label in, only that label's keys out. Fake master via FORGE_MASTER_ENV."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agent_env

MASTER = """# === AI ===
FAKE_KEY__AGENCY=x1
ANTHROPIC_API_KEY__WHOLESALE="w-anth"
ANTHROPIC_API_KEY__AGENCY='a-anth'
GHL_API_KEY__DAYCARE=d-ghl
STRIPE_SECRET_KEY__DAYCARE_TEST=d-test
export TELEGRAM_BOT_TOKEN=tg
HIGGSFIELD_API_KEY=gh
EMPTY_KEY__AGENCY=
"""


class AgentEnvTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.path = Path(d) / "master.env"
        self.path.write_text(MASTER)
        self.env = mock.patch.dict(os.environ, {"FORGE_MASTER_ENV": str(self.path)})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_own_label_only(self):
        a = agent_env.load_agent_env("agency")
        self.assertEqual(a["FAKE_KEY"], "x1")
        self.assertEqual(a["ANTHROPIC_API_KEY"], "a-anth")
        self.assertEqual(a["HIGGSFIELD_API_KEY"], "gh")            # listed shared name for agency
        w = agent_env.load_agent_env("WHOLESALE")
        self.assertNotIn("FAKE_KEY", w)                      # wholesale never sees agency's key
        self.assertEqual(w["ANTHROPIC_API_KEY"], "w-anth")
        self.assertNotIn("HIGGSFIELD_API_KEY", w)                  # shared name not listed for wholesale
        self.assertEqual(w["TELEGRAM_BOT_TOKEN"], "tg")
        self.assertNotIn("x1", w.values())

    def test_missing_stays_missing(self):
        a = agent_env.load_agent_env("AGENCY")
        self.assertNotIn("EMPTY_KEY", a)                     # blank = absent
        self.assertNotIn("GHL_API_KEY", a)                   # only daycare has one: no borrowing
        dc = agent_env.load_agent_env("DAYCARE")
        self.assertNotIn("ANTHROPIC_API_KEY", dc)
        self.assertEqual(dc["STRIPE_SECRET_KEY__DAYCARE_TEST"], "d-test")   # literal shared name
        self.assertNotIn("STRIPE_SECRET_KEY", dc)            # __DAYCARE_TEST is not __DAYCARE

    def test_file_keys_replaced_config_kept(self):
        cfg = agent_env.with_master("DROPSHIP", {"ANTHROPIC_API_KEY": "file-key", "SHOPIFY_STORE_DOMAIN": "s",
                                                 "SHOPIFY_ADMIN_TOKEN": "file-tok"})
        self.assertEqual(cfg, {"SHOPIFY_STORE_DOMAIN": "s", "TELEGRAM_BOT_TOKEN": "tg",
                               "HIGGSFIELD_API_KEY": "gh"})   # file key + token gone, master shared in

    def test_no_master_means_no_keys_and_no_values_logged(self):
        os.environ["FORGE_MASTER_ENV"] = str(self.path) + ".missing"
        err, out = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            self.assertEqual(agent_env.load_agent_env("AGENCY"), {})
            os.environ["FORGE_MASTER_ENV"] = str(self.path)
            agent_env.load_agent_env("AGENCY")
            agent_env.with_master("DAYCARE", {"GHL_API_KEY": "file"})
        logs = err.getvalue() + out.getvalue()
        for v in ("x1", "w-anth", "a-anth", "d-ghl", "d-test", "tg", "gh", "file"):
            self.assertNotIn(v, logs)

    def test_tests_never_read_real_master(self):
        os.environ.pop("FORGE_MASTER_ENV")
        self.assertEqual(agent_env.load_agent_env("WHOLESALE"), {})

    def test_bad_label(self):
        with self.assertRaises(ValueError):
            agent_env.load_agent_env("WHOLESALE__AGENCY")


if __name__ == "__main__":
    unittest.main()
