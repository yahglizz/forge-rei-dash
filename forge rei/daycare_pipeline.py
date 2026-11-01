"""daycare_pipeline.py — Solomon · Pipeline: the daycare GHL enrollment pipelines on the dashboard.

TWO boards, never mixed (separate legal entities):
  `enrollment` (default) — GHL pipeline "Enrollment" = A Touch of Blessings (921 N 18th +
                           2318 Cecil B. Moore). State marcus_state/daycare_pipeline.json.
  `amt`                  — GHL pipeline "A Mother's Touch" = 1923 Cecil B. Moore, a SEPARATE
                           legal entity. State marcus_state/daycare_pipeline_amt.json.
Every function takes `board` (default "enrollment", so the original single-board callers and
payload are unchanged). A move is checked against THAT board's cached cards + stages and,
live, against the opportunity's current pipelineId before any write.

A lane of Solomon (like Leads / Starts): thread `daycare_pipeline`, heartbeat labeled
"Solomon · Pipeline", ZERO Claude calls.

What it does:
  1. refresh() — every 5 min on the box (FORGE_MARCUS gate lives in connector.main), a
     read-only paged GET of the daycare location's "Enrollment" pipeline opportunities
     (stage ids resolved live from GET /opportunities/pipelines, the ids below as fallback)
     -> the board's state file (both boards every tick). Never raises: a failed read keeps the last
     cards and records the error, so view() shows them marked stale.
  2. view() — GET /api/daycare/pipeline. State file only, no network on the request path.
  3. Proposals: the daily n8n workflow R5knymRU7t30uR8x (9 PM ET, built outside this repo)
     reads each open opportunity's thread and moves stages FORWARD-only on quoted evidence
     (and moves A Mother's Touch contacts — tag entity-amt / loc-1923-cecil-b-moore — out of
     Enrollment into their own pipeline). Lost is never auto-moved: it stays a tag
     `pipe-propose:lost` (slugs: new-lead|contacted|tour-scheduled|application-sent|
     enrolled|lost). A card shows "proposed -> <Stage>" when that differs from its stage.
  4. move() / move_all_proposed() — the OWNER's tap (POST /api/daycare/pipeline/move and
     /move-all). PUT the opportunity's stage in GHL, then remove the contact's
     `pipe-propose:*` tags, then update the cached card at once.

CLAUDE.md §2 (propose -> review -> execute), addition for this lane: **in this repo stage
moves are operator taps.** Nothing here moves a stage on its own — the loop
and refresh() are GET-only; the only GHL writes are inside move(), which runs only from the
owner's session-gated POST. It sends nothing to families.

Kill switch: FORGE_DAYCARE_PIPELINE=0 — the loop does not start (connector) and refresh /
move refuse. Logs carry ids + counts only, never a child's name.
Stdlib only.
"""
import json
import os
import threading
import time
from pathlib import Path

import daycare_leads
import forge_atomic
import forge_heartbeat
import forge_ops

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "daycare_pipeline.json"            # board "enrollment" (ATOB)
STATE_AMT = HERE / "marcus_state" / "daycare_pipeline_amt.json"    # board "amt" (A Mother's Touch)
_LOCK = threading.Lock()            # state file read-modify-write
_MOVE_LOCK = threading.Lock()       # one owner move (or move-all batch) at a time
_REFRESH_LOCKS = {"enrollment": threading.Lock(), "amt": threading.Lock()}   # one GHL read per board

INTERVAL = int(os.environ.get("FORGE_DAYCARE_PIPELINE_INTERVAL", "300"))   # 5 min
MANUAL_REFRESH_MIN_SEC = 15
MOVE_ALL_CAP = 50
PAGE_SIZE, MAX_PAGES = 100, 20      # ponytail: 2,000-opportunity cap; raise if the pipeline grows
STALE_SEC = 3 * INTERVAL

PIPELINE_NAME = "Enrollment"
FALLBACK_PIPELINE_ID = "HibQlSD7pc29Qawf4IT2"
# (id, name) in board order — used only when the live GET /opportunities/pipelines fails.
FALLBACK_STAGES = (
    ("2f78afc0-9de6-467a-b871-64ff4abdc3ef", "New Lead"),
    ("91534e2d-c614-436a-88c3-71f754d66e57", "Contacted"),
    ("0d1dfc37-6935-4497-afa2-0327dd629b82", "Tour Scheduled"),
    ("5f32b1e1-d4ca-4935-b66a-ce83c8cd256d", "Application Sent"),
    ("70d53796-0a23-4bf4-ad56-8231a2fb3b3c", "Enrolled"),
    ("365b2803-cc2c-40c3-a8a8-a6c1b4194f15", "Lost"),
)
AMT_PIPELINE_NAME = "A Mother's Touch"
AMT_FALLBACK_PIPELINE_ID = "2CWNllg1yK8DN1J4uEl6"
AMT_FALLBACK_STAGES = (
    ("6472b166-258b-4d8d-bf26-ac17fa6b353c", "New Lead"),
    ("5d86715d-4e1e-4cbf-b0c5-60c63a874106", "Contacted"),
    ("a328e644-3168-4f13-8682-9d93576ab5a4", "Tour Scheduled"),
    ("4aa57852-f89f-4622-b9ca-f8337f745c95", "Application Sent"),
    ("b39b7bcc-fd38-4492-b368-e225ba61edb6", "Enrolled"),
    ("373f5eb1-5066-4db6-8a2e-f9610e85f81f", "Lost"),
)
PROPOSE_PREFIX = "pipe-propose:"

DEFAULT_BOARD = "enrollment"
# board -> (GHL pipeline name, fallback pipeline id, fallback stages, dashboard label,
#           missing_is_empty). missing_is_empty: when the live pipelines list was read and has
# no pipeline by that name, show an honest empty board instead of searching fallback ids.
BOARDS = {
    "enrollment": (PIPELINE_NAME, FALLBACK_PIPELINE_ID, FALLBACK_STAGES, "A Touch of Blessings", False),
    "amt": (AMT_PIPELINE_NAME, AMT_FALLBACK_PIPELINE_ID, AMT_FALLBACK_STAGES, "A Mother's Touch", True),
}
BAD_BOARD = "board must be one of: " + ", ".join(BOARDS)

_manual_at = {}                     # board -> last manual refresh (s)


def board_key(value):
    """'' / None -> the default board; a known key (any case) -> it; anything else -> None."""
    v = str(value or "").strip().lower()
    return DEFAULT_BOARD if not v else (v if v in BOARDS else None)


def _state_path(board):
    return STATE_AMT if board == "amt" else STATE


def enabled():
    return os.environ.get("FORGE_DAYCARE_PIPELINE", "1") != "0"


def _slug(name):
    """'Tour Scheduled' -> 'tour-scheduled' (the n8n proposal-tag slug)."""
    return "-".join(str(name or "").strip().lower().replace("_", " ").split())


def _ms(sec):
    return int(sec * 1000) if sec is not None else None


def _err(e):
    """Exception -> safe one-liner: type + HTTP code only, never a body or token."""
    code = getattr(e, "code", None)
    return f"{type(e).__name__}{f' {code}' if code else ''}"


# ── pure helpers ──────────────────────────────────────────────────────────────
def proposal_tags(tags):
    """Every `pipe-propose:*` tag on a contact, exactly as GHL holds it."""
    return [str(t) for t in (tags or []) if str(t).strip().lower().startswith(PROPOSE_PREFIX)]


def proposed_slug(tags, valid_slugs):
    """The proposal slug carried by the tags, else None. Several proposals: the LAST valid
    one in tag order wins (ponytail: GHL appends tags, so last = newest — not verified;
    move() clears them all either way)."""
    hits = [s for s in (_slug(t.strip()[len(PROPOSE_PREFIX):]) for t in proposal_tags(tags))
            if s in valid_slugs]
    return hits[-1] if hits else None


def _norm_name(name):
    """Pipeline name for matching: case, spacing and curly apostrophes don't matter."""
    return " ".join(str(name or "").replace("\u2019", "'").strip().lower().split())


def resolve_pipeline(data, board=DEFAULT_BOARD):
    """GET /opportunities/pipelines payload -> (pipeline_id, [{id,name,slug}], source).
    Matches the board's pipeline by name; anything unusable falls back to the known ids.
    source "missing" (pipeline_id None): the list was read and that board's pipeline is not
    in it (only boards with missing_is_empty, i.e. A Mother's Touch)."""
    name, fb_id, fb_stages, _label, missing_is_empty = BOARDS[board]
    pipelines = (data.get("pipelines") if isinstance(data, dict) else None)
    for p in pipelines or []:
        if not isinstance(p, dict) or _norm_name(p.get("name")) != _norm_name(name):
            continue
        raw = [s for s in (p.get("stages") or []) if isinstance(s, dict) and s.get("id")]
        if not p.get("id") or not raw:
            break
        raw.sort(key=lambda s: s.get("position") if isinstance(s.get("position"), (int, float)) else 0)
        return (str(p["id"]), [{"id": str(s["id"]), "name": str(s.get("name") or ""),
                                "slug": _slug(s.get("name"))} for s in raw], "live")
    else:
        if missing_is_empty and isinstance(pipelines, list):
            return None, [{"id": i, "name": n, "slug": _slug(n)} for i, n in fb_stages], "missing"
    return fb_id, [{"id": i, "name": n, "slug": _slug(n)} for i, n in fb_stages], "fallback"


def card_from(opp, stages):
    """One raw GHL opportunity -> a board card. GHL contact name = the CHILD; kept as-is."""
    by_id = {s["id"]: s for s in stages}
    by_slug = {s["slug"]: s for s in stages}
    contact = opp.get("contact") if isinstance(opp.get("contact"), dict) else {}
    tags = contact.get("tags") or []
    stage = by_id.get(str(opp.get("pipelineStageId") or ""))
    slug = proposed_slug(tags, by_slug)
    prop = by_slug.get(slug) if slug else None
    if prop and stage and prop["id"] == stage["id"]:
        prop = None                                   # already there: nothing to approve
    return {
        "opportunityId": str(opp.get("id") or ""),
        "contactId": str(opp.get("contactId") or contact.get("id") or ""),
        "name": str(opp.get("name") or contact.get("name") or "").strip(),
        "stageId": str(opp.get("pipelineStageId") or ""),
        "stageName": stage["name"] if stage else "",
        "status": str(opp.get("status") or ""),
        "createdAt": _ms(daycare_leads._sec(opp.get("createdAt"))),
        "updatedAt": _ms(daycare_leads._sec(opp.get("updatedAt"))),
        "source": str(opp.get("source") or ""),
        "proposedStageId": prop["id"] if prop else None,
        "proposedStageName": prop["name"] if prop else None,
        "proposeTags": proposal_tags(tags),
    }


def _summary(cards, stages):
    counts = {s["id"]: 0 for s in stages}
    for c in cards:
        if c["stageId"] in counts:
            counts[c["stageId"]] += 1
    return {"counts": counts, "total": len(cards),
            "proposals": sum(1 for c in cards if c.get("proposedStageId"))}


# ── state ─────────────────────────────────────────────────────────────────────
def _load(board=DEFAULT_BOARD):
    try:
        d = json.loads(_state_path(board).read_text())
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001 — missing/corrupt state = empty board
        return {}


def _save(st, board=DEFAULT_BOARD):
    st.update(_summary(st.get("cards") or [], st.get("stages") or []))
    forge_atomic.atomic_write_json(_state_path(board), st)


# ── GHL reads (GET only) ──────────────────────────────────────────────────────
def fetch(client, board=DEFAULT_BOARD):
    """Read one board's pipeline -> (pipeline_id, stages, source, cards). GET only.
    Raises on a failed opportunity read (refresh() records it). A pipeline that is not in
    GHL (source "missing") returns no cards and makes no search."""
    try:
        pid, stages, source = resolve_pipeline(
            client.get("/opportunities/pipelines", {"locationId": client.location_id}), board)
    except Exception as e:  # noqa: BLE001 — stage ids fall back; the search below still runs
        pid, stages, source = resolve_pipeline(None, board)
        source = f"fallback ({_err(e)})"
    cards, seen, after = [], set(), None
    if pid is None:
        return pid, stages, source, cards
    for _ in range(MAX_PAGES):
        params = {"location_id": client.location_id, "pipeline_id": pid,
                  "status": "all", "limit": PAGE_SIZE}
        if after:
            params["startAfterId"], params["startAfter"] = after
        data = client.get("/opportunities/search", params)
        opps = [o for o in ((data.get("opportunities") if isinstance(data, dict) else None) or [])
                if isinstance(o, dict) and o.get("id")]
        fresh = [o for o in opps if str(o["id"]) not in seen]
        if not fresh:
            break
        for o in fresh:
            seen.add(str(o["id"]))
            if not o.get("pipelineId") or str(o.get("pipelineId")) == pid:
                cards.append(card_from(o, stages))
        meta = (data.get("meta") if isinstance(data, dict) else None) or {}
        nxt = (str(meta.get("startAfterId") or ""), str(meta.get("startAfter") or ""))
        total = meta.get("total")
        if not nxt[0] or nxt == after or (isinstance(total, int) and len(seen) >= total):
            break
        after = nxt
    return pid, stages, source, cards


def refresh(client, now=None, board=DEFAULT_BOARD):
    """One read of one board from GHL -> its state. Never raises; returns {ok, error, total}."""
    now = now or time.time()
    board = board_key(board)
    if board is None:
        return {"ok": False, "error": BAD_BOARD}
    if not enabled():
        return {"ok": False, "error": "Pipeline lane is off (FORGE_DAYCARE_PIPELINE=0)."}
    configured = bool(client is not None and getattr(client, "configured", False))
    got, error = None, None
    lock = _REFRESH_LOCKS[board]
    if not configured:
        error = "GHL not connected — add GHL_API_KEY + GHL_LOCATION_ID to daycare.env."
    elif not lock.acquire(blocking=False):
        return {"ok": False, "error": "A pipeline refresh is already running."}
    else:
        try:
            got = fetch(client, board)
        except Exception as e:  # noqa: BLE001
            error = f"GHL read failed: {_err(e)}"
        finally:
            lock.release()
    with _LOCK:
        st = _load(board)
        st["lastRunAt"], st["configured"], st["error"] = _ms(now), configured, error
        if got:
            pid, stages, source, cards = got
            # A move the owner tapped WHILE this read was in flight wins over the read.
            moved = {c["opportunityId"]: c for c in st.get("cards") or []
                     if (c.get("movedAt") or 0) >= _ms(now)}
            st.update(pipelineId=pid, stages=stages, stageSource=source, fetchedAt=_ms(now),
                      cards=[moved.get(c["opportunityId"], c) for c in cards])
        _save(st, board)
    print(f"[daycare_pipeline] refresh {board}: {len(got[3]) if got else 'n/a'} opportunities"
          + (f", error: {error}" if error else ""))
    return {"ok": error is None, "error": error, "total": st.get("total", 0)}


def refresh_manual(client, board=DEFAULT_BOARD):
    """POST /api/daycare/pipeline/refresh — the owner's Refresh tap, ≥15 s apart per board."""
    board = board_key(board)
    if board is None:
        return {"ok": False, "error": BAD_BOARD}
    wait = MANUAL_REFRESH_MIN_SEC - (time.time() - _manual_at.get(board, 0.0))
    if wait > 0:
        return {"ok": False, "error": f"Refreshed a moment ago — try again in {int(wait) + 1}s."}
    _manual_at[board] = time.time()
    return refresh(client, board=board)


# ── view (state only) ─────────────────────────────────────────────────────────
def view(configured=None, now=None, board=DEFAULT_BOARD):
    """GET /api/daycare/pipeline[?board=amt]. Reads that board's state file only — no network."""
    now = now or time.time()
    board = board_key(board)
    if board is None:
        return {"ok": False, "error": BAD_BOARD}
    st = _load(board)
    stages = st.get("stages") or resolve_pipeline(None, board)[1]
    cards = st.get("cards") or []
    fetched = st.get("fetchedAt")
    error = st.get("error")
    missing = st.get("stageSource") == "missing"
    if not enabled():
        error = "Pipeline lane is off (FORGE_DAYCARE_PIPELINE=0)."
    elif not st.get("lastRunAt"):
        error = ("Not read yet — it refreshes every 5 min on the box (loops are off on a "
                 "UI-only machine). Tap Refresh to read GHL now.")
    cols = []
    for s in stages:
        mine = sorted((c for c in cards if c["stageId"] == s["id"]),
                      key=lambda c: (c.get("proposedStageId") is None, -(c.get("createdAt") or 0)))
        cols.append({"id": s["id"], "name": s["name"], "slug": s["slug"],
                     "count": len(mine), "cards": mine})
    return {
        "ok": True,
        "enabled": enabled(),
        "configured": bool(st.get("configured")) if configured is None else bool(configured),
        "stages": cols,
        "proposals": sum(1 for c in cards if c.get("proposedStageId")),
        "total": len(cards),
        "unstaged": sum(1 for c in cards if c["stageId"] not in {s["id"] for s in stages}),
        "fetchedAt": fetched,
        "lastRunAt": st.get("lastRunAt"),
        "stale": not fetched or now - fetched / 1000 > STALE_SEC,
        "stageSource": st.get("stageSource"),
        "error": error,
        "board": board,
        "label": BOARDS[board][3],
        "pipelineName": BOARDS[board][0],
        "missing": missing,
    }


# ── owner taps (the ONLY GHL writes) ──────────────────────────────────────────
def _stage_for(stages, value):
    v = str(value or "").strip()
    return next((s for s in stages if v and (s["id"] == v or s["slug"] == _slug(v))), None)


def _live_pipeline_ok(client, oid, pid):
    """GET the opportunity and confirm it is STILL in this board's pipeline (n8n moves A
    Mother's Touch families between pipelines). None = ok, else an error dict. Fail-closed."""
    try:
        data = client.get(f"/opportunities/{oid}")
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "opportunityId": oid, "code": getattr(e, "code", None),
                "error": f"Could not confirm the card's pipeline in GHL: {_err(e)}"}
    # GHL v2 nests it under "opportunity" (not verified live); a bare object is accepted too.
    opp = data if isinstance(data, dict) else {}
    opp = opp.get("opportunity") if isinstance(opp.get("opportunity"), dict) else opp
    if not pid or str(opp.get("pipelineId") or "") != str(pid):
        return {"ok": False, "opportunityId": oid,
                "error": "This card is no longer in this pipeline in GHL — refresh and try again."}
    return None


def _move_one(client, opportunity_id, stage, now, board=DEFAULT_BOARD):
    """Caller holds _MOVE_LOCK. PUT the stage, clear the proposal tags, update the card."""
    oid = str(opportunity_id or "").strip()
    st = _load(board)
    stages = st.get("stages") or []
    card = next((c for c in st.get("cards") or [] if oid and c["opportunityId"] == oid), None)
    if not card:
        return {"ok": False, "opportunityId": oid,
                "error": f"Not a {BOARDS[board][0]} pipeline card — refresh and try again."}
    target = _stage_for(stages, stage)
    if not target:
        return {"ok": False, "opportunityId": oid,
                "error": "Stage must be one of: " + ", ".join(s["name"] for s in stages)}
    if card["stageId"] != target["id"]:
        bad = _live_pipeline_ok(client, oid, st.get("pipelineId"))
        if bad:
            return bad
        try:
            client.put(f"/opportunities/{oid}", {"pipelineStageId": target["id"]})
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "opportunityId": oid, "code": getattr(e, "code", None),
                    "error": f"GHL move failed: {_err(e)}"}
    tags_cleared, warning = True, None
    if card.get("proposeTags") and card.get("contactId"):
        try:
            client.delete(f"/contacts/{card['contactId']}/tags", {"tags": card["proposeTags"]})
        except Exception as e:  # noqa: BLE001 — the move stands; the tag reappears on refresh
            tags_cleared, warning = False, f"Moved, but the proposal tag could not be removed: {_err(e)}"
    with _LOCK:
        st = _load(board)
        for c in st.get("cards") or []:
            if c["opportunityId"] == oid:
                c.update(stageId=target["id"], stageName=target["name"], movedAt=_ms(now),
                         updatedAt=_ms(now), proposedStageId=None, proposedStageName=None)
                if tags_cleared:
                    c["proposeTags"] = []
        _save(st, board)
    print(f"[daycare_pipeline] owner move ({board}): opp {oid} -> stage {target['id']}"
          + ("" if tags_cleared else " (proposal tag NOT cleared)"))
    out = {"ok": True, "opportunityId": oid, "stageId": target["id"], "stageName": target["name"],
           "tagsCleared": tags_cleared}
    if warning:
        out["warning"] = warning
    return out


def _gate(client):
    if not enabled():
        return "Pipeline lane is off (FORGE_DAYCARE_PIPELINE=0)."
    if client is None or not getattr(client, "configured", False):
        return "GHL not connected — add GHL_API_KEY + GHL_LOCATION_ID to daycare.env."
    return None


def move(client, opportunity_id, stage, board=DEFAULT_BOARD):
    """POST /api/daycare/pipeline/move — the owner's tap moves ONE card on ONE board.
    stage = id or slug of THAT board's stages."""
    b = board_key(board)
    blocked = BAD_BOARD if b is None else _gate(client)
    if blocked:
        return {"ok": False, "error": blocked}
    with _MOVE_LOCK:
        return _move_one(client, opportunity_id, stage, time.time(), b)


def move_all_proposed(client, confirm=False, board=DEFAULT_BOARD):
    """POST /api/daycare/pipeline/move-all — the owner's confirmed tap approves every
    proposal on ONE board, ≤50 per call. Stops early on a GHL rate limit (429)."""
    b = board_key(board)
    blocked = (BAD_BOARD if b is None else _gate(client)) or (None if confirm is True else "confirm:true required")
    if blocked:
        return {"ok": False, "error": blocked}
    with _MOVE_LOCK:
        todo = [c for c in _load(b).get("cards") or [] if c.get("proposedStageId")]
        results = []
        for c in todo[:MOVE_ALL_CAP]:
            r = _move_one(client, c["opportunityId"], c["proposedStageId"], time.time(), b)
            results.append(r)
            if r.get("code") == 429:
                break
    moved = sum(1 for r in results if r["ok"])
    return {"ok": moved == len(results), "moved": moved, "failed": len(results) - moved,
            "remaining": len(todo) - moved, "results": results}


# ── loop ──────────────────────────────────────────────────────────────────────
def counts(now=None):
    """Both boards' counts for Solomon's chat context — state files only, no network, no
    names, never raises. Keys stay per board: the two businesses are never summed."""
    now = now or time.time()
    out = {}
    for b in BOARDS:
        try:
            v = view(now=now, board=b)
            out[b] = {"label": v["label"], "total": v["total"], "proposals": v["proposals"],
                      "byStage": {s["name"]: s["count"] for s in v["stages"]},
                      "stale": v["stale"], "missing": v["missing"]}
        except Exception as e:  # noqa: BLE001
            out[b] = {"unreadable": type(e).__name__}
    return out


def run_forever(client):
    """Background loop (thread `daycare_pipeline` — Solomon's Pipeline lane). GET only.
    Refreshes BOTH boards each tick; the heartbeat carries the first error."""
    last = (_load().get("lastRunAt") or 0) / 1000
    time.sleep(max(0, min(INTERVAL, last + INTERVAL - time.time())))   # deploys restart often
    while True:
        err = None
        try:
            if client is None or not getattr(client, "configured", False):
                err = "Daycare GHL not configured"
            elif not forge_ops.paused():
                errs = []
                for b in BOARDS:
                    e = refresh(client, board=b).get("error")
                    if e:
                        errs.append(f"{b}: {e}")
                err = "; ".join(errs) or None
        except Exception as e:  # noqa: BLE001
            err = type(e).__name__
        forge_heartbeat.beat("daycare_pipeline", INTERVAL, "Solomon · Pipeline", error=err)
        time.sleep(INTERVAL)
