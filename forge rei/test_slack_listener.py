"""Slack Socket Mode listener: ack-before-dispatch, envelope/event dedupe, routing, reconnect,
missing SDK, flag-off start-up, and no secrets/bodies in logs.
Run: FORGE_MARCUS=0 python3 -m unittest test_slack_listener  (fake client: no network, no threads
left running; handle_interaction / slack_inbound stubbed)."""
import ast
import contextlib
import io
import logging
import os
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

if "slack_io" not in sys.modules:
    os.environ["FORGE_SLACK_CONFIG_DIR"] = tempfile.mkdtemp(prefix="slack_cfg_")

import slack_io  # noqa: E402

HERE = Path(__file__).resolve().parent
SECRET = "xapp-1-SECRETAPPTOKEN"
BODY = "seller Jane 215-555-0100 wants 90k"


class Req:
    def __init__(self, type, envelope_id, payload, retry_attempt=None):
        self.type, self.envelope_id, self.payload = type, envelope_id, payload
        self.retry_attempt = retry_attempt


class FakeClient:
    """slack_sdk builtin SocketModeClient surface, driven by the test thread."""
    def __init__(self, log, drop_after_connect=False):
        self.socket_mode_request_listeners = []
        self.log, self.drop = log, drop_after_connect
        self.connected = threading.Event()
        self.up, self.closed = False, False

    def connect(self):
        self.up = not self.drop
        self.connected.set()

    def is_connected(self):
        return self.up

    def close(self):
        self.up, self.closed = False, True

    def send_socket_mode_response(self, resp):
        self.log.append(("ack", resp["envelope_id"], threading.get_ident()))

    def feed(self, req):
        for fn in self.socket_mode_request_listeners:
            fn(self, req)


class Harness:
    """Run run_forever on a thread with one or more fake clients."""
    def __init__(self, n_clients=1, drops=()):
        self.log, self.stop = [], threading.Event()
        self.clients = [FakeClient(self.log, i in drops) for i in range(n_clients)]
        self.made = []

    def factory(self):
        c = self.clients[min(len(self.made), len(self.clients) - 1)]
        self.made.append(c)
        return c

    def __enter__(self):
        self.t = threading.Thread(target=slack_io.run_forever,
                                  kwargs={"stop": self.stop, "client_factory": self.factory}, daemon=True)
        self.t.start()
        assert self.clients[-1].connected.wait(2), "client never connected"
        return self

    def __exit__(self, *a):
        self.stop.set()
        self.t.join(3)
        assert not self.t.is_alive(), "run_forever did not stop"


def interactive(eid, trigger="T1"):
    return Req("interactive", eid, {"type": "block_actions", "trigger_id": trigger,
                                    "actions": [{"value": "approve:1"}]})


def event(eid, event_id="Ev1", retry=None):
    return Req("events_api", eid, {"event_id": event_id,
                                   "event": {"type": "message", "text": BODY, "user": "U1"}},
               retry_attempt=retry)


class ListenerTests(unittest.TestCase):
    def setUp(self):
        slack_io._ENVELOPES.clear()
        slack_io._WARNED.clear()
        self.done = threading.Event()
        self.calls = []
        self.patches = [mock.patch.object(slack_io, "_POLL", 0.01),
                        mock.patch.object(slack_io, "_BACKOFF_MIN", 0.01),
                        mock.patch.object(slack_io, "_BACKOFF_MAX", 0.02)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()

    def _record(self, name, log=None):
        def fn(*a, **kw):
            self.calls.append((name, threading.get_ident(), a, kw))
            if log is not None:
                log.append(("dispatch", name))
            self.done.set()
            return {"ok": True}
        return fn

    def _wait_calls(self, n, timeout=2):
        end = threading.Event()
        for _ in range(int(timeout / 0.01)):
            if len(self.calls) >= n:
                return True
            end.wait(0.01)
        return False

    def test_envelope_acked_before_dispatch(self):
        with Harness() as h:
            with mock.patch.object(slack_io, "handle_interaction", self._record("tap", h.log)):
                h.clients[0].feed(interactive("E1"))
                self.assertTrue(self.done.wait(2))
        self.assertEqual(h.log[0][:2], ("ack", "E1"))
        self.assertEqual(h.log[1], ("dispatch", "tap"))
        self.assertEqual(h.log[0][2], threading.get_ident())          # ack on the receiving thread
        self.assertNotEqual(self.calls[0][1], threading.get_ident())   # work on a worker thread
        self.assertEqual(self.calls[0][3], {"envelope_id": "E1"})

    def test_duplicate_envelope_dispatched_once(self):
        with Harness() as h:
            with mock.patch.object(slack_io, "handle_interaction", self._record("tap")):
                h.clients[0].feed(interactive("E1", "T1"))
                h.clients[0].feed(interactive("E1", "T1"))
                self.assertTrue(self.done.wait(2))
                threading.Event().wait(0.1)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual([x[1] for x in h.log if x[0] == "ack"], ["E1", "E1"])   # both still acked

    def test_retry_same_event_id_dispatched_once(self):
        mod = types.SimpleNamespace(handle_message_event=self._record("msg"),
                                    handle_slash=self._record("slash"))
        with mock.patch.dict(sys.modules, {"slack_inbound": mod}), Harness() as h:
            h.clients[0].feed(event("E1", "Ev9"))
            h.clients[0].feed(event("E2", "Ev9", retry=1))     # Slack retry: new envelope, same event
            self.assertTrue(self.done.wait(2))
            threading.Event().wait(0.1)
        self.assertEqual([c[0] for c in self.calls], ["msg"])
        self.assertEqual(self.calls[0][2][0]["type"], "message")   # the inner event, not the envelope

    def test_slash_routed_and_reply_shown_to_user(self):
        mod = types.SimpleNamespace(handle_slash=self._record("slash"),
                                    handle_message_event=self._record("msg"))
        shown = []
        with mock.patch.dict(sys.modules, {"slack_inbound": mod}), \
                mock.patch.object(slack_io, "_respond", lambda p, b: shown.append(b)), Harness() as h:
            h.clients[0].feed(Req("slash_commands", "E7", {"command": "/forge", "text": "today",
                                                          "trigger_id": "T7"}))
            self.assertTrue(self.done.wait(2))
            threading.Event().wait(0.05)
        self.assertEqual(self.calls[0][0], "slash")
        self.assertEqual(shown, [{"ok": True}])

    def test_unknown_envelope_type_ignored(self):
        with Harness() as h, mock.patch.object(slack_io, "handle_interaction", self._record("tap")):
            h.clients[0].feed(Req("hello", "E5", {}))
            h.clients[0].feed(Req("disconnect", "E6", {}))
            threading.Event().wait(0.1)
        self.assertEqual(self.calls, [])
        self.assertEqual([x[1] for x in h.log if x[0] == "ack"], ["E5", "E6"])

    def test_missing_inbound_module_ignored(self):
        with mock.patch.dict(sys.modules, {"slack_inbound": None}), Harness() as h:
            h.clients[0].feed(event("E1"))
            threading.Event().wait(0.1)
        self.assertIn("inbound", slack_io._WARNED)

    def test_reconnect_after_disconnect(self):
        with Harness(n_clients=2, drops=(0,)) as h:
            self.assertTrue(h.clients[1].connected.wait(2))
            self.assertTrue(h.clients[0].closed)
            for _ in range(100):
                if slack_io.status()["connected"]:
                    break
                threading.Event().wait(0.01)
            self.assertTrue(slack_io.status()["connected"])
        self.assertGreaterEqual(len(h.made), 2)
        self.assertFalse(slack_io.status()["connected"])

    def test_connect_error_retried_and_redacted(self):
        log, made, ok = [], [], FakeClient([])

        def factory():
            made.append(1)
            if len(made) == 1:
                raise RuntimeError(f"boom token={SECRET}")
            return ok
        stop = threading.Event()
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"SLACK_APP_TOKEN": SECRET}), contextlib.redirect_stdout(out):
            t = threading.Thread(target=slack_io.run_forever, args=(stop, factory), daemon=True)
            t.start()
            self.assertTrue(ok.connected.wait(2))
            stop.set()
            t.join(3)
        self.assertNotIn(SECRET, out.getvalue())
        self.assertNotIn(SECRET, str(slack_io.status()))

    def test_missing_sdk_returns_without_raising(self):
        blocked = {k: None for k in ("slack_sdk", "slack_sdk.socket_mode", "slack_sdk.socket_mode.builtin")}
        out = io.StringIO()
        with mock.patch.dict(sys.modules, blocked), mock.patch.dict(os.environ, {"SLACK_APP_TOKEN": SECRET}), \
                contextlib.redirect_stdout(out):
            t = threading.Thread(target=slack_io.run_forever, daemon=True)
            t.start()
            t.join(2)
            self.assertFalse(t.is_alive())
            slack_io.run_forever()               # second call: still quiet, logged once
        self.assertEqual(out.getvalue().count("slack_sdk not installed"), 1)
        self.assertNotIn(SECRET, out.getvalue())

    def test_listener_not_started_without_flags(self):
        tree = ast.parse((HERE / "connector.py").read_text())
        top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertFalse(any("slack" in a.name for n in top for a in n.names),
                         "connector must not import slack_* at module level")

        def is_slack_flag(test):
            src = ast.unparse(test) if hasattr(ast, "unparse") else ""
            return ("FORGE_SLACK" in ast.dump(test)) and (not src or "!= '0'" in src or '!= "0"' in src)

        starts = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "Thread":
                if any(k.arg == "target" and "run_forever" in ast.dump(k.value) and "slack_io" in ast.dump(k.value)
                       for k in node.keywords):
                    starts.append(node)
        self.assertEqual(len(starts), 1, "exactly one slack listener thread start")

        def parents_of(target, node, chain):
            for child in ast.iter_child_nodes(node):
                if child is target:
                    return chain + [node]
                hit = parents_of(target, child, chain + [node])
                if hit:
                    return hit
            return None
        chain = parents_of(starts[0], tree, [])
        ifs = [n for n in chain if isinstance(n, ast.If)]
        self.assertTrue(any(isinstance(n.test, ast.Name) and n.test.id == "LOOPS_ENABLED" for n in ifs),
                        "slack listener must sit inside `if LOOPS_ENABLED:` (FORGE_MARCUS=1)")
        self.assertTrue(any(is_slack_flag(n.test) for n in ifs), "and behind FORGE_SLACK != '0'")
        self.assertTrue(any(isinstance(n, ast.Try) for n in chain), "inside try/except")
        default = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                   and getattr(n.func, "attr", "") == "get" and n.args
                   and isinstance(n.args[0], ast.Constant) and n.args[0].value == "FORGE_SLACK"]
        self.assertTrue(default and all(len(n.args) > 1 and n.args[1].value == "0" for n in default),
                        "FORGE_SLACK defaults to off")

    def test_no_token_or_body_in_logs(self):
        out, err, logs = io.StringIO(), io.StringIO(), io.StringIO()
        handler = logging.StreamHandler(logs)
        root = logging.getLogger()
        root.addHandler(handler)
        old = root.level
        root.setLevel(logging.DEBUG)

        def boom(*a, **kw):
            self.done.set()
            raise RuntimeError(BODY + " " + SECRET)
        mod = types.SimpleNamespace(handle_message_event=boom, handle_slash=boom)
        try:
            with mock.patch.dict(os.environ, {"SLACK_APP_TOKEN": SECRET, "SLACK_BOT_TOKEN": "xoxb-SECRETBOT"}), \
                    mock.patch.dict(sys.modules, {"slack_inbound": mod}), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), Harness() as h:
                h.clients[0].feed(event("E1", "Ev1"))
                h.clients[0].feed(event("E2", "Ev1", retry=1))
                h.clients[0].feed(Req("weird", "E3", {"text": BODY}))
                self.assertTrue(self.done.wait(2))
                threading.Event().wait(0.1)
        finally:
            root.removeHandler(handler)
            root.setLevel(old)
        text = out.getvalue() + err.getvalue() + logs.getvalue()
        self.assertIn("dispatch events_api failed: RuntimeError", text)
        self.assertIn("duplicate envelope", text)
        for bad in (SECRET, "xoxb-SECRETBOT", "Jane", "215-555"):
            self.assertNotIn(bad, text)


if __name__ == "__main__":
    unittest.main()
