"""Regression tests for Marcus's tracked seller-message classifier."""

import ast
import importlib
import importlib.util
import inspect
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import ace
import brain_io
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

NOT_DENIALS = (
    "im not in a huge rush",
    "im not in a position to sell yet",
    "im not the only owner",
    "im not at the house right now",
    "im not really sure what its worth",
    "im not against selling",
    "im not in town till friday",
    "im not a cash buyer im the owner",
)

TRUE_DENIALS = (
    "I don't know you",
    "wrong number",
    "wrong person",
    "I think you have the wrong number",
    "Sorry but wrong number",
    "you have the wrong number, I don't know you",
    "im not the owner",
    "im not the seller",
    "i dont own it",
    "never owned it",
    "thats not me",
    "thats not my house anymore",
)

NAMED_IDENTITY_DENIALS = (
    ("THIS IS NOT KRISTEN. I've had this number for 5 years.", "Kristen Moffett"),
    ("I am not geraldine", "Geraldine Brown"),
)

DENIAL_PHRASE_CONTINUATIONS = (
    "I don't own it outright; there is a mortgage",
    "I've never owned an investment property; this is my primary home",
    "That's not me refusing; I need time",
)

COMPLETE_SELLER_CONTEXT = (
    "I'm not home.",
    "I am not local.",
    "I'm not there.",
)

AMBIGUOUS_PHRASE_SELLER_CONTEXT = (
    "I don't know you, but yes, I'm open to selling",
    "You have the wrong price, but I would consider selling",
    "100k is the wrong number, but I'd sell for 150k",
    "You have the wrong person listed as owner; I own it with my wife",
    "you called me about my house, yes I'm open to selling",
    "who is this about my property? yes, I would consider selling",
    "what is this regarding the house? I may be open to selling",
)

STANDALONE_DENIALS = (
    "did I call you? No",
    "you called me",
    "who is this?",
    "who are you?",
    "what is this?",
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
            ("i pay the property taxes", "CONTINUE"),
            ("what would you like to know", "CONTINUE"),
            ("what can you tell me about closing", "CONTINUE"),
        )
        for body, expected in cases:
            with self.subTest(body=body):
                self.assertEqual(expected, marcus_engine.classify(body))

    def test_factual_price_vocabulary_is_not_a_price_ask(self):
        cases = (
            "the kitchen range is new",
            "the house numbers are hard to see",
            "we received an offer last week",
            "the previous offer fell through",
        )
        for body in cases:
            with self.subTest(body=body):
                self.assertEqual("CONTINUE", marcus_engine.classify(body))

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

    def test_ordinary_seller_replies_are_not_identity_denials(self):
        for body in NOT_DENIALS:
            with self.subTest(body=body):
                self.assertFalse(marcus_engine._is_denial(body))

    def test_explicit_identity_and_ownership_denials_are_denials(self):
        for body in TRUE_DENIALS:
            with self.subTest(body=body):
                self.assertTrue(marcus_engine._is_denial(body))

    def test_named_identity_denials_are_denials(self):
        for body, expected_name in NAMED_IDENTITY_DENIALS:
            with self.subTest(body=body):
                self.assertTrue(marcus_engine._is_denial(body, expected_name))

    def test_named_identity_denials_require_matching_contact_context(self):
        for body, expected_name in NAMED_IDENTITY_DENIALS:
            with self.subTest(body=body, context="missing"):
                self.assertFalse(marcus_engine._is_denial(body))
            with self.subTest(body=body, context="mismatched"):
                self.assertFalse(marcus_engine._is_denial(body, "Jordan Reed"))

    def test_denial_phrases_inside_seller_context_are_not_denials(self):
        cases = (
            DENIAL_PHRASE_CONTINUATIONS
            + COMPLETE_SELLER_CONTEXT
            + AMBIGUOUS_PHRASE_SELLER_CONTEXT
        )
        for body in cases:
            with self.subTest(body=body):
                self.assertFalse(marcus_engine._is_denial(body))

    def test_standalone_confused_recipient_phrases_remain_denials(self):
        for body in STANDALONE_DENIALS:
            with self.subTest(body=body):
                self.assertTrue(marcus_engine._is_denial(body))

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

    def test_e2e_harness_recognizes_tracked_classifier_source(self):
        harness = Path(__file__).resolve().parent.parent / "forge-test-harness" / "e2e_seller_sim.py"
        tree = ast.parse(harness.read_text(encoding="utf-8"), filename=str(harness))
        probe = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "probe_classifiers"
        )
        production_assignment = next(
            node for node in probe.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "prod"
                    for target in node.targets)
        )
        expression = ast.unparse(production_assignment.value)
        self.assertIn("_is_tracked_classifier_source", expression)
        self.assertIn("src", expression)
        self.assertIn("HERE", expression)
        self.assertNotIn("scan_missed_replies", expression)

    def test_e2e_harness_classifier_source_check_uses_resolved_path_equality(self):
        harness = Path(__file__).resolve().parent.parent / "forge-test-harness" / "e2e_seller_sim.py"
        tree = ast.parse(harness.read_text(encoding="utf-8"), filename=str(harness))
        helper = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_is_tracked_classifier_source"
        )
        module = ast.fix_missing_locations(ast.Module(body=[helper], type_ignores=[]))
        namespace = {"os": os}
        exec(compile(module, str(harness), "exec"), namespace)
        is_tracked = namespace["_is_tracked_classifier_source"]

        with tempfile.TemporaryDirectory() as td:
            repo_dir = Path(td) / "forge-rei"
            tracked = repo_dir / "seller_classify.py"
            normalized_tracked = repo_dir / "nested" / ".." / "seller_classify.py"
            external_scan = Path(td) / "marcus-wholesale-agent" / "scan_missed_replies.py"
            outside_same_name = Path(td) / "other-app" / "seller_classify.py"

            self.assertTrue(is_tracked(str(tracked), str(repo_dir)))
            self.assertTrue(is_tracked(str(normalized_tracked), str(repo_dir)))
            self.assertFalse(is_tracked(str(external_scan), str(repo_dir)))
            self.assertFalse(is_tracked(str(outside_same_name), str(repo_dir)))
            self.assertFalse(is_tracked(None, str(repo_dir)))

    def test_prompt_skills_fall_back_to_repo_when_vault_is_missing(self):
        with tempfile.TemporaryDirectory() as td:
            missing_vault = Path(td) / "missing-vault"
            with mock.patch.object(brain_io, "VAULT", missing_vault):
                engine = MarcusEngineStatusStub()
                self.assertTrue(marcus_engine.MarcusEngine._load_reply_rubric(engine))
                self.assertTrue(marcus_engine.MarcusEngine._load_playbook(engine))
                sources = marcus_engine.skill_sources()

        required = {
            "replyRubric": ("seller-reply-playbook.md",),
            "playbook": (
                "marcus-playbook.md",
                "yahjair-voice.md",
                "wholesale-seller-texter.md",
                "closing-plays.md",
            ),
        }
        for group, names in required.items():
            entries = sources[group]
            if group == "replyRubric":
                entries = {names[0]: entries}
            for name in names:
                with self.subTest(skill=name):
                    metadata = entries[name]
                    self.assertGreater(metadata["bytes"], 0)
                    self.assertEqual("repo", metadata["source"])
                    self.assertEqual(name, Path(metadata["path"]).name)
                    self.assertIn("forge-marcus", Path(metadata["path"]).parts)
                    self.assertEqual({"path", "source", "bytes"}, set(metadata))

    def test_vault_skill_overrides_matching_repo_seed(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td)
            skills = vault / "Skills"
            skills.mkdir()
            override = skills / "marcus-playbook.md"
            override.write_text("vault-only marker", encoding="utf-8")
            with mock.patch.object(brain_io, "VAULT", vault):
                engine = MarcusEngineStatusStub()
                playbook = marcus_engine.MarcusEngine._load_playbook(engine)
                sources = marcus_engine.skill_sources()

        metadata = sources["playbook"]["marcus-playbook.md"]
        self.assertIn("vault-only marker", playbook)
        self.assertEqual(str(override), metadata["path"])
        self.assertEqual("vault", metadata["source"])
        self.assertEqual(len("vault-only marker".encode("utf-8")), metadata["bytes"])

    def test_utf8_vault_skill_preserves_prompt_text_and_byte_count(self):
        expected = "Seller’s timeline — call-ready ✓"
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td)
            skills = vault / "Skills"
            skills.mkdir()
            override = skills / "yahjair-voice.md"
            override.write_text(expected, encoding="utf-8")
            with mock.patch.object(brain_io, "VAULT", vault):
                engine = MarcusEngineStatusStub()
                playbook = marcus_engine.MarcusEngine._load_playbook(engine)
                sources = marcus_engine.skill_sources()

        self.assertIn(expected, playbook)
        self.assertEqual(
            len(expected.encode("utf-8")),
            sources["playbook"]["yahjair-voice.md"]["bytes"],
        )

    def test_prompt_health_is_metadata_only_in_marcus_and_ace_status(self):
        with tempfile.TemporaryDirectory() as td:
            missing_vault = Path(td) / "missing-vault"
            with mock.patch.object(brain_io, "VAULT", missing_vault):
                expected = marcus_engine.skill_sources()
                marcus_status = marcus_engine.MarcusEngine.status(MarcusEngineStatusStub())
                with mock.patch.object(ace, "_load", return_value={
                    "mode": "off", "sentToday": 0, "day": ace._today_key(), "log": [],
                }):
                    ace_status = ace.status()

        self.assertEqual(expected, marcus_status["promptHealth"])
        self.assertEqual(expected, ace_status["promptHealth"])
        self.assertFalse(ace_status["degradedPrompt"])
        self.assertNotIn("vault-only marker", repr(ace_status["promptHealth"]))

    def test_ace_prompt_is_degraded_when_a_required_skill_is_empty(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td)
            skills = vault / "Skills"
            skills.mkdir()
            (skills / "seller-reply-playbook.md").write_text("", encoding="utf-8")
            with mock.patch.object(brain_io, "VAULT", vault):
                with mock.patch.object(ace, "_load", return_value={
                    "mode": "off", "sentToday": 0, "day": ace._today_key(), "log": [],
                }):
                    ace_status = ace.status()

        self.assertEqual(0, ace_status["promptHealth"]["replyRubric"]["bytes"])
        self.assertTrue(ace_status["degradedPrompt"])


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
