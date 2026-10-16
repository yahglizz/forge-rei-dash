"""test_ghl_send_retry.py — a GHL message SEND is never auto-retried on timeout/5xx.

Why: GHLClient._req retried every POST on timeout/5xx. A read timeout after GHL accepted
/conversations/messages sent the seller/parent/client the same text twice. Sends now retry
only on 429 (GHL rejected it, nothing went out) and raise GHLSendUnknown otherwise.

Fake opener (urllib.request.urlopen patched), sleep patched. No network, no real keys:
HOME + action log + vault point at a temp dir before connector is imported.
Run: cd "forge rei" && python3 test_ghl_send_retry.py
"""
import io
import json
import os
import socket
import tempfile
import unittest
import urllib.error
from email.message import Message
from unittest import mock

_TMP = tempfile.mkdtemp()
os.environ["HOME"] = _TMP                      # never fold real ~/Desktop *.env keys in
os.environ.setdefault("FORGE_ACTION_LOG", os.path.join(_TMP, "act.jsonl"))
os.environ.setdefault("FORGE_VAULT", os.path.join(_TMP, "vault"))
os.environ.setdefault("FORGE_MARCUS", "0")

import connector  # noqa: E402

SEND = "/conversations/messages"
BODY = {"type": "SMS", "contactId": "c1", "conversationId": "v1", "message": "hi"}


def _http(code, headers=None):
    h = Message()
    for k, v in (headers or {}).items():
        h[k] = v
    return urllib.error.HTTPError("https://x", code, "err", h, io.BytesIO(b'{"message":"boom"}'))


class _Resp:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    """Plays a script of outcomes (exception instances or dict bodies), one per call."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls = []

    def __call__(self, req, timeout=None):
        self.calls.append((req.get_method(), req.full_url))
        out = self.script.pop(0)
        if isinstance(out, BaseException):
            raise out
        return _Resp(out)


class SendRetryTest(unittest.TestCase):
    def setUp(self):
        self.client = connector.GHLClient({"GHL_API_KEY": "test", "GHL_LOCATION_ID": "loc",
                                           "GHL_BASE_URL": "https://ghl.invalid"}, "test")
        self.sleeps = []
        p = mock.patch.object(connector.time, "sleep", side_effect=self.sleeps.append)
        p.start()
        self.addCleanup(p.stop)

    def _run(self, opener, fn):
        with mock.patch.object(connector.urllib.request, "urlopen", opener):
            return fn()

    def test_send_timeout_is_one_attempt(self):
        op = FakeOpener(TimeoutError("read timed out"), {"messageId": "m2"})
        with self.assertRaises(connector.GHLSendUnknown) as cm:
            self._run(op, lambda: self.client.post(SEND, BODY))
        self.assertEqual(len(op.calls), 1)
        self.assertIn("check the GHL conversation", str(cm.exception))

    def test_send_socket_timeout_and_urlerror_are_one_attempt(self):
        for err in (socket.timeout("timed out"), urllib.error.URLError("reset")):
            op = FakeOpener(err, {"messageId": "m2"})
            with self.assertRaises(connector.GHLSendUnknown):
                self._run(op, lambda: self.client.post(SEND, BODY))
            self.assertEqual(len(op.calls), 1)

    def test_send_5xx_is_one_attempt(self):
        op = FakeOpener(_http(502), {"messageId": "m2"})
        with self.assertRaises(connector.GHLSendUnknown) as cm:
            self._run(op, lambda: self.client.post(SEND, BODY))
        self.assertEqual(len(op.calls), 1)
        self.assertIsInstance(cm.exception.__cause__, urllib.error.HTTPError)

    def test_send_429_is_retried_honoring_retry_after(self):
        op = FakeOpener(_http(429, {"Retry-After": "2"}), {"messageId": "m1"})
        res = self._run(op, lambda: self.client.post(SEND, BODY))
        self.assertEqual(res, {"messageId": "m1"})
        self.assertEqual(len(op.calls), 2)
        self.assertEqual(self.sleeps, [2.0])

    def test_send_4xx_raises_plain_http_error(self):
        op = FakeOpener(_http(400))
        with self.assertRaises(urllib.error.HTTPError):
            self._run(op, lambda: self.client.post(SEND, BODY))
        self.assertEqual(len(op.calls), 1)

    def test_get_timeout_is_retried(self):
        op = FakeOpener(TimeoutError("read timed out"), {"contacts": []})
        res = self._run(op, lambda: self.client.get("/contacts/", {"locationId": "loc"}))
        self.assertEqual(res, {"contacts": []})
        self.assertEqual(len(op.calls), 2)

    def test_non_send_post_5xx_still_retried(self):
        # e.g. /contacts/search is a read over POST — unchanged behavior.
        op = FakeOpener(_http(503), {"contacts": []})
        self._run(op, lambda: self.client.post("/contacts/search", {"locationId": "loc"}))
        self.assertEqual(len(op.calls), 2)

    def test_module_send_helper_routes_through_client(self):
        # ghl_post (Marcus, screening, Do Today, drawer sends) shares WHOLESALE._req.
        op = FakeOpener(TimeoutError("read timed out"), {"messageId": "m2"})
        with mock.patch.object(connector, "WHOLESALE", self.client):
            with self.assertRaises(connector.GHLSendUnknown):
                self._run(op, lambda: connector.ghl_post(SEND, BODY))
        self.assertEqual(len(op.calls), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
