#!/usr/bin/env python3
"""action_log (wave-2 item 6): append/recent, rotation, redaction, concurrent writers,
unwritable path never raises or blocks.  python3 test_action_log.py  (exit 1 on failure)

Writes only to a temp dir — never the real marcus_state.
"""
import json
import os
import stat
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
TMP = Path(tempfile.mkdtemp(prefix="action_log_test_"))
os.environ["FORGE_ACTION_LOG"] = str(TMP / "unused.jsonl")

import action_log  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def fresh(name):
    action_log.flush()            # queued lines from the previous section land in ITS file
    action_log.STATE = TMP / name / "agent_actions.jsonl"
    action_log.MAX_BYTES = 5 * 1024 * 1024
    return action_log.STATE


# 1. append + recent (newest first, agent filter, fields)
p = fresh("basic")
action_log.record("scout", "auto_tag_hot", business="wholesale", trigger="auto_hot", ref="c1")
action_log.record_result({"error": "GHL tag failed: 500"}, "scout", "auto_pipeline_hot", ref="c2")
action_log.record_result({"ok": True}, "marcus", "approve_send", ref="p1", approval_required=True)
action_log.flush()
rows = action_log.recent(10)
check(len(rows) == 3 and rows[0]["action"] == "approve_send", "recent newest-first, 3 rows")
check(set(rows[0]) == {"ts", "agent", "business", "trigger", "ref", "action", "result", "ok",
                       "error", "retry", "approvalRequired"}, "all spec fields present")
check(rows[1]["ok"] is False and "500" in rows[1]["error"], "error dict -> ok False + error")
check([r["ref"] for r in action_log.recent(10, agent="scout")] == ["c2", "c1"], "agent filter")
check(action_log.last_by_agent() == {
    "marcus": {"ts": rows[0]["ts"], "action": "approve_send", "ok": True},
    "scout": {"ts": rows[1]["ts"], "action": "auto_pipeline_hot", "ok": False}},
    "last_by_agent keeps newest per agent")

# 2. rotation: small cap → .1 appears, current file stays small, history still readable
p = fresh("rotate")
action_log.MAX_BYTES = 600
for i in range(30):
    action_log.record("scout", "auto_tag_hot", ref=f"r{i}")
action_log.flush()
old = p.with_name(p.name + ".1")
check(old.exists(), "rotated file .1 exists")
check(p.stat().st_size <= 600 + 400, "current file bounded by cap")
check(not p.with_name(p.name + ".2").exists(), "keeps exactly one old file")
check(action_log.recent(5)[0]["ref"] == "r29", "recent reads newest after rotation")

# 3. redaction: fake keys never land on disk; phones keep last 4 only
p = fresh("redact")
fakes = [
    "sk-ant-" + "api03-" + "FAKEfakeFAKE1234567890",
    "Bearer " + "abcdefghijklmnopqrstuvwxyz0123",
    "EAA" + "BsbCS1iHgBAFAKEFAKEFAKE1234",
    "sk_" + "live_" + "FAKE1234567890abcdefgh",
    "sk-" + "proj-" + "FAKEFAKE1234567890",
    "123456789" + ":AA" + "FakeFakeFakeFakeFakeFake12",
]
action_log.record("eco", "approve_ad_paused", error="meta said " + " / ".join(fakes),
                  result="token " + fakes[0], ref=fakes[2])
action_log.record("operator", "sms_sent", result="to +1 (555) 867-5309 on 2026-09-22")
action_log.flush()
disk = p.read_text()
check(not any(f in disk for f in fakes), "no fake key string reaches disk")
check("[REDACTED]" in disk, "redaction marker written")
check("867-5309" not in disk and "***5309" in disk, "phone masked to last 4")
check("2026-09-22" in disk, "dates are not mistaken for phones")
# Codex: adjacent numbers / number+date / full GHL pit- token
check(action_log._scrub("phones 2155550123 2155550199") == "phones ***0123 ***0199", "adjacent phones each masked")
check(action_log._scrub("215-555-0123 2026-09-22") == "***0123 2026-09-22", "phone next to a date masked")
check(action_log._scrub("pit-12345678-abcd-4321-abcd-123456789abc") == "[REDACTED]", "whole GHL token redacted")

# 4. 8 concurrent writers → every line whole + valid JSON
p = fresh("concurrent")
N_THREADS, PER = 8, 50


def writer(t):
    for i in range(PER):
        action_log.record(f"agent{t}", "work", ref=f"{t}-{i}", result="x" * 200)


ths = [threading.Thread(target=writer, args=(t,)) for t in range(N_THREADS)]
[t.start() for t in ths]
[t.join() for t in ths]
action_log.flush()
lines = p.read_text().splitlines()
parsed = [json.loads(ln) for ln in lines]
check(len(parsed) == N_THREADS * PER, f"{N_THREADS} threads x {PER} = {len(parsed)} valid lines")
check(len({r["ref"] for r in parsed}) == N_THREADS * PER, "no line lost or duplicated")

# 5. unwritable path: record() never raises, returns False fast
ro = TMP / "readonly"
ro.mkdir()
os.chmod(ro, stat.S_IRUSR | stat.S_IXUSR)
action_log.STATE = ro / "sub" / "agent_actions.jsonl"
try:
    t0 = time.time()
    r1 = action_log.record("scout", "auto_tag_hot", ref="x")
    r2 = action_log.record_result(object(), "scout", "weird")    # non-dict result
    action_log.STATE = TMP                                          # a directory, not a file
    r3 = action_log.record("scout", "auto_tag_hot")
    action_log.flush()
    check(time.time() - t0 < 1.0, "failures return fast, no exception")
    check(not (ro / "sub").exists(), "nothing written on an unwritable path")
    check(action_log.recent(5) == [], "recent on a bad path -> [] (never raises)")
except Exception as e:  # noqa: BLE001
    check(False, f"record raised: {e!r}")
finally:
    os.chmod(ro, stat.S_IRWXU)

# 6. a slow disk never stalls the caller (Codex P1: I/O is off the send path)
fresh("slow")
_real_write = action_log._write
action_log._write = lambda line: time.sleep(0.5)
try:
    t0 = time.time()
    rs = [action_log.record("marcus", "approve_send") for _ in range(5)]
    check(all(rs) and time.time() - t0 < 0.1, "slow disk -> caller returns immediately")
    _q, action_log._Q = action_log._Q, __import__("queue").Queue(maxsize=1)
    try:
        action_log._Q.put_nowait("x")                    # queue full, no worker draining it
        t0 = time.time()
        check(action_log.record("marcus", "x") is False and time.time() - t0 < 0.1,
              "full queue -> dropped, not blocked")
    finally:
        action_log._Q = _q
finally:
    action_log.flush()
    action_log._write = _real_write

print(f"\n{'FAILED' if FAILS else 'ALL PASS'} ({len(FAILS)} failures)")
sys.exit(1 if FAILS else 0)
