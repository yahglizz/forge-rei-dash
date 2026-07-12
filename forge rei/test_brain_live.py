import tempfile
import unittest
from pathlib import Path

import brain_io


class BrainLiveStatusTest(unittest.TestCase):
    def setUp(self):
        self.orig_vault = brain_io.VAULT
        self.tmp = tempfile.TemporaryDirectory()
        brain_io.VAULT = Path(self.tmp.name)
        (brain_io.VAULT / "Skills").mkdir()

    def tearDown(self):
        brain_io.VAULT = self.orig_vault
        self.tmp.cleanup()

    def test_all_agent_playbooks_report_live(self):
        for names in brain_io.AGENT_SKILLS.values():
            (brain_io.VAULT / "Skills" / names[0]).write_text("# active playbook\n")
        status = brain_io.skill_status()
        self.assertTrue(status["live"], status)
        self.assertEqual(status["total"], status["ready"])
        self.assertTrue(all(c["ready"] for c in status["consumers"].values()))

    def test_missing_consumer_playbook_fails_live(self):
        (brain_io.VAULT / "Skills" / "scout-playbook.md").write_text("# scout\n")
        status = brain_io.skill_status()
        self.assertFalse(status["live"], status)
        self.assertTrue(status["consumers"]["scout"]["ready"])
        self.assertFalse(status["consumers"]["eco"]["ready"])


if __name__ == "__main__":
    unittest.main()
