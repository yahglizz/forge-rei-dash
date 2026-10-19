"""Solomon's Command Board store (daycare_board). Run: python3 test_daycare_board.py — exit 1 on failure.
No network; the board file lives in a temp dir (FORGE_DAYCARE_BOARD)."""
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="board-test-"))
os.environ["FORGE_DAYCARE_BOARD"] = str(TMP / "board.json")

import daycare_board as b  # noqa: E402

T0 = 1_760_000_000.0
EV = {"source": "Supabase invoices", "window": "latest 500 · 921 N 18th St", "fetchedAt": 1}


def item(key, sev="normal", domain="billing", **kw):
    return {"domain": domain, "key": key, "title": f"item {key}", "why": "because", "evidence": EV,
            "center": "921 N 18th St", "severity": sev, **kw}


def reset():
    b.STATE.unlink(missing_ok=True)


def ids(v):
    return [i["key"] for i in v["items"]]


def test_state_path_is_the_override():
    assert b.STATE == TMP / "board.json", b.STATE


def test_dedupe_and_aging():
    reset()
    r1 = b.upsert(item("inv:1"), now=T0)
    r2 = b.upsert(dict(item("inv:1"), title="item inv:1 (now 12d overdue)"), now=T0 + 3600)
    assert r1["change"] == "new" and r2["change"] == "seen" and r1["id"] == r2["id"] == b.item_id("billing", "inv:1")
    v = b.view(now=T0 + 7200)
    assert v["count"] == 1, v
    it = v["items"][0]
    assert it["firstSeen"] == int(T0 * 1000) and it["lastSeen"] == int((T0 + 3600) * 1000) and it["seenCount"] == 2, it
    assert it["title"].endswith("12d overdue)") and it["ageSec"] == 7200, it


def test_rejects_without_evidence_or_center():
    reset()
    for bad, why in ((dict(item("a"), evidence={"source": "x"}), "window"),
                     (dict(item("a"), evidence={"window": "7d"}), "source"),
                     (dict(item("a"), evidence=None), "source"),
                     (dict(item("a"), center=""), "center"),
                     (dict(item("a"), domain="payroll"), "domain"),
                     (dict(item("a"), severity="critical"), "severity"),
                     (dict(item("a"), owner="marcus"), "owner"),
                     (dict(item("a"), title=""), "title")):
        r = b.upsert(bad, now=T0)
        assert r["ok"] is False and why in r["error"], (bad, r)
    assert b.upsert(dict(item("a"), center="unknown"), now=T0)["ok"], "'unknown' center is allowed"
    assert b.view(now=T0)["count"] == 1
    res = b.apply_round([{"domain": "billing", "items": [dict(item("b"), evidence={})], "status": {"ok": True}}],
                        now=T0 + 1)
    assert res["domains"][0]["rejected"] == 1 and res["domains"][0]["items"] == 0, res
    assert b.view(now=T0 + 1)["count"] == 0, "the rejected item never shows, and 'a' resolved (round said ok)"


def test_failed_source_never_closes_items():
    reset()
    b.apply_round([{"domain": "inbox", "items": [item("mail:t1", domain="inbox")], "status": {"ok": True}}], now=T0)
    res = b.apply_round([{"domain": "inbox", "items": [], "status": {"ok": False, "error": "Gmail read failed"}}],
                        now=T0 + 60)
    assert res["closed"] == [] and b.view(now=T0 + 60)["count"] == 1, "a failed read is Unknown, not 0 problems"
    row = res["domains"][0]
    assert row == {"domain": "inbox", "ok": False, "items": 0, "at": int((T0 + 60) * 1000),
                   "error": "Gmail read failed"}, row
    assert "inbox" in res["line"] and "Unknown" in res["line"], res["line"]
    assert b.view(now=T0 + 60)["sources"][0]["ok"] is False
    res = b.apply_round([{"domain": "inbox", "items": [], "status": {"ok": True}}], now=T0 + 120)
    assert len(res["closed"]) == 1 and b.view(now=T0 + 120)["count"] == 0, "an OK read with nothing = closed"
    it = b.view("all", now=T0 + 120)["items"][0]
    assert it["state"] == "done" and it["closedBy"] == "watch", it


def test_partial_sources_resolve_only_their_prefix():
    reset()
    b.apply_round([{"domain": "enrollment", "items": [item("lead:1", domain="enrollment"),
                                                      item("start:9", domain="enrollment")],
                    "status": {"ok": True}}], now=T0)
    res = b.apply_round([{"domain": "enrollment", "items": [],
                          "status": {"ok": False, "sources": {"lead:": True, "start:": False}}}], now=T0 + 60)
    assert len(res["closed"]) == 1 and ids(b.view(now=T0 + 60)) == ["start:9"], b.view(now=T0 + 60)


def test_resolve_missing_and_reopen():
    reset()
    b.upsert(item("inv:1"), now=T0)
    b.upsert(item("inv:2"), now=T0)
    out = b.resolve_missing("billing", ["inv:2"], now=T0 + 60)
    assert out["closed"] == [b.item_id("billing", "inv:1")] and ids(b.view(now=T0 + 60)) == ["inv:2"]
    assert b.resolve_missing("nope", [])["ok"] is False
    r = b.upsert(item("inv:1"), now=T0 + 3600)
    assert r["change"] == "reopened", r
    it = next(i for i in b.view(now=T0 + 3600)["items"] if i["key"] == "inv:1")
    assert it["state"] == "open" and it["firstSeen"] == int((T0 + 3600) * 1000) and it["seenCount"] == 1, \
        "a condition that cleared and came back is a fresh occurrence"


def test_done_reopens_while_the_source_still_shows_it():
    reset()
    iid = b.upsert(item("inv:7"), now=T0)["id"]
    assert b.done(iid, now=T0 + 10)["ok"] and b.view(now=T0 + 10)["count"] == 0
    assert b.done("nope")["ok"] is False
    res = b.apply_round([{"domain": "billing", "items": [item("inv:7")], "status": {"ok": True}}], now=T0 + 60)
    assert res["new"] == [iid], "evidence beats the mark"
    it = b.view(now=T0 + 60)["items"][0]
    assert it["firstSeen"] == int(T0 * 1000) and it["seenCount"] == 2, "same problem, still aging"


def test_snooze():
    reset()
    iid = b.upsert(item("inv:3"), now=T0)["id"]
    r = b.snooze(iid, 24, now=T0)
    assert r["ok"] and r["snoozeUntil"] == int((T0 + 86400) * 1000), r
    assert b.view(now=T0 + 3600)["count"] == 0 and b.view("snoozed", now=T0 + 3600)["count"] == 1
    b.apply_round([{"domain": "billing", "items": [item("inv:3")], "status": {"ok": True}}], now=T0 + 7200)
    assert b.view(now=T0 + 7200)["count"] == 0, "a persisting problem stays snoozed until the snooze ends"
    assert b.view(now=T0 + 86401)["count"] == 1, "an expired snooze reads as open"
    assert b.snooze(iid, 99999, now=T0)["snoozeUntil"] == int((T0 + b.MAX_SNOOZE_H * 3600) * 1000), "capped"
    assert b.view(now=T0 + 60)["counts"]["snoozed"] == 1
    un = b.snooze(iid, 0, now=T0 + 60)
    assert un["state"] == "open" and un["snoozeUntil"] is None and b.view(now=T0 + 60)["count"] == 1, "hours 0 = undo"
    b.snooze(iid, 24, now=T0)
    assert b.snooze(iid, "x")["ok"] is False and b.snooze("nope", 2)["ok"] is False
    b.done(iid, now=T0)
    assert b.snooze(iid, 2)["ok"] is False, "a closed item can't be snoozed"


def test_ranking_counts_and_filters():
    reset()
    b.upsert(item("low1", "low"), now=T0)
    b.upsert(item("hi-new", "high"), now=T0 + 50)
    b.upsert(item("hi-old", "high"), now=T0 + 10)
    b.upsert(item("urg", "urgent", domain="roster"), now=T0 + 99)
    b.upsert(item("norm", "normal", domain="inbox"), now=T0 + 5)
    v = b.view(now=T0 + 100)
    assert ids(v) == ["urg", "hi-old", "hi-new", "norm", "low1"], ids(v)
    assert v["counts"] == {"open": 5, "byDomain": {"billing": 3, "roster": 1, "inbox": 1},
                           "bySeverity": {"low": 1, "high": 2, "urgent": 1, "normal": 1}, "snoozed": 0}, v["counts"]
    assert v["thirdPartyText"] is True, "an inbox item (email subject) marks the payload"
    assert ids(b.view(domain="roster", now=T0 + 100)) == ["urg"] and b.view(limit=2, now=T0 + 100)["count"] == 5
    assert b.view(domain="billing", now=T0 + 100)["thirdPartyText"] is True, "fail closed: any item title is third-party text"
    assert b.view(domain="ads", now=T0 + 100)["thirdPartyText"] is False, "an empty list carries none"
    assert len(b.view(limit=2, now=T0 + 100)["items"]) == 2 and b.view(limit="x", now=T0)["items"]
    c = b.counts_block(now=T0 + 100)
    assert c["open"] == 5 and "title" not in str(c) and "item " not in str(c), "counts only — no titles"


def test_apply_round_summary_and_mail_desk():
    reset()
    desk = {"ok": True, "unread": 2, "urgent": [{"subject": "Tour?", "bucket": "lead"}], "top": [{"subject": "Tour?"}]}
    res = b.apply_round([{"domain": "roster", "items": [item("room:1", "urgent", domain="roster")], "status": {"ok": True}},
                         {"domain": "social", "items": [], "status": {"ok": False, "notWired": True, "error": "not wired"}}],
                        now=T0, mail_desk=desk)
    assert res["open"] == 1 and len(res["new"]) == 1 and res["urgent"][0]["title"] == "item room:1", res
    assert res["newItems"][0]["domain"] == "roster" and "social" in res["line"], res
    assert res["domains"][1]["notWired"] is True
    v = b.view(now=T0)
    assert v["lastRound"]["ranAt"] == int(T0 * 1000) and v["mailDesk"] == desk and v["thirdPartyText"] is True
    bb = b.brief_block(now=T0)
    assert bb["mailDesk"]["topUrgentSubjects"] == ["Tour?"] and "top" not in bb["mailDesk"], bb
    assert bb["board"]["failedSources"] == [{"domain": "social", "error": "not wired", "notWired": True}]
    assert bb["board"]["items"][0]["evidence"]["source"] == "Supabase invoices"


def test_text_renderers():
    reset()
    b.upsert(dict(item("x", "urgent"), title="<b>Tour</b> & more"), now=T0)
    t = b.telegram_text(b.view(now=T0 + 7200))
    assert "&lt;b&gt;Tour&lt;/b&gt; &amp; more" in t and "🔴" in t and "2h" in t and "<b>Tour" not in t, t
    assert "Nothing open." in b.telegram_text({"counts": {"open": 0}, "items": []})
    res = {"new": list("abcdefgh"), "closed": ["z"], "open": 9,
           "newItems": [{"id": str(i), "domain": "inbox", "title": f"t{i}", "severity": "high", "center": "unknown"}
                        for i in range(8)],
           "urgent": [{"id": "u", "domain": "roster", "title": "over cap", "severity": "urgent", "center": "AMT"}],
           "domains": [{"domain": "inbox", "ok": False}]}
    d = b.board_digest_text(res, did=[{"ok": True, "summary": "Tagged 3 enrolled"}] * 5)
    lines = d.splitlines()
    assert len(lines) <= 12 and "8 new" in lines[0] and "1 urgent" in lines[0], d
    assert "over cap" in d and "Unknown" in d and "What I did" in d and "Tagged 3 enrolled" in d, d


def test_telegram_board_command():
    import telegram_agent as ta
    reset()
    b.upsert(item("inv:9", "high"), now=T0)
    seen = []
    saved = ta._http
    ta._http = lambda m, p, query=None, body=None, timeout=90: seen.append((m, p, query)) or b.view(limit=8, now=T0)
    try:
        text, cards = ta.quick("/board", "", "-100", "daycare")
        assert "Solomon's board" in text and "item inv:9" in text and cards == [], text
        assert seen == [("GET", "/api/daycare/board", {"limit": 8})], "one GET, zero Claude"
        assert ta.quick("/board", "", None, None)[0].startswith("🏛️"), "HQ works too"
        assert "Daycare chat" in ta.quick("/board", "", "-1", "wholesale")[0]
        ta._http = lambda *a, **k: {"ok": False, "error": "Session expired"}
        assert ta.quick("/board", "", "-100", "daycare")[0].startswith("⚠️ Couldn't read the board")
    finally:
        ta._http = saved
    import telegram_io
    src = Path(telegram_io.__file__).read_text()
    assert '"/pin", "/board")' in src and '("board", ' in src, "routed + in the / menu"


def main():
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except Exception as e:  # noqa: BLE001
                failed += 1
                import traceback
                print("FAIL", name, "->", repr(e))
                traceback.print_exc()
    print("daycare_board:", "FAILED" if failed else "all OK")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
