import os
import tempfile
import unittest
from pathlib import Path

import test_mode


class TestModePhoneValidationTest(unittest.TestCase):
    def setUp(self):
        self.orig_state = test_mode.STATE
        self.orig_env = os.environ.get(test_mode.ENV_PHONES)
        self.tmp = tempfile.TemporaryDirectory()
        test_mode.STATE = Path(self.tmp.name) / "test_mode.json"
        os.environ.pop(test_mode.ENV_PHONES, None)

    def tearDown(self):
        test_mode.STATE = self.orig_state
        if self.orig_env is None:
            os.environ.pop(test_mode.ENV_PHONES, None)
        else:
            os.environ[test_mode.ENV_PHONES] = self.orig_env
        self.tmp.cleanup()

    def test_rejects_incomplete_phone(self):
        self.assertEqual("", test_mode.norm("267910166"))
        status = test_mode.update({"enabled": True, "phones": ["267910166"]})
        self.assertEqual([], status["phones"])
        self.assertFalse(test_mode.is_test("267910166"))

    def test_accepts_ten_digit_and_country_code(self):
        self.assertEqual("2675550100", test_mode.norm("(267) 555-0100"))
        self.assertEqual("2675550100", test_mode.norm("+1 267 555 0100"))
        test_mode.update({"enabled": True, "phones": ["+1 267 555 0100"]})
        self.assertTrue(test_mode.is_test("2675550100"))


if __name__ == "__main__":
    unittest.main()
