"""'What the agents did' digest (action_digest over action_log). Zero Claude.
Run: python3 test_action_digest.py   (temp action log; exit 1 on failure)."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

LOG = Path(tempfile.mkdtemp()) / "actions.jsonl"
os.environ["FORGE_ACTION_LOG"] = str(LOG)
import action_log  # noqa: E402
import action_digest  # noqa: E402

action_log.STATE = LOG


def main():
    old = {"ts": int((time.time() - 3 * 86400) * 1000), "agent": "solomon", "trigger": "chat_auto",
           "action": "chat:/api/daycare/ghl/tag", "ok": True, "ref": "OLD"}
    LOG.write_text(json.dumps(old) + "\n")
    rec = action_log.record_result
    rec({"ok": True}, "solomon", "chat:/api/daycare/ghl/tag", business="daycare", trigger="chat_auto",
        ref="Tag Mia's mom enrolled")
    rec({"ok": True}, "solomon", "partner:/api/daycare/replies/approve", business="daycare", trigger="dash_tap",
        ref="Text Mia's mom the tour times", approval_required=True)
    rec({"ok": False, "error": "GHL 422 — sk-ant-api03-SECRETSECRETSECRET"}, "solomon", "chat:/api/daycare/ghl/tag",
        business="daycare", trigger="chat_auto", ref="Tag Ava's dad")
    rec({"ok": True}, "marcus", "partner:/api/marcus/approve", business="wholesale", trigger="telegram_tap",
        ref="Send the 2210 Oak reply")
    rec({"ok": True}, "dyson", "chat:/api/hub/task", business="agency", trigger="chat_auto", ref="Task for Solomon")
    action_log.record("scout", "sms_send", trigger="autotag", ok=True)
    assert action_log.flush()

    d = action_digest.digest(24)
    assert d["ok"] and d["hours"] == 24 and d["count"] == 6 and not d["truncated"], d
    s = d["agents"]["solomon"]
    assert (s["total"], s["ok"], s["failed"]) == (3, 2, 1), s
    assert s["byTrigger"] == {"chat_auto": 2, "dash_tap": 1}, s["byTrigger"]
    newest, mid, first = s["latest"]
    assert newest["summary"] == "Tag Ava's dad" and newest["ok"] is False and "undo" not in newest, newest
    assert "422" in newest["error"] and "SECRET" not in json.dumps(d), "the log already scrubbed secrets"
    assert mid["path"] == "/api/daycare/replies/approve" and "undo" not in mid, "a sent text has no inverse"
    assert first["undo"] == {"path": "/api/daycare/ghl/tag", "how": "same contact_id with add ↔ remove swapped"}
    assert first["trigger"] == "chat_auto" and first["business"] == "daycare" and first["path"] == "/api/daycare/ghl/tag"
    assert d["agents"]["marcus"]["byTrigger"] == {"telegram_tap": 1}
    assert d["agents"]["dyson"]["latest"][0]["undo"]["path"] == "/api/hub/task/update"
    assert d["agents"]["scout"]["latest"][0]["path"] is None, "non-route actions carry no path"
    assert "OLD" not in json.dumps(d), "outside the window"
    assert action_digest.digest(96)["count"] == 7
    for raw, want in ((0, 1), (999, 168), ("x", 24), (None, 24), ("48", 48)):
        assert action_digest.digest(raw)["hours"] == want, raw
    assert action_digest._path("chat:/api/x/y") == "/api/x/y" and action_digest._path("sms_send") is None
    for p in action_digest.INVERSE:
        assert p.startswith("/api/") and action_digest.INVERSE[p]["path"].startswith("/api/")
    print("action_digest: all OK")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print("FAIL", repr(e))
        sys.exit(1)
