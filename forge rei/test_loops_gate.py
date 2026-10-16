"""test_loops_gate.py — FORGE_MARCUS fails SAFE: loops run only when FORGE_MARCUS=1.

Why: the old default was ON, so a plain `./start.sh` on the Mac (which holds every live key)
started a second Scout/Follow-up/Telegram fleet against the same GHL + bot.

Each case imports connector in a fresh subprocess (module-level constant). Hermetic: temp
HOME (no ~/Desktop env files), temp action log + vault. No network.
Run: cd "forge rei" && python3 test_loops_gate.py
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _loops_enabled(value):
    with tempfile.TemporaryDirectory() as tmp:
        env = {k: v for k, v in os.environ.items() if k != "FORGE_MARCUS"}
        env.update(HOME=tmp, FORGE_ACTION_LOG=os.path.join(tmp, "act.jsonl"),
                   FORGE_VAULT=os.path.join(tmp, "vault"), PYTHONDONTWRITEBYTECODE="1")
        if value is not None:
            env["FORGE_MARCUS"] = value
        out = subprocess.run([sys.executable, "-c", "import connector; print(connector.LOOPS_ENABLED)"],
                             cwd=HERE, env=env, capture_output=True, text=True, timeout=120)
        assert out.returncode == 0, out.stderr[-2000:]
        return out.stdout.strip().splitlines()[-1]


class LoopsGateTest(unittest.TestCase):
    def test_default_is_off(self):
        self.assertEqual(_loops_enabled(None), "False")

    def test_one_turns_loops_on(self):
        self.assertEqual(_loops_enabled("1"), "True")

    def test_zero_is_off(self):
        self.assertEqual(_loops_enabled("0"), "False")

    def test_box_unit_sets_flag(self):
        # The box keeps running its loops only because its unit sets FORGE_MARCUS=1.
        unit = (HERE / "deploy" / "setup_droplet.sh").read_text()
        self.assertIn("Environment=FORGE_MARCUS=1", unit)

    def test_mac_starters_are_ui_only(self):
        self.assertIn('FORGE_MARCUS="${FORGE_MARCUS:-0}"', (HERE / "start.sh").read_text())
        self.assertIn("<key>FORGE_MARCUS</key><string>0</string>",
                      (HERE / "install_service.sh").read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
