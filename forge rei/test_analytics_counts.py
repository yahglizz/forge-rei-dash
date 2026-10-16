"""Analytics counts each conversation once (was 4x) and an empty window stays empty.
Fixture GHL only; no network."""
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analytics_engine as ae  # noqa: E402

NOW = int(time.time() * 1000)
DAY = 86400 * 1000


def _convos(n, start_age_days=1, inbound_every=2):
    return [{"id": f"c{i}", "lastMessageDate": NOW - (start_age_days * DAY) - i * 60000,
             "lastMessageDirection": "inbound" if i % inbound_every == 0 else "outbound",
             "unreadCount": 1, "lastMessageBody": "maybe", "lastMessageType": "TYPE_SMS",
             "tags": []} for i in range(n)]


class FakeGHL:
    """ignore_cursor=True mimics GHL ignoring the paging params (the 4x bug)."""

    def __init__(self, convos, ignore_cursor=False):
        self.convos, self.ignore, self.calls = convos, ignore_cursor, []

    def __call__(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        if path != "/conversations/search":
            return {"messages": []}
        rows = self.convos
        after = (params or {}).get("startAfterDate")
        if after and not self.ignore:
            rows = [c for c in rows if c["lastMessageDate"] < after]
        return {"conversations": rows[: params.get("limit", 100)]}


def _build(ghl, days=30):
    return ae.build(ghl, lambda: ([], []), "loc", days=days, pages=4, sample=0)


class AnalyticsCounts(unittest.TestCase):
    def setUp(self):
        self._log = ae.PROPOSALS_LOG
        ae.PROPOSALS_LOG = HERE / "does-not-exist" / "proposals.jsonl"

    def tearDown(self):
        ae.PROPOSALS_LOG = self._log

    def test_cursor_ignored_counts_once_not_4x(self):
        d = _build(FakeGHL(_convos(100), ignore_cursor=True))
        self.assertEqual(d["scope"], 100)
        self.assertEqual(d["volume"]["inboundLast"], 50)
        self.assertEqual(d["volume"]["unanswered"], 50)
        self.assertEqual(sum(d["timing"]["byHour"].values()), 50)

    def test_real_paging_collects_every_page_once(self):
        ghl = FakeGHL(_convos(250))
        d = _build(ghl)
        self.assertEqual(d["scope"], 250)
        searches = [p for path, p in ghl.calls if path == "/conversations/search"]
        self.assertEqual(len(searches), 3)
        self.assertEqual(searches[0].get("sort"), "desc")
        self.assertIn("startAfterDate", searches[1])

    def test_empty_window_is_empty_not_all_time(self):
        d = _build(FakeGHL(_convos(40, start_age_days=60)), days=7)
        self.assertEqual(d["scope"], 0)
        self.assertEqual(d["volume"]["unanswered"], 0)
        self.assertEqual(d["responseRate"], 0)


if __name__ == "__main__":
    unittest.main()
