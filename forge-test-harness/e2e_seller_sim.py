"""e2e_seller_sim.py — full start-to-finish ACE simulation against FAKE sellers.

WHAT THIS IS
------------
The wholesale auto-reply pipeline has a lot of moving parts (Scout thread reads →
Marcus screening → ConversationEngine state machine → ace.decide/apply → the voice
drafter → sms_guard → GHL). Unit tests cover the pieces; this covers the SEAMS.

It runs the REAL engines — real screening (Claude), real drafting off the real vault
playbook, the real `sms_guard` stack with `autonomous=True`, real `legit_check` — and
fakes exactly ONE thing: the GoHighLevel transport. So no SMS can leave the box, no
live GHL contact is created, and no live state file is touched.

Isolation: the script copies `forge rei/*.py` into a scratch dir and runs there, so
every `marcus_state/*.json` write lands in the scratch dir instead of production.

HOW TO RUN (on the box — the Windows dev machine has no real python3)
---------------------------------------------------------------------
    scp -i ~/.ssh/forge_droplet forge-test-harness/e2e_seller_sim.py \
        root@24.199.81.124:/tmp/e2e_seller_sim.py

    ssh -i ~/.ssh/forge_droplet root@24.199.81.124 \
      'set -a; . /etc/default/forge-reios >/dev/null 2>&1; set +a; \
       export FORGE_VAULT=/opt/forge/vault FORGE_MARCUS=0 FORGE_SMS_DEDUPE_MINUTES=0; \
       python3 /tmp/e2e_seller_sim.py'

Env notes:
  * `FORGE_VAULT=/opt/forge/vault` is REQUIRED. It lives in the systemd unit
    (`/etc/systemd/system/forge-reios.service`), NOT in `/etc/default/forge-reios`,
    so sourcing the env file alone leaves it unset — and the drafter then silently
    runs with a 0-byte playbook. See bug B5 in CODEX_WHOLESALE_AUTOPILOT_TASK.md.
  * `FORGE_SMS_DEDUPE_MINUTES=0` compresses a multi-day conversation into seconds.
    It DISABLES the send-ledger dedupe gate — that gate is therefore NOT covered by
    this harness and needs its own test.
  * `FORGE_MARCUS=0` keeps the background loops off.

Reads `/tmp/e2e_result.json` for the full structured output.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

# ── bootstrap: run from an isolated copy of the app so state writes stay scratch ──
_APP_CANDIDATES = [
    "/opt/forge/forge-rei",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "forge rei"),
]
_MARKER = "_FORGE_E2E_ISOLATED"


# Marcus can still load the legacy toolkit's draft_reply override. The classifier itself
# must always resolve to the tracked seller_classify.py copied into the scratch app tree.
_TOOLKIT_CANDIDATES = [
    "/opt/forge/marcus-wholesale-agent",
    os.path.expanduser("~/Desktop/marcus-wholesale-agent"),
]


def _is_tracked_classifier_source(source, repo_dir):
    """Return true only for the tracked classifier copied into this isolated app."""
    if not source or not repo_dir:
        return False
    actual = os.path.realpath(os.fspath(source))
    expected = os.path.realpath(os.path.join(os.fspath(repo_dir), "seller_classify.py"))
    return actual == expected


def _bootstrap():
    app = next((p for p in _APP_CANDIDATES if os.path.isdir(p)), None)
    if not app:
        sys.exit("could not find the app dir (forge rei / /opt/forge/forge-rei)")
    root = tempfile.mkdtemp(prefix="forge_e2e_")
    run = os.path.join(root, "forge-rei")          # keep root as the parent dir
    os.makedirs(os.path.join(run, "marcus_state"), exist_ok=True)
    for name in os.listdir(app):
        if name.endswith(".py"):
            shutil.copy2(os.path.join(app, name), os.path.join(run, name))
    shutil.copy2(os.path.abspath(__file__), os.path.join(run, "sim.py"))

    toolkit = next((p for p in _TOOLKIT_CANDIDATES if os.path.isdir(p)), None)
    if toolkit:
        try:
            os.symlink(toolkit, os.path.join(root, "marcus-wholesale-agent"))
            print(f"[e2e] optional legacy draft toolkit linked from {toolkit}")
        except OSError as e:
            print(f"[e2e] could not link the optional legacy draft toolkit ({e}); "
                  "the tracked repo drafter fallback will be used")
    else:
        print("[e2e] optional legacy draft toolkit not found; "
              "the tracked repo drafter fallback will be used")

    env = dict(os.environ, **{_MARKER: run})
    print(f"[e2e] isolated run dir: {run}\n")
    raise SystemExit(subprocess.call([sys.executable, os.path.join(run, "sim.py")], env=env))


if not os.environ.get(_MARKER):
    _bootstrap()

HERE = os.environ[_MARKER]
sys.path.insert(0, HERE)
os.chdir(HERE)

import ace                     # noqa: E402
import conversation_engine     # noqa: E402
import marcus_engine           # noqa: E402
import marcus_screening        # noqa: E402
import scout_triage            # noqa: E402
import sms_guard               # noqa: E402

LOC = "loc_e2e"
STATE = {"conv": None, "cid": None, "name": None, "phone": None, "thread": []}
SENT = []
POSTS = []


def _ms():
    return int(time.time() * 1000)


def add(direction, body):
    STATE["thread"].append({"id": f"m{len(STATE['thread'])}", "direction": direction,
                            "body": body, "messageType": "TYPE_SMS", "dateAdded": _ms()})


# ── fake GHL transport (the ONLY faked layer) ────────────────────────────────
def _convo_row():
    last = STATE["thread"][-1]
    return {"id": STATE["conv"], "contactId": STATE["cid"], "fullName": STATE["name"],
            "contactName": STATE["name"], "phone": STATE["phone"], "email": "",
            "type": "TYPE_PHONE", "lastMessageBody": last["body"],
            "lastMessageDate": last["dateAdded"],
            "lastMessageDirection": ("inbound" if last["direction"] == "inbound"
                                     else "outbound"),
            "lastMessageType": "TYPE_SMS", "unreadCount": 1,
            "dateUpdated": last["dateAdded"]}


def ghl_get(path, params=None):
    p = str(path)
    if p.startswith("/conversations/search"):
        return {"conversations": [_convo_row()], "total": 1}
    if p.startswith("/conversations/") and p.endswith("/messages"):
        # GHL returns newest-first, nested under messages.messages
        return {"messages": {"messages": list(reversed(STATE["thread"]))}}
    if p.startswith("/contacts/") and "/" not in p[len("/contacts/"):]:
        return {"contact": {"id": STATE["cid"],
                            "firstName": (STATE["name"] or "x").split()[0],
                            "name": STATE["name"], "phone": STATE["phone"],
                            "tags": [], "dateAdded": _ms()}}
    if p.startswith("/contacts"):
        return {"contacts": [{"id": STATE["cid"], "name": STATE["name"],
                              "phone": STATE["phone"], "tags": []}]}
    if p.startswith("/opportunities") or p.startswith("/pipelines"):
        return {"pipelines": [], "opportunities": []}
    return {}


def ghl_post(path, body=None):
    POSTS.append((str(path), body))
    if str(path) == "/conversations/messages":
        msg = (body or {}).get("message") or ""
        SENT.append(msg)
        add("outbound", msg)
    return {"ok": True, "id": f"post{len(POSTS)}"}


def ghl_put(path, body=None):
    POSTS.append(("PUT " + str(path), body))
    return {"ok": True}


SCOUT = scout_triage.ScoutEngine(ghl_get, ghl_post, LOC, ghl_put=ghl_put)
MARCUS = marcus_engine.MarcusEngine(ghl_get, ghl_post, LOC)
SCREENER = marcus_screening.Screener(ghl_get, LOC, scout=SCOUT, ghl_post=ghl_post)
CONVO = conversation_engine.ConversationEngine()


def _check(contact_id, message, conv_id=None, name="", last_seller_message=None,
           kind="sms", autonomous=False, check_legit=True):
    return sms_guard.guard(contact_id, message, conv_id=conv_id, name=name, scout=SCOUT,
                           last_seller_message=last_seller_message, kind=kind,
                           autonomous=autonomous, check_legit=check_legit)


for _eng in (MARCUS, SCREENER):
    _eng.safety_check = _check
    _eng.safety_record = lambda **kw: sms_guard.record_success(**kw)
    _eng.safety_release = sms_guard.release


def bridge(report):
    """Byte-for-byte mirror of connector._ace_update_from_screening."""
    crec = CONVO.update(STATE["conv"], contact_id=STATE["cid"], name=STATE["name"],
                        phone=STATE["phone"], report=report, last_inbound_ms=_ms())
    last_in = None
    try:
        msgs = SCOUT._thread_transcript(STATE["conv"]) or []
        inb = [(m.get("body") or "").strip() for m in msgs
               if m.get("direction") == "inbound" and (m.get("body") or "").strip()]
        last_in = inb[-1] if inb else None
    except Exception:
        pass
    return crec, ace.apply(STATE["conv"], crec, report, CONVO, MARCUS,
                           last_seller_msg=last_in)


# ── scripted sellers ─────────────────────────────────────────────────────────
SCENARIOS = [
    {
        "id": "A-price-first",
        "note": "Seller signals interest immediately. Tests the call-pivot lane and the "
                "one-pivot-then-silence contract.",
        "conv": "conv_e2e_A", "cid": "contact_e2e_A",
        "name": "Dana Whitfield (TEST)", "phone": "+15555550199",
        "opener": ("hey Dana, i buy houses in the area, any chance youd consider an offer "
                   "on the fairmount property"),
        "turns": [
            ("yes im still thinking about selling it, what did you have in mind",
             "first genuine inbound — interested, ZERO facts gathered yet"),
            ("its in ok shape, roofs about 15 years old and the kitchen needs updating but "
             "nobody ever trashed it", "answers CONDITION"),
            ("not in a huge rush but id like to be out before the fall, so like 60 days",
             "answers TIMELINE"),
            ("how much would you give me for it", "explicit PRICE ask"),
            ("ok i can talk tomorrow after 5", "post-pivot — ACE must stay silent"),
        ],
    },
    {
        "id": "B-slow-burn",
        "note": "Seller is engaged but noncommittal. Tests the qualifying-question lane "
                "and whether a soft price ask trips the pivot.",
        "conv": "conv_e2e_B", "cid": "contact_e2e_B",
        "name": "Ray Molina (TEST)", "phone": "+15555550188",
        "opener": ("hey Ray, i buy houses in the area, would you consider selling the "
                   "chelten ave property"),
        "turns": [
            ("me and my brother inherited it last year, we been going back and forth on it",
             "engaged but noncommittal — question lane should run"),
            ("its been empty since my mom passed, needs work, the basement takes water when "
             "it rains hard", "answers CONDITION + OCCUPANCY"),
            ("we want it done this summer if we can, taxes are killing us",
             "answers TIMELINE + MOTIVATION"),
            ("what kind of numbers are you thinking",
             "SOFT price ask — should trip the pivot, currently does not (bug B2)"),
        ],
    },
]

# Phrases the classifier must get right. Regression guard for bugs B2/B3/B4.
PRICE_ASKS = [
    "how much would you give me for it", "what kind of numbers are you thinking",
    "whats your offer", "what were you thinking", "what can you do for it",
    "give me a ballpark", "whats the most you can do", "what are you offering",
    "how much", "whats it worth to you", "what number did you have in mind",
    "send me your best", "whats your range", "what would you pay",
]
NOT_DENIALS = [
    "im not in a huge rush", "im not in a position to sell yet", "im not the only owner",
    "im not at the house right now", "im not really sure what its worth",
    "im not against selling", "im not in town till friday",
    "im not a cash buyer im the owner",
]


def probe_classifiers():
    """Pure-function probes — no Claude, no network. Fast and deterministic."""
    price = [{"text": s, "classify": marcus_engine.classify(s)} for s in PRICE_ASKS]
    price_missed = [r for r in price if r["classify"] not in ("PRICE", "READY")]
    denial = [{"text": s, "isDenial": marcus_engine._is_denial(s)} for s in NOT_DENIALS]
    denial_fp = [r for r in denial if r["isDenial"]]
    src = "?"
    try:
        import inspect
        src = inspect.getsourcefile(marcus_engine.classify) or "?"
    except Exception:
        pass
    prod = _is_tracked_classifier_source(src, HERE)
    source_meta = marcus_engine.classifier_source()
    out = {"classifySource": src, "classifyModule": marcus_engine.classify.__module__,
           "usingProductionClassifier": prod,
           "legacyDraftOverride": bool(source_meta.get("externalDraftOverride")),
           "draftSource": source_meta.get("draftSource"),
           "priceAsks": price, "priceMissed": len(price_missed), "priceTotal": len(price),
           "denialProbe": denial, "denialFalsePositives": len(denial_fp)}
    if not prod:
        print("!! WARNING: classifier is not the tracked seller_classify.py copied into "
              "the isolated app tree. Classification results are not representative. (bug B1)")
    print("PROBE " + json.dumps(
        {k: out[k] for k in ("classifySource", "classifyModule", "usingProductionClassifier",
                             "legacyDraftOverride", "draftSource", "priceMissed",
                             "priceTotal", "denialFalsePositives")},
        default=str))
    for r in price_missed:
        print(f"   PRICE MISS  {r['classify']:9} | {r['text']}")
    for r in denial_fp:
        print(f"   DENIAL FP   {r['text']}")
    return out


def run_scenario(sc):
    STATE.update({"conv": sc["conv"], "cid": sc["cid"], "name": sc["name"],
                  "phone": sc["phone"], "thread": []})
    add("outbound", sc["opener"])
    out = {"id": sc["id"], "note": sc["note"], "turns": []}
    for i, (msg, why) in enumerate(sc["turns"], 1):
        add("inbound", msg)
        before = len(SENT)
        rep = SCREENER.screen(contact_id=sc["cid"], conv_id=sc["conv"]) or {}
        report = (rep.get("screening") or {}).get("report") or {}
        crec, d = bridge(report)
        turn = {
            "turn": i, "why": why, "seller": msg,
            "classify": marcus_engine.classify(msg),
            "isDenial": marcus_engine._is_denial(msg),
            "isSoftNo": marcus_engine._is_soft_no(msg),
            "screenSkipped": rep.get("skipped") or rep.get("error"),
            "screening": {
                "interest": report.get("interest"), "score": report.get("score"),
                "askingPrice": report.get("askingPrice"),
                "timeline": (report.get("timeline") or "")[:60],
                "condition": (report.get("conditionNotes") or "")[:70],
                "motivation": report.get("motivationLevel"),
                "occupancy": report.get("propertyStatus"),
            },
            "state": (crec or {}).get("state"), "facts": (crec or {}).get("facts"),
            "replies": (crec or {}).get("replies"),
            "pivoted": bool((crec or {}).get("callPivotAt")),
            "aceAction": d.get("action"), "aceReason": d.get("reason"),
            "aceError": d.get("error"), "aceGate": d.get("gate"),
            "outbound": SENT[before:],
        }
        out["turns"].append(turn)
        print("TURN " + json.dumps(turn, default=str))
    out["finalRec"] = CONVO.get(sc["conv"])
    return out


def main():
    ace.set_mode("full")
    cfg = {
        "runDir": HERE, "aceMode": ace.mode(), "cap": ace.cap_for(),
        "questionCap": ace.reply_cap_for(), "pivotReserve": ace.PIVOT_RESERVE,
        "maxReplies": ace.MAX_REPLIES,
        "smsDedupeMinutes": sms_guard.DEDUP_MINUTES,
        "sendWindowET": [sms_guard.SEND_START, sms_guard.SEND_END],
        "hourET": sms_guard._hour_et(), "withinHours": sms_guard._within_hours(),
        "vault": os.environ.get("FORGE_VAULT"),
        "replyRubricBytes": len(MARCUS._load_reply_rubric() or ""),
        "playbookBytes": len(MARCUS._load_playbook() or ""),
    }
    print("CONFIG " + json.dumps(cfg, default=str))
    if not cfg["replyRubricBytes"] or not cfg["playbookBytes"]:
        print("!! WARNING: the drafter loaded a 0-byte playbook/rubric. Set FORGE_VAULT. "
              "Drafts below are NOT representative of production. (bug B5)")
    if not cfg["withinHours"]:
        print("!! WARNING: outside the 9am-8pm ET send window — every send will be gated "
              "at sms_guard. Re-run during the window for a meaningful result.")

    results = {"config": cfg, "probe": probe_classifiers(), "scenarios": []}
    for sc in SCENARIOS:
        print("\n===== SCENARIO " + sc["id"] + " =====")
        results["scenarios"].append(run_scenario(sc))
    results["digest"] = ace.digest()
    results["callReady"] = ace.call_ready_list()
    results["allSent"] = SENT
    with open("/tmp/e2e_result.json", "w") as f:
        json.dump(results, f, indent=2, default=str)

    print("\nDIGEST " + json.dumps(results["digest"]["summary"], default=str))
    print(f"SENT_COUNT {len(SENT)}")
    for s in SENT:
        print("  >>", s)
    print("\nfull structured output -> /tmp/e2e_result.json")


if __name__ == "__main__":
    main()
