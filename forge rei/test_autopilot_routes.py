import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("FORGE_MARCUS", "0")

import connector


HERE = Path(__file__).resolve().parent


class AutopilotRouteTests(unittest.TestCase):
    def _post(self, body, *, allowed=True, origin=None):
        payload = json.dumps(body).encode("utf-8")
        handler = object.__new__(connector.Handler)
        handler.path = "/api/autopilot/toggle"
        handler.headers = {
            "Host": "localhost:7799",
            "Content-Length": str(len(payload)),
        }
        if origin is not None:
            handler.headers["Origin"] = origin
        handler.rfile = io.BytesIO(payload)
        handler._dashboard_client_allowed = lambda: allowed
        responses = []
        handler._send_json = (
            lambda obj, code=200, headers=None: responses.append((code, obj))
        )

        connector.Handler.do_POST(handler)

        self.assertEqual(1, len(responses))
        return responses[0]

    def test_status_route_delegates_to_autopilot_status(self):
        expected = {
            "enabled": False,
            "sentToday": 0,
            "cap": 10,
            "day": "2026-07-30",
            "log": [],
        }
        with mock.patch.object(
                connector.autopilot, "status", return_value=expected) as status:
            result = connector.ROUTES["/api/autopilot/status"]({})

        self.assertIs(expected, result)
        status.assert_called_once_with()

    def test_autopilot_state_defaults_off_when_no_state_file_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "autopilot.json"
            with mock.patch.object(connector.autopilot, "STATE", state):
                result = connector.autopilot.status()

        self.assertFalse(result["enabled"])
        self.assertEqual(0, result["sentToday"])
        self.assertFalse(state.exists())

    def test_toggle_handler_delegates_false_to_autopilot(self):
        expected = {"enabled": False, "sentToday": 0, "cap": 10}
        with mock.patch.object(
                connector.autopilot, "set_enabled", return_value=expected) as set_enabled:
            code, result = self._post({"enabled": False})

        self.assertEqual(200, code)
        self.assertIs(expected, result)
        set_enabled.assert_called_once_with(False)

    def test_toggle_rejects_non_boolean_enabled_without_changing_state(self):
        with mock.patch.object(connector.autopilot, "set_enabled") as set_enabled:
            code, result = self._post({"enabled": "false"})

        self.assertEqual(400, code)
        self.assertEqual({"error": "enabled must be a boolean"}, result)
        set_enabled.assert_not_called()

    def test_toggle_keeps_private_dashboard_and_same_origin_guards(self):
        for request in (
                {"allowed": False, "origin": None, "expected": "private dashboard access required"},
                {"allowed": True, "origin": "https://evil.example", "expected": "same-origin request required"},
        ):
            with self.subTest(request=request), mock.patch.object(
                    connector.autopilot, "set_enabled") as set_enabled:
                code, result = self._post(
                    {"enabled": False},
                    allowed=request["allowed"],
                    origin=request["origin"],
                )
            self.assertEqual(403, code)
            self.assertEqual(request["expected"], result["error"])
            set_enabled.assert_not_called()

    def test_ace_panel_has_a_separate_reengagement_autopilot_control(self):
        source = (HERE / "ace.jsx").read_text(encoding="utf-8")
        self.assertIn('window.useApi("/api/autopilot/status"', source)
        self.assertIn('window.apiPost("/api/autopilot/toggle", { enabled:', source)
        self.assertIn("Re-engagement Autopilot", source)
        self.assertIn("const autopilotReady =", source)
        self.assertIn("disabled={autopilotBusy || !autopilotReady}", source)

        checked = subprocess.run(
            ["node", str(HERE / "deploy" / "valjsx.js"), str(HERE / "ace.jsx")],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)


if __name__ == "__main__":
    unittest.main()
