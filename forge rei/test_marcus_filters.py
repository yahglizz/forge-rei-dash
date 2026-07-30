"""Regression tests for Marcus's tracked seller-message classifier."""

import importlib
import importlib.util
import inspect
from pathlib import Path
import unittest

import marcus_engine


PRICE_ASKS = (
    "how much would you give me for it",
    "what kind of numbers are you thinking",
    "whats your offer",
    "what were you thinking",
    "what can you do for it",
    "give me a ballpark",
    "whats the most you can do",
    "what are you offering",
    "how much",
    "whats it worth to you",
    "what number did you have in mind",
    "send me your best",
    "whats your range",
    "what would you pay",
)


class SellerClassifierTests(unittest.TestCase):
    def test_all_real_price_asks_are_price(self):
        for body in PRICE_ASKS:
            with self.subTest(body=body):
                self.assertEqual("PRICE", marcus_engine.classify(body))

    def test_classifier_keywords_respect_word_boundaries(self):
        cases = (
            ("that was a surprise", "CONTINUE"),
            ("the stopwatch is running", "CONTINUE"),
            ("the rangefinder is broken", "CONTINUE"),
            ("the ballparking exercise can wait", "CONTINUE"),
        )
        for body, expected in cases:
            with self.subTest(body=body):
                self.assertEqual(expected, marcus_engine.classify(body))

    def test_core_intents(self):
        cases = (
            ("stop texting me", "DNC"),
            ("please unsubscribe", "DNC"),
            ("remove me from your list", "DNC"),
            ("do not text this number", "DNC"),
            ("who is this", "HELP"),
            ("wrong number", "HELP"),
            ("who are you", "HELP"),
            ("not right now", "NRN"),
            ("maybe in a few months", "NRN"),
            ("yes", "READY"),
            ("i am interested", "READY"),
            ("tell me more", "READY"),
        )
        for body, expected in cases:
            with self.subTest(body=body):
                self.assertEqual(expected, marcus_engine.classify(body))

    def test_tracked_module_exposes_classifier_and_price_safe_drafter(self):
        spec = importlib.util.find_spec("seller_classify")
        self.assertIsNotNone(spec, "seller_classify must be a tracked repo module")
        if spec is None:
            return

        seller_classify = importlib.import_module("seller_classify")
        self.assertIs(marcus_engine.classify, seller_classify.classify)
        draft = seller_classify.draft_reply("Dana", "PRICE")
        self.assertIn("Dana", draft)
        self.assertNotRegex(draft, r"\$\s*\d|\b\d{4,}\b")

    def test_classifier_source_and_status_point_to_tracked_module(self):
        source = Path(inspect.getsourcefile(marcus_engine.classify)).resolve()
        self.assertEqual(Path(__file__).resolve().parent, source.parent)
        self.assertEqual("seller_classify.py", source.name)

        metadata = marcus_engine.classifier_source()
        self.assertEqual(str(source), metadata["classifySource"])
        self.assertEqual("seller_classify", metadata["classifyModule"])
        self.assertTrue(metadata["tracked"])

        engine = MarcusEngineStatusStub()
        self.assertEqual(metadata, marcus_engine.MarcusEngine.status(engine)["classifierSource"])


class MarcusEngineStatusStub:
    """Enough state to exercise status() without loading Marcus's live files."""

    proposals = {}
    enabled = True
    auto_send = False
    auto_send_nrn = False
    anthropic_key = None
    last_poll = None
    poll_interval = 60
    counts = {"proposed": 0, "sent": 0, "suppressed": 0, "dismissed": 0}
    last_error = None


if __name__ == "__main__":
    unittest.main()
