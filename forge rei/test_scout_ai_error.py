"""Scout surfaces a failed Claude scoring batch (aiError) instead of claiming "Claude"
scoring while every lead is rule-scored. Claude is faked; no network."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import review_agent  # noqa: E402
import scout_triage  # noqa: E402


class ScoutAiError(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        p = mock.patch.object(scout_triage, "STATE", Path(td.name) / "scout.json")
        p.start()
        self.addCleanup(p.stop)
        self.eng = scout_triage.ScoutEngine(lambda *a, **k: {}, lambda *a, **k: {}, "loc")

    def test_failed_batch_sets_ai_error_and_success_clears_it(self):
        boom = RuntimeError("Anthropic API error (400): credit balance is too low")
        with mock.patch.object(review_agent, "_claude", side_effect=boom):
            self.assertEqual(self.eng._claude_batch("k", [(0, "I want to sell asap")]), {})
        self.assertIn("credit balance", self.eng.summary()["aiError"])
        self.assertIn("credit balance", self.eng.overview()["aiError"])
        ok = '[{"i":0,"intent":"ready","motivation":90,"askingPrice":null,"reason":"x"}]'
        with mock.patch.object(review_agent, "_claude", return_value=ok):
            self.assertIn(0, self.eng._claude_batch("k", [(0, "I want to sell asap")]))
        self.assertIsNone(self.eng.summary()["aiError"])


if __name__ == "__main__":
    unittest.main()
