"""daycare_ads_tg.py — Solomon · Ads Telegram approval cards (2026-10-17).

The owner's goal: "the box runs it, the agents create + optimize the ads on their own — with the
push of an approval from Telegram." This module is the tap layer, in the DAYCARE chat only:

  OPTIMIZE  one card per shadow proposal (pause / budget move / turn on a test) with the rule
            that fired, the numbers + window + source and the guardrails. ✅ = autopilot.approve
            (fresh guard against live Meta), ❌ = reject, then a receipt with ↩ Undo.
  CREATE    concept cards: Solomon's Ad Generator concepts (daycare_ads_studio.ideas) with a
            preview image drawn by the guarded Higgsfield engine as source "auto" (quoted cost
            only, HIGGSFIELD_AUTO_CREDITS). No real image → a text card and NO build button.
            ✅ Build = daycare_ads_studio.create_ad (PAUSED-only) → LAUNCH card.
  LAUNCH    🚀 $10 / $20 per day = daycare_ads_autopilot.launch (every guard there) → receipt
            with ↩ Undo (pauses campaign + ad set + ad).

Nothing here applies on its own: every Meta write is behind one of these tap handlers, and the
taps themselves are two-factor (right chat AND allowed user — telegram_io._authorized). The
autopilot mode is never changed here; in "off" no card is sent and every handler refuses.
callback_data = "<prefix>:<card id>[:<usd>]" (≤ 21 bytes, Telegram allows 64); the card id maps
to the proposal / idea server-side in marcus_state/daycare_ads_cards.json, and a card is
single-use (pending → working → final) so a double tap can never run twice.
Kill: FORGE_DAYCARE_ADS_CARDS=0 · autopilot mode off · forge_ops clock-out.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from pathlib import Path

import forge_atomic
import forge_ops

HERE = Path(__file__).resolve().parent
STORE = forge_atomic.guard_state_path(HERE / "marcus_state" / "daycare_ads_cards.json")
BIZ = "daycare"
MAX_CARDS = 200
AUTO_CONCEPTS_PER_DAY = 3
MAX_PENDING_CONCEPTS = 3
CONCEPT_TTL = 3 * 86400            # an un-actioned concept card stops counting as pending after 3 days
_LOCK = threading.RLock()
_SYNC = False                      # tests: run "background" work inline
FINAL = ("applied", "skipped", "failed", "built", "launched", "kept", "discarded", "replaced",
         "undone", "expired", "done")


def enabled() -> bool:
    return os.environ.get("FORGE_DAYCARE_ADS_CARDS", "1") != "0"


# ── store ───────────────────────────────────────────────────────────────────────────────────
def _load() -> dict:
    try:
        d = json.loads(Path(STORE).read_text())
        return d if isinstance(d, dict) else {"cards": []}
    except Exception:  # noqa: BLE001
        return {"cards": []}


def _save(d: dict) -> None:
    d["cards"] = (d.get("cards") or [])[-MAX_CARDS:]
    try:
        Path(STORE).parent.mkdir(parents=True, exist_ok=True)
        forge_atomic.atomic_write_json(STORE, d)
    except Exception:  # noqa: BLE001
        pass


def _new(kind: str, ref: str, **kw) -> dict:
    now = int(time.time() * 1000)
    card = {"id": "c" + secrets.token_hex(4), "kind": kind, "ref": str(ref), "state": "pending",
            "createdAt": now, "updatedAt": now, **kw}
    with _LOCK:
        d = _load()
        d.setdefault("cards", []).append(card)
        _save(d)
    return card


def _get(cid: str) -> dict | None:
    return next((c for c in _load().get("cards") or [] if c.get("id") == cid), None)


def _set(cid: str, **patch) -> dict | None:
    with _LOCK:
        d = _load()
        for c in d.get("cards") or []:
            if c.get("id") == cid:
                c.update(patch, updatedAt=int(time.time() * 1000))
                _save(d)
                return c
    return None


def _claim(cid: str, kinds: tuple, to: str = "working") -> tuple:
    """Atomically move a PENDING card of one of `kinds` to `to`. (card, None) or (None, why).
    This is what makes every button single-use."""
    with _LOCK:
        d = _load()
        c = next((x for x in d.get("cards") or [] if x.get("id") == str(cid or "").strip()), None)
        if not c or c.get("kind") not in kinds:
            return None, "unknown or expired card"
        if c.get("state") != "pending":
            return None, f"already handled ({c.get('state')})"
        c.update(state=to, updatedAt=int(time.time() * 1000))
        _save(d)
        return dict(c), None


def _bg(fn, name: str = "daycare_ads") -> None:
    """Off the Telegram poll thread / HTTP thread. Thread name bills Claude spend to Solomon."""
    if _SYNC:
        fn()
        return
    import higgsfield_io
    higgsfield_io.run_in_background(fn, lambda r: None, timeout=3600, name=name)


# ── Telegram send (one place, so tests swap one transport) ───────────────────────────────────
def _tg():
    import telegram_io
    return telegram_io


def _esc(s) -> str:
    return _tg()._esc(s)


def _send(text: str, buttons=None, dedupe: str | None = None) -> dict:
    try:
        return _tg().send_biz(BIZ, text, buttons=buttons, dedupe_key=dedupe) or {}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}"}


def _send_photo(url: str, caption: str, buttons=None, dedupe: str | None = None) -> dict:
    try:
        return _tg().send_photo(BIZ, url, caption, buttons=buttons, dedupe_key=dedupe) or {}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}"}


def _btn(text: str, data: str) -> dict:
    assert len(data.encode()) <= 64, data          # Telegram's hard callback_data limit
    return {"text": text, "callback_data": data}


def _mark_sent(card: dict, r: dict) -> None:
    _set(card["id"], sent=bool(r.get("ok")), sendError=None if r.get("ok") else str(r.get("error") or "")[:120],
         messageId=r.get("messageId"))


# ── OPTIMIZE cards ──────────────────────────────────────────────────────────────────────────
def _usd(v) -> str:
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return "n/a"


def optimize_text(rec: dict, run: dict | None = None) -> str:
    """Plain words: the action, the rule that fired, the numbers WITH window + source, the guard."""
    import datetime as dt
    import daycare_ads_autopilot as ap
    run = run or {}
    c = ap.cfg()
    try:
        today = dt.date.fromisoformat(str(run.get("day") or "")[:10])
    except ValueError:
        today = ap.local_now().date()
    until = (today - dt.timedelta(days=1)).isoformat()
    s14, s7 = (today - dt.timedelta(days=14)).isoformat(), (today - dt.timedelta(days=7)).isoformat()
    ev = rec.get("evidence") or {}
    name = _esc(rec.get("name") or rec.get("id"))
    if rec.get("kind") == "budget":
        verb = "Raise" if rec["to"] > rec["from"] else "Cut"
        what = f"{verb} the daily budget of {rec.get('level')} “{name}” from {_usd(rec['from'] / 100)} to {_usd(rec['to'] / 100)}/day"
    elif rec.get("to") == "PAUSED":
        what = f"Pause {rec.get('level')} “{name}”"
    else:
        what = f"Turn ON {rec.get('level')} “{name}”"
    tcpl = ev.get("tcpl") or run.get("tcpl") or c["tcpl"]
    if "spend14" in ev:
        nums = (f"14 days {s14}→{until}: spend {_usd(ev.get('spend14'))}, {ev.get('leads14', 0)} leads, "
                f"CPL {_usd(ev.get('cpl14')) if ev.get('cpl14') else 'n/a'} vs {_usd(tcpl)} target")
        if "cpl7" in ev:
            nums += f"; 7 days {s7}→{until}: CPL {_usd(ev.get('cpl7')) if ev.get('cpl7') else 'n/a'} on {ev.get('leads7', 0)} leads"
        if ev.get("freq"):
            nums += f"; frequency {ev['freq']}"
        src = "Meta via Pipeboard (pixel leads, not enrollments) · complete days, America/New_York"
    else:
        nums = "New test ad — no results yet; it spends from its ad set's existing budget once on."
        src = "Solomon's creative loop"
    total = run.get("totalBudget")
    guard = (f"At your tap it re-checks live Meta first: cooldown, ≤+20% step, the {_usd(c['maxDaily'])}/day "
             f"account ceiling{' (active now ' + _usd(total) + ')' if total is not None else ''}, never the "
             "last ad in an ad set.")
    return (f"🧮 <b>Solomon · Ads — proposal</b>\n<b>{what}</b>\nWhy: {_esc(rec.get('reason') or '')}\n"
            f"📊 {_esc(nums)}\nSource: {src}\n🛡 {guard}")


def send_optimize_cards(run: dict | None = None, actions: list | None = None) -> list:
    """One card per PROPOSED autopilot action not already carded. Older pending optimize cards
    whose proposal was superseded are expired. Returns the new cards."""
    import daycare_ads_autopilot as ap
    if not enabled() or ap.get_mode() != "shadow":
        return []
    props = [a for a in (actions if actions is not None else ap._load().get("actions") or [])
             if a.get("status") == "proposed" and a.get("aid")]
    live = {a["aid"] for a in props}
    with _LOCK:
        d = _load()
        for c in d.get("cards") or []:
            if c.get("kind") == "optimize" and c.get("state") == "pending" and c.get("ref") not in live:
                c.update(state="expired", updatedAt=int(time.time() * 1000))
        seen = {c.get("ref") for c in d.get("cards") or [] if c.get("kind") == "optimize"}
        _save(d)
    out = []
    for rec in props:
        if rec["aid"] in seen:
            continue
        card = _new("optimize", rec["aid"], title=ap._fmt_action(rec)[:120])
        r = _send(optimize_text(rec, run), [[_btn("✅ Apply", f"adsapply:{card['id']}"),
                                             _btn("❌ Skip", f"adsskip:{card['id']}")]],
                  dedupe=f"adscard-{rec['aid']}")
        _mark_sent(card, r)
        out.append(_get(card["id"]))
    return out


# ── CREATE (concept) cards ──────────────────────────────────────────────────────────────────
def _today() -> str:
    import higgsfield_io
    return higgsfield_io._today()


def _expire_old_concepts() -> None:
    cut = (time.time() - CONCEPT_TTL) * 1000
    with _LOCK:
        d = _load()
        for c in d.get("cards") or []:
            if c.get("kind") == "concept" and c.get("state") == "pending" and c.get("createdAt", 0) < cut:
                c.update(state="expired", updatedAt=int(time.time() * 1000))
        _save(d)


def _pending(kind: str) -> int:
    return sum(1 for c in _load().get("cards") or [] if c.get("kind") == kind and c.get("state") == "pending")


def _auto_today() -> int:
    day = _today()
    return sum(1 for c in _load().get("cards") or [] if c.get("kind") == "concept"
               and c.get("source") == "auto" and c.get("day") == day)


def concept_caption(idea: dict, credits=None, why: str = "", next_step: str = "", body_max: int = 380) -> str:
    lines = [f"🎨 <b>New ad concept</b> — {_esc((idea.get('title') or 'Concept')[:80])}",
             f"<b>{_esc((idea.get('headline') or '')[:60])}</b>",
             _esc((idea.get("primaryText") or "")[:body_max]),
             f"CTA {_esc(idea.get('cta') or '—')} · {_esc(idea.get('format') or '1:1')}",
             f"📊 {_esc((idea.get('evidence') or 'Unknown — no evidence cited')[:180])}"]
    if credits is not None:
        lines.append(f"🖼 Preview ≈ {float(credits):g} credits (Higgsfield app credits — not ad spend)")
        lines.append("✅ Build = creates it PAUSED on Meta, nothing spends. Launching is a separate tap.")
    else:
        lines.append(f"🖼 No preview image: {_esc(why[:160]) or 'not generated'}")
        if next_step:
            lines.append(f"Next step: {_esc(next_step[:600])}")
        lines.append("No Build button until a real image exists — I never fake one.")
    return "\n".join(x for x in lines if x)


def _concept_card(idea: dict, source: str) -> dict:
    """Preview image (auto source: quoted cost only, auto cap) → photo card with Build; else a
    text card without Build. Never raises."""
    import daycare_ads_studio as studio
    import higgsfield_io as hf
    card = _new("concept", idea["id"], source=source, day=_today(), title=(idea.get("title") or "")[:80])
    out, why, nxt = {}, "", ""
    try:
        eng = hf.status()
        if not eng.get("ready"):
            why, nxt = "the image engine is not ready", eng.get("nextStep") or ""
            if (eng.get("cli") or {}).get("lapsed"):
                hf.alert_login_lapsed("needed for an automatic ad preview")
        else:
            out = studio.generate_asset(idea["id"], confirm=True, trigger="telegram_auto")
            if not out.get("ok"):
                why = str(out.get("error") or "image not generated")
    except Exception as e:  # noqa: BLE001
        why = f"{type(e).__name__}"
    drop = [_btn("🔁 Another angle", f"adsalt:{card['id']}"), _btn("❌ Discard", f"adsdrop:{card['id']}")]
    if out.get("ok") and out.get("imageUrl"):
        _set(card["id"], imageUrl=out["imageUrl"], credits=out.get("credits"))
        tl = _target_line()
        cap = concept_caption(idea, out.get("credits")) + tl
        if len(cap) > tg_caption_room():                  # shrink the body, never cut HTML mid-tag
            cap = concept_caption(idea, out.get("credits"), body_max=max(60, 380 - (len(cap) - tg_caption_room()))) + tl
        r = _send_photo(out["imageUrl"], cap,
                        [[_btn("✅ Build PAUSED ad", f"adsbuild:{card['id']}")], drop],
                        dedupe=f"adscard-{idea['id']}")
    else:
        _set(card["id"], noImage=why[:160])
        r = _send(concept_caption(idea, None, why, nxt), [drop], dedupe=f"adscard-{idea['id']}")
    _mark_sent(card, r)
    return _get(card["id"])


def tg_caption_room() -> int:
    return 1000                                           # Telegram allows 1024; leave room for the tap footer


def _target_line() -> str:
    """Up front, on the concept card: which ad set ✅ Build would join, and whether the launch tap
    could be used for it (CBO / lifetime / other live ads → "launch it in Meta yourself")."""
    try:
        import daycare_ads_autopilot as ap
        import daycare_ads_studio as studio
        if not ap.configured():
            return ""
        t = studio.build_target()
        if not t.get("ok"):
            return f"\n🎯 Build target Unknown: {_esc(str(t.get('error') or '')[:140])}"
        ev = t.get("evidence") or {}
        line = (f"\n🎯 Builds into “{_esc((t.get('adset') or {}).get('name'))[:60]}” — {ev.get('leads', 0)} leads, "
                f"CPL {_usd(ev.get('cpl'))} ({_esc(ev.get('window') or 'Maximum')}, Meta via Pipeboard)")
        if t.get("blockers"):
            line += f"\n⚠ Launch it in Meta yourself: {_esc('; '.join(t['blockers'])[:180])}"
        return line
    except Exception:  # noqa: BLE001
        return ""


def send_concept_cards(n: int = 3, source: str = "auto") -> dict:
    """Draft concepts (one Claude call) and send up to n cards. Synchronous — callers run it
    in the background. Throttles: clock-out, autopilot off, ≥3 un-actioned concept cards,
    ≤3 auto cards per operator day."""
    import daycare_ads_autopilot as ap
    if not enabled():
        return {"ok": False, "skipped": "cards switched off (FORGE_DAYCARE_ADS_CARDS=0)"}
    if forge_ops.paused():
        return {"ok": False, "skipped": "agents are clocked out"}
    if ap.get_mode() == "off":
        return {"ok": False, "skipped": "ads autopilot is off"}
    _expire_old_concepts()
    pend = _pending("concept")
    room = MAX_PENDING_CONCEPTS - pend
    if room <= 0:
        return {"ok": False, "skipped": f"{pend} concept cards are still waiting for your tap"}
    n = max(1, min(int(n or 1), 3, room))
    if source == "auto":
        left = AUTO_CONCEPTS_PER_DAY - _auto_today()
        if left <= 0:
            return {"ok": False, "skipped": "today's automatic concept cards were already sent"}
        n = min(n, left)
    import daycare_ads_studio as studio
    r = studio.ideas(None)
    if not r.get("ok"):
        _send(f"🎨 Solomon couldn't draft new ad concepts: {_esc(str(r.get('error') or '')[:200])}",
              dedupe=f"adsconcept-fail-{_today()}")
        return {"ok": False, "error": r.get("error")}
    cards = [_concept_card(idea, source) for idea in (r.get("next") or [])[:n]]
    return {"ok": True, "cards": cards, "packetUnknown": r.get("packetUnknown")}


def start_concept_cards(n: int = 3, source: str = "chat") -> dict:
    """The route / partner entry: quick checks inline, the slow part in the background."""
    import daycare_ads_autopilot as ap
    if not enabled():
        return {"ok": False, "error": "Telegram ad cards are switched off (FORGE_DAYCARE_ADS_CARDS=0)"}
    if forge_ops.paused():
        return {"ok": False, "error": "agents are clocked out"}
    if ap.get_mode() == "off":
        return {"ok": False, "error": "ads autopilot is off"}
    try:
        n = max(1, min(int(n or 3), 3))
    except (TypeError, ValueError):
        n = 3
    _bg(lambda: send_concept_cards(n, source))
    return {"ok": True, "queued": True, "n": n,
            "message": f"Drafting {n} concept card(s) for the daycare Telegram chat — preview images only "
                       "within HIGGSFIELD_AUTO_CREDITS; nothing is built or launched without your tap."}


def after_run(run: dict) -> None:
    """Called by the autopilot after a SHADOW daily run: proposal cards now, concept cards in the
    background on the creative cadence (FORGE_DAYCARE_ADS_CREATIVE, every creativeEveryDays)."""
    import daycare_ads_autopilot as ap
    send_optimize_cards(run)
    c = ap.cfg()
    if not c["creative"]:
        return
    last = max([x.get("createdAt", 0) for x in _load().get("cards") or []
                if x.get("kind") == "concept" and x.get("source") == "auto"] or [0])
    if time.time() * 1000 - last >= c["creativeEveryDays"] * 86400 * 1000 - 3600 * 1000:
        _bg(lambda: send_concept_cards(3, "auto"))


# ── LAUNCH cards ────────────────────────────────────────────────────────────────────────────
def _send_launch_card(idea: dict) -> dict:
    import daycare_ads_autopilot as ap
    meta = idea.get("meta") or {}
    card = _new("launch", idea["id"], title=(idea.get("title") or "")[:80])
    amts = ap.launch_budgets()[:3]
    blockers = meta.get("blockers") or []
    head = (f"🚀 <b>Built PAUSED</b> — {_esc(idea.get('title') or 'Ad')}\n"
            + (_joined_line(meta) + "\n" if meta.get("adsetName") else "")
            + f"Campaign {_esc(meta.get('campaignId'))} · ad set {_esc(meta.get('adsetId'))} · ad {_esc(meta.get('adId'))}\n"
            "Nothing is serving or spending.\n")
    if blockers:
        text = head + ("⚠ Launch this one in Meta yourself — from here it would be refused: "
                       + _esc("; ".join(blockers)) + ".\n")
    else:
        text = head + ("Launch turns ON the campaign, ad set and ad at the budget you tap (≈30× that per month "
                       f"if it runs all month). Daily ceiling {_usd(ap.cfg()['maxDaily'])} across every active ad "
                       "set; one launch per 24 h.\n")
    text += f"<a href=\"{_esc(meta['url'])}\">Open in Ads Manager</a>" if meta.get("url") else ""
    rows = ([] if blockers else [[_btn(f"🚀 Launch at ${a}/day", f"adslaunch:{card['id']}:{a}") for a in amts]]) \
        + [[_btn("Keep paused", f"adskeep:{card['id']}")]]
    img = meta.get("imageUrl") or idea.get("imageUrl")
    r = _send_photo(img, text, rows, dedupe=f"adslaunch-{idea['id']}") if img else \
        _send(text, rows, dedupe=f"adslaunch-{idea['id']}")
    _mark_sent(card, r)
    return _get(card["id"])


def _joined_line(meta: dict) -> str:
    """Which ad set the build joined and why — with window + source (never a bare number)."""
    ev = meta.get("evidence") or {}
    win = f"{ev.get('window') or 'Maximum'} {ev.get('since') or '?'}→{ev.get('until') or '?'}"
    return (f"Joined ad set “{_esc(meta.get('adsetName') or meta.get('adsetId'))}” (campaign "
            f"“{_esc(meta.get('campaignName') or meta.get('campaignId'))}”) — the account's best: "
            f"{ev.get('leads', 0)} leads, CPL {_usd(ev.get('cpl'))} on {_usd(ev.get('spend'))} "
            f"({_esc(win)}{', ' + _esc(ev['tz']) if ev.get('tz') else ''}; {_esc(ev.get('source') or 'Meta via Pipeboard')}). "
            "It inherits that ad set's targeting, optimization and destination.")


def _send_undo_receipt(text: str, aid: str) -> dict:
    card = _new("undo", aid, title=text[:120])
    r = _send(text, [[_btn("↩ Undo", f"adsundo:{card['id']}")]])
    _mark_sent(card, r)
    return _get(card["id"])


# ── tap handlers (each returns fast; slow Meta / image work runs in the background) ──────────
def _off_refusal():
    import daycare_ads_autopilot as ap
    if ap.get_mode() == "off":
        return {"error": "ads autopilot is off — nothing applied"}
    return None


def h_apply(cid: str) -> dict:
    if (no := _off_refusal()):
        return no
    card, err = _claim(cid, ("optimize",))
    if err:
        return {"error": err}

    def work():
        import daycare_ads_autopilot as ap
        r = ap.approve(card["ref"])
        if r.get("ok"):
            _set(card["id"], state="applied")
            a = r.get("action") or {}
            _send_undo_receipt(f"✅ Applied: {_esc(ap._fmt_action(a) if a else card.get('title'))}"
                               f"{' (verified on Meta)' if a.get('verified') else ' (Meta has not confirmed it yet)'}",
                               card["ref"])
        else:
            _set(card["id"], state="failed", error=str(r.get("error") or "")[:160])
            _send(f"⚠ Not applied — {_esc(str(r.get('error') or (r.get('action') or {}).get('why') or 'failed')[:200])}")
    _bg(work)
    return {"message": "Applying — checking live Meta first; receipt follows"}


def h_skip(cid: str) -> dict:
    card, err = _claim(cid, ("optimize",))
    if err:
        return {"error": err}
    import daycare_ads_autopilot as ap
    ap.reject(card["ref"])
    _set(card["id"], state="skipped")
    return {"message": "Skipped — nothing changed on Meta"}


def h_undo(cid: str) -> dict:
    card, err = _claim(cid, ("undo",))
    if err:
        return {"error": err}

    def work():
        import daycare_ads_autopilot as ap
        r = ap.undo(card["ref"])
        _set(card["id"], state="undone" if r.get("ok") else "failed", error=None if r.get("ok") else str(r.get("error"))[:160])
        _send("↩ Undone." if r.get("ok") else f"⚠ Undo failed — {_esc(str(r.get('error'))[:200])}")
    _bg(work)
    return {"message": "Undoing — receipt follows"}


def h_build(cid: str) -> dict:
    if (no := _off_refusal()):
        return no
    import daycare_ads_studio as studio
    c0 = _get(cid)
    if c0 and c0.get("kind") == "concept" and not c0.get("imageUrl"):
        return {"error": "no real preview image on this card — build it from the Ad Studio"}
    if not studio.build_ready():
        return {"error": "Build needs PIPEBOARD_API_TOKEN in daycare.env — nothing was sent to Meta"}
    card, err = _claim(cid, ("concept",))
    if err:
        return {"error": err}

    def work():
        try:
            r = studio.build(card["ref"])           # Pipeboard, inside the best ad set (Graph only without it)
        except Exception as e:  # noqa: BLE001 — a plain-words card, never a stack trace
            r = {"ok": False, "error": f"build stopped ({type(e).__name__})"}
        idea = studio._find(card["ref"]) or {}
        if r.get("ok") and (idea.get("meta") or {}).get("adId"):
            _set(card["id"], state="built")
            _send_launch_card(idea)
        else:
            why = str(r.get("error") or r.get("detail") or "no ad id came back")[:240]
            _set(card["id"], state="failed", error=why[:160])
            _send(f"⚠ Build failed — {_esc(why)}\nNothing was switched on.")
    _bg(work)
    return {"message": "Building it PAUSED on Meta — the launch card follows"}


def h_alt(cid: str) -> dict:
    if (no := _off_refusal()):
        return no
    card, err = _claim(cid, ("concept",), to="replaced")
    if err:
        return {"error": err}
    _bg(lambda: send_concept_cards(1, "alt"))
    return {"message": "Drafting another angle — caps still apply"}


def h_drop(cid: str) -> dict:
    card, err = _claim(cid, ("concept",), to="discarded")
    if err:
        return {"error": err}
    import daycare_ads_studio as studio
    studio.discard(card["ref"])
    return {"message": "Discarded"}


def _launch_work(card: dict, usd: int, second_ok: bool) -> None:
    import daycare_ads_autopilot as ap
    r = ap.launch(card["ref"], usd, second_ok=second_ok)
    if r.get("ok"):
        _set(card["id"], state="launched", usd=usd, noop=bool(r.get("noop")))
        a = r.get("action") or {}
        if a.get("aid"):
            _send_undo_receipt(f"🚀 Launched {_esc(card.get('title') or 'the ad')} at ${usd}/day — Meta shows the "
                               "campaign, ad set and ad ACTIVE at that budget.", a["aid"])
        else:
            _send(f"🚀 {_esc(r.get('message') or 'already live')}")
    elif r.get("code") == "daily_limit":
        _set(card["id"], state="done", error=str(r.get("error"))[:160])
        again = _new("launch2", card["ref"], usd=usd, title=card.get("title"))
        rr = _send(f"⚠ {_esc(r.get('error'))}\nTap below only if you really want a second launch today.",
                   [[_btn(f"⚠️ Yes — launch a second ad at ${usd}/day", f"adsagain:{again['id']}:{usd}")],
                    [_btn("Keep paused", f"adskeep:{again['id']}")]])
        _mark_sent(again, rr)
    else:
        _set(card["id"], state="failed", error=str(r.get("error"))[:160])
        _send(f"⚠ Not launched — {_esc(str(r.get('error'))[:240])}")


def _parse_amt(arg: str) -> tuple:
    cid, _, amt = str(arg or "").partition(":")
    try:
        return cid, int(amt)
    except ValueError:
        return cid, None


def h_launch(arg: str) -> dict:
    if (no := _off_refusal()):
        return no
    cid, usd = _parse_amt(arg)
    import daycare_ads_autopilot as ap
    if usd not in ap.launch_budgets():
        return {"error": "not an allowed launch budget"}
    card, err = _claim(cid, ("launch",))
    if err:
        return {"error": err}
    _bg(lambda: _launch_work(card, usd, False))
    return {"message": f"Launching at ${usd}/day — guards + Meta verify first; receipt follows"}


def h_again(arg: str) -> dict:
    if (no := _off_refusal()):
        return no
    cid, usd = _parse_amt(arg)
    c0 = _get(cid)
    if not c0 or c0.get("usd") != usd:
        return {"error": "amount does not match this card"}
    card, err = _claim(cid, ("launch2",))
    if err:
        return {"error": err}
    _bg(lambda: _launch_work(card, usd, True))
    return {"message": f"Launching a second ad at ${usd}/day — receipt follows"}


def h_keep(cid: str) -> dict:
    card, err = _claim(cid, ("launch", "launch2"), to="kept")
    if err:
        return {"error": err}
    return {"message": "Kept PAUSED — nothing spends"}


def handlers() -> dict:
    """Merged into telegram_io.set_actions in connector.py."""
    return {"adsapply": h_apply, "adsskip": h_skip, "adsundo": h_undo, "adsbuild": h_build,
            "adsalt": h_alt, "adsdrop": h_drop, "adslaunch": h_launch, "adsagain": h_again,
            "adskeep": h_keep}


# ── read model for the dashboard ────────────────────────────────────────────────────────────
def cards_view(limit: int = 30) -> dict:
    cards = list(reversed(_load().get("cards") or []))
    counts: dict = {}
    for c in cards:
        counts[c.get("state")] = counts.get(c.get("state"), 0) + 1
    keep = ("id", "kind", "state", "title", "source", "createdAt", "updatedAt", "imageUrl", "credits",
            "usd", "sent", "sendError", "error", "noImage")
    return {"ok": True, "enabled": enabled(), "pending": counts.get("pending", 0), "counts": counts,
            "cards": [{k: c.get(k) for k in keep if c.get(k) is not None} for c in cards[:max(1, min(limit, 100))]]}
