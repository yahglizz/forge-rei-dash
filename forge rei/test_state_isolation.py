"""Tests never write the live marcus_state/ (audit log, agent bus, chat history);
a normal (non-test) entry point still does. No network."""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIVE = HERE / "marcus_state"

# Deliberately NOT setting FORGE_ACTION_LOG: the guard alone must keep us off the live path.
os.environ.pop("FORGE_ACTION_LOG", None)
sys.path.insert(0, str(HERE))
import action_log  # noqa: E402
import agent_bus  # noqa: E402
import agents_history  # noqa: E402
import forge_atomic  # noqa: E402


def _digest(p):
    return hashlib.md5(p.read_bytes()).hexdigest() if p.exists() else None


class UnderTest(unittest.TestCase):
    def test_paths_redirected_and_live_files_untouched(self):
        mods = (action_log, agent_bus, agents_history)
        live = {m: LIVE / m.STATE.name for m in mods}
        before = {m: _digest(p) for m, p in live.items()}
        for m in mods:
            self.assertFalse(str(m.STATE.resolve()).startswith(str(LIVE.resolve())), m.__name__)
        self.assertTrue(action_log.record("test", "isolation-probe"))
        self.assertTrue(action_log.flush())
        agent_bus.send("scout", "marcus", "note", "isolation probe")
        agents_history.record("scout", "isolation probe", "ok")
        self.assertIn("isolation-probe", action_log.STATE.read_text())
        self.assertEqual(before, {m: _digest(p) for m, p in live.items()})
        self.assertEqual(os.environ.get("FORGE_UNDER_TEST"), "1")   # children inherit

    def test_explicit_live_override_is_refused_under_test(self):
        p = forge_atomic.guard_state_path(LIVE / "agent_actions.jsonl")
        self.assertNotEqual(p.resolve(), (LIVE / "agent_actions.jsonl").resolve())
        other = Path(tempfile.gettempdir()) / "x.jsonl"
        self.assertEqual(forge_atomic.guard_state_path(other), other)


class NormalRun(unittest.TestCase):
    """A copy of the modules in a temp dir: a `connector.py` entry point writes its own
    marcus_state (production behaviour); a `test_*.py` entry point does not."""

    def _run(self, script_name):
        td = Path(tempfile.mkdtemp(prefix="forge-normal-run-"))
        self.addCleanup(shutil.rmtree, td, True)
        for f in ("action_log.py", "forge_atomic.py"):
            shutil.copy(HERE / f, td / f)
        (td / script_name).write_text(
            "import action_log\n"
            "action_log.record('marcus', 'normal-run-probe')\n"
            "assert action_log.flush()\n"
            "print(action_log.STATE)\n")
        env = {k: v for k, v in os.environ.items()
               if k not in ("FORGE_UNDER_TEST", "FORGE_ACTION_LOG")}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        out = subprocess.run([sys.executable, script_name], cwd=td, env=env,
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        return td / "marcus_state" / "agent_actions.jsonl", Path(out.stdout.strip())

    def test_connector_entry_point_writes_real_path(self):
        real, used = self._run("connector.py")
        self.assertEqual(used.resolve(), real.resolve())
        self.assertIn("normal-run-probe", real.read_text())

    def test_test_entry_point_never_writes_real_path(self):
        real, used = self._run("test_probe.py")
        self.assertFalse(real.exists())
        self.assertIn("normal-run-probe", used.read_text())


if __name__ == "__main__":
    unittest.main()
