"""daycare_center_tag.py — put the right A Touch of Blessings center tag on a family, by itself.

Owner decision 2026-11-12: "we don't need approval for tagging someone; always auto tag properly."
A family on the ATOB board with NO `loc-` tag gets `loc-921-n-18th` or `loc-2318-cecil-b-moore` when the
parent's own form fields name exactly one of those centers. No Claude call, no tap. Two entry points:

  run(cards, client)         the box loop: daycare_pipeline.refresh calls it after every GHL read.
  safe_to_add(cid, tag)      the agents' gate: dash_live lets an agent's `ghl/tag` write that adds ONE
                             center tag run without a card, but only with the SAME evidence the loop needs (the
                             family's own fields name exactly that center), so no agent picks a center by guess.

Evidence = the contact's custom fields named exactly "Preferred Location", "Tour Location" or "SMS Center"
(parent-typed text, so it is read strictly: short, no phone/URL/suite words, and its only 2+ digit numbers are
exactly 921 or exactly 2318). What never happens (October 2026: center tags needed a tap to keep the two legal
entities apart): never loc-1923 or any AMT mark (`entity-amt`, a 1923 tag, the contact on the AMT board, text
naming AMT / 1923 / Mother's Touch in any spelling), never when the family already has ANY `loc-` tag
(add-only, never a move), never two centers named in one field or across fields, never a ZZ test family,
never when either board is unread / errored / older than 15 min / not live (fail closed), never when the
LIVE contact (read right before the write) has any loc- or AMT tag. Per-family 2-minute claim so two writers
can't both pass; daily caps (loop 30, agents 20); 5 tags per pass. Intake / login / confirmation tags stay
owner-tapped (they start enrollment and PIN texts). Kill: FORGE_DAYCARE_AUTO_CENTER=0 stops BOTH paths.
Box only for the loop (FORGE_MARCUS=1).
"""
from __future__ import annotations

import os
import re
import threading
import time
import unicodedata

BOARD = "enrollment"                          # ATOB. Never "amt".
SITE_TAG = {"atob-one": "loc-921-n-18th", "atob-two": "loc-2318-cecil-b-moore"}
TAG_SITE = {v: k for k, v in SITE_TAG.items()}
CENTER_LABEL = {"loc-921-n-18th": "921 N 18th", "loc-2318-cecil-b-moore": "2318 Cecil B. Moore"}
FIELD_NAMES = {"preferred location", "tour location", "sms center"}      # exact field names, nothing fuzzy
MAX_VALUE = 80                                # a center answer is short; a paragraph is not evidence
_AMT_BITS = ("amt", "1923", "mothertouch", "motherstouch", "momstouch", "momtouch", "entityamt")
_VETO = re.compile(r"(suite|\bste\b|\bapt\b|\bunit\b|\broom\b|\bfloor\b|#|\btel\b|phone|\bfax\b|www|http|@|\.com)")
MAX_TAGS = 5                                  # per refresh pass
DAILY = {"loop": 30, "agent": 20}             # per day, per path
RECHECK_H = 6                                 # a family with no evidence yet is looked at again after this
MAX_READS = 12
FRESH_SEC = 900                               # a board older than 15 min proves nothing
RESERVE_SEC = 120                             # a family's claim: long enough for the POST + GHL to show it
_STATE = "daycare_center_tag.json"            # {"checked": {contactId: ts}, "tagged": {contactId: {...}}}
_COUNTS = "daycare_center_tag_counts.json"    # {"day": "2026-11-12", "loop": n, "agent": n, "capNoted": bool}
_LOCK = threading.Lock()                      # one pass at a time; a slow GHL never piles passes up
_RLOCK = threading.Lock()                     # claims + counters (run() holds _LOCK while it takes them)
_FIELDS = {"at": 0.0, "ids": {}}              # center custom-field ids, cached an hour
_RESERVED = {}                                # contactId -> ts


def enabled() -> bool:
    return os.environ.get("FORGE_DAYCARE_AUTO_CENTER", "1") != "0"


def _norm(value) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).casefold()


def _nums(t) -> set:
    """Numbers of 2+ digits in normalized text, ordinals ("18th") dropped: that is a street name, not a number."""
    return set(re.findall(r"\d{2,}", re.sub(r"\b\d+(?:st|nd|rd|th)\b", " ", t)))


def _ambiguous(value) -> bool:
    """AMT in any spelling (full-width, punctuation, spacing), 1923, both centers, or Cecil B without 2318."""
    t = _norm(value)
    collapsed = re.sub(r"[^a-z0-9]+", "", t)
    nums = _nums(t)
    return (any(b in collapsed for b in _AMT_BITS) or {"921", "2318"} <= nums
            or ("cecil" in collapsed and "2318" not in nums))


def center_from_text(value) -> str | None:
    """The ONE ATOB site this field value names ("atob-one" | "atob-two"), else None. Strict on purpose:
    parents type these. Short; no phone / URL / suite / apartment words; every number of 2+ digits is
    exactly 921 or exactly 2318 (so "1456 N 18th St", "215-555-2318", "Suite 921" name nothing)."""
    t = _norm(value).strip()
    if not t or len(t) > MAX_VALUE or _ambiguous(t) or _VETO.search(t):
        return None
    nums = _nums(t)
    return "atob-one" if nums == {"921"} else "atob-two" if nums == {"2318"} else None


def _clean_name(name, cap=60) -> str:
    """A family name safe to put on a card or in a channel: no control / bidi characters, one line, clipped."""
    s = "".join(ch for ch in str(name or "") if unicodedata.category(ch) not in ("Cc", "Cf", "Zl", "Zp"))
    return " ".join(s.split())[:cap] or "a family"


def _test(name) -> bool:
    return str(name or "").strip().lower().startswith("zz")


def _board_ok(st, now) -> bool:
    return bool(st.get("fetchedAt")) and not st.get("error") and st.get("stageSource") == "live" \
        and now - st["fetchedAt"] / 1000 <= FRESH_SEC


def _boards(now=None):
    """-> (atob cards, amt contact ids), or None unless BOTH boards were read cleanly, live, in the last 15 min."""
    import daycare_pipeline
    now = now or time.time()
    atob, amt = daycare_pipeline._load(BOARD), daycare_pipeline._load("amt")
    if not _board_ok(atob, now) or not _board_ok(amt, now):
        return None
    return atob.get("cards") or [], {c.get("contactId") for c in amt.get("cards") or [] if c.get("contactId")}


def _amt_card(c) -> bool:
    return bool(c.get("amt")) or any("1923" in str(t) for t in (c.get("centers") or []) + [c.get("center") or ""])


def eligible(card, amt_ids) -> bool:
    """An untagged ATOB family: no loc- tag at all, no AMT mark, not on the AMT board, not a test family."""
    return bool(card.get("contactId")) and not card.get("centers") and not card.get("center") \
        and not _amt_card(card) and card["contactId"] not in amt_ids and not _test(card.get("name"))


def _contact_clean(contact) -> bool:
    """Right before the write: tags present and readable, no loc- tag, no AMT mark, not a test family."""
    tags = contact.get("tags")
    if not isinstance(tags, list):
        return False                          # an unreadable tag list is not an untagged family
    tags = [str(t).strip().lower() for t in tags]
    name = ((contact.get("firstName") or "") + " " + (contact.get("lastName") or "")).strip()
    return not any(t.startswith("loc-") or t == "entity-amt" or "1923" in t for t in tags) and not _test(name)


def _reserve(contact_id, now=None) -> bool:
    """Claim the right to auto-tag this family. False = another auto write claimed it in the last two minutes
    (an agent call, a second call in the same turn, the box loop). Without it two writers can both pass the
    live re-read before either lands."""
    now = now or time.time()
    with _RLOCK:
        for k in [k for k, t in _RESERVED.items() if now - t > RESERVE_SEC]:
            del _RESERVED[k]
        if str(contact_id) in _RESERVED:
            return False
        _RESERVED[str(contact_id)] = now
        return True


def _take(kind, now=None) -> bool:
    """One of today's auto-tag slots for this path ("loop" | "agent"). False = the daily cap is spent."""
    import slack_io
    now = now or time.time()
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    with _RLOCK:
        st = slack_io._read(_COUNTS)
        if st.get("day") != day:
            st = {"day": day}
        if (st.get(kind) or 0) >= DAILY[kind]:
            return False
        st[kind] = (st.get(kind) or 0) + 1
        slack_io._write(_COUNTS, st)
        return True


def _field_ids(client) -> dict:
    """{custom-field id: name} for the fields named exactly Preferred Location / Tour Location / SMS Center."""
    if _FIELDS["ids"] and time.time() - _FIELDS["at"] < 3600:
        return _FIELDS["ids"]
    data = client.get(f"/locations/{client.location_id}/customFields") or {}
    ids = {f["id"]: f.get("name", "") for f in data.get("customFields") or []
           if f.get("id") and str(f.get("name") or "").strip().lower() in FIELD_NAMES}
    _FIELDS.update(at=time.time(), ids=ids)
    return ids


def evidence(client, contact) -> tuple[str | None, str]:
    """-> (site, field name) when the contact's center fields name exactly one ATOB center; else (None, why).
    ANY ambiguous field (AMT / 1923 / two centers) vetoes the whole contact, whatever the other fields say."""
    ids = _field_ids(client)
    found = {}
    for item in contact.get("customFields") or contact.get("customField") or []:
        fid = item.get("id") or item.get("customFieldId")
        val = item.get("value") if item.get("value") is not None else item.get("field_value")
        if fid not in ids or val in (None, ""):
            continue
        if _ambiguous(val):
            return None, "a center field is ambiguous (AMT / 1923 / two centers)"
        site = center_from_text(val)
        if site:
            found[ids[fid]] = site
    sites = set(found.values())
    if len(sites) == 1:
        return sites.pop(), next(iter(found))
    return None, ("two centers named" if len(sites) > 1 else "no center named")


def _live_client():
    """The box's daycare GHL client (connector runs in this process), or None. Tests patch this."""
    try:
        import connector
        c = connector.DAYCARE_GHL
        return c if getattr(c, "configured", False) else None
    except Exception:  # noqa: BLE001
        return None


def safe_to_add(contact_id, tag) -> tuple[bool, str]:
    """The agents' gate (dash_live): may an agent ADD this ONE center tag to this contact without a card?
    Only the exact tag string of an ATOB site; only a family the boards prove is untagged ATOB (fresh, live,
    both read); only when the LIVE contact still has no loc- / AMT tag AND its own fields name exactly this
    center; only one claim per family per two minutes; only within today's agent cap. Any doubt, any error,
    no GHL client = a card."""
    if not enabled():
        return False, "automatic center tags are off"
    if tag not in TAG_SITE:
        return False, "not an A Touch of Blessings center tag"
    try:
        boards = _boards()
    except Exception:  # noqa: BLE001
        return False, "boards unreadable"
    if boards is None:
        return False, "a board is unread, errored, stale or not live"
    cards, amt_ids = boards
    mine = [c for c in cards if c.get("contactId") == str(contact_id or "")]
    if not mine:
        return False, "family is not on the ATOB board"
    if not all(eligible(c, amt_ids) for c in mine):
        return False, "family already has a center tag, an AMT mark, or is a test family"
    client = _live_client()
    if client is None:
        return False, "GHL is not reachable for the live check"
    try:
        contact = (client.get(f"/contacts/{contact_id}") or {}).get("contact") or {}
        if not contact or not _contact_clean(contact):
            return False, "the live contact already has a center tag, an AMT mark, or is a test family"
        site, why = evidence(client, contact)
    except Exception:  # noqa: BLE001
        return False, "live GHL read failed"
    if site != TAG_SITE[tag]:
        return False, "the family's own fields do not name this center"
    if not _reserve(contact_id):
        return False, "another center tag for this family is already in flight"
    if not _take("agent"):
        return False, "today's automatic center-tag cap for agents is spent"
    return True, ""


def run(cards, client, now=None, force=False) -> int:
    """One pass after a GHL read of the ATOB board. -> tags added. Never raises, never piles up."""
    if not _LOCK.acquire(blocking=False):
        return 0                              # a slow GHL: the previous pass is still running
    try:
        if not enabled() or (os.environ.get("FORGE_MARCUS") != "1" and not force):
            return 0
        if client is None or not getattr(client, "configured", False):
            return 0
        import slack_io
        now = now or time.time()
        boards = _boards(now)
        if boards is None:
            return 0
        _, amt_ids = boards
        added = reads = 0
        st = slack_io._read(_STATE)
        checked, tagged = st.setdefault("checked", {}), st.setdefault("tagged", {})
        for card in cards:
            if added >= MAX_TAGS or reads >= MAX_READS:
                break
            cid = card.get("contactId")
            if not eligible(card, amt_ids) or now - (checked.get(cid) or 0) < RECHECK_H * 3600:
                continue
            reads += 1
            checked[cid] = now
            contact = (client.get(f"/contacts/{cid}") or {}).get("contact") or {}
            if not contact or not _contact_clean(contact):
                continue
            site, field = evidence(client, contact)
            if not site or not _reserve(cid, now):
                continue
            if not _take("loop", now):
                _cap_note(now)
                break
            import daycare_ghl
            res = daycare_ghl.tag_contact(client, cid, add=[SITE_TAG[site]])
            if not res.get("ok"):
                print(f"[center_tag] tag failed for {cid[:6]}: {res.get('error')}", flush=True)
                continue
            added += 1
            tagged[cid] = {"site": site, "field": field, "ts": int(now)}
            _announce(card, site, field)
        st["checked"] = {k: v for k, v in checked.items() if now - v < 30 * 86400}
        st["tagged"] = {k: v for k, v in tagged.items() if now - (v.get("ts") or 0) < 90 * 86400}
        slack_io._write(_STATE, st)
        return added
    except Exception as e:  # noqa: BLE001 — a tagging pass never blocks the pipeline lane
        print(f"[center_tag] run failed: {type(e).__name__}", flush=True)
        return 0
    finally:
        _LOCK.release()


def _cap_note(now) -> None:
    """The daily cap is spent: say so once a day in the daycare main chat."""
    try:
        import slack_io
        with _RLOCK:
            st = slack_io._read(_COUNTS)
            if st.get("capNoted"):
                return
            st["capNoted"] = True
            slack_io._write(_COUNTS, st)
        ch = slack_io.chat_for("daycare")
        if ch:
            slack_io.send(f"⚠️ Automatic center tags paused for today ({DAILY['loop']} tagged). A burst like this "
                          "usually means an import: check that the families' center answers look right.",
                          channel=ch, dedupe_key=f"centertag-cap:{time.strftime('%Y-%m-%d', time.gmtime(now))}")
    except Exception:  # noqa: BLE001
        pass


def _announce(card, site, field) -> None:
    """One line in the site's Slack channel + the action log. Best effort."""
    tag = SITE_TAG[site]
    try:
        import action_log
        action_log.record("solomon", "auto_center_tag", business="daycare", trigger="auto",
                          ref=f"{card.get('contactId')} +{tag}", result=f"from {field}", approval_required=False)
    except Exception:  # noqa: BLE001
        pass
    try:
        import html
        import slack_io
        ch = slack_io.topic_channel(f"daycare-{site}") or slack_io.chat_for("daycare")
        if ch:
            slack_io.send(f"🏷 Tagged <b>{html.escape(_clean_name(card.get('name')), quote=False)}</b> → "
                          f"{CENTER_LABEL[tag]} (from their {html.escape(field, quote=False)})", channel=ch,
                          dedupe_key=f"centertag:{card.get('contactId')}:{tag}")
    except Exception:  # noqa: BLE001
        pass
