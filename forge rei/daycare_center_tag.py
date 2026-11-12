"""daycare_center_tag.py — put the right A Touch of Blessings center tag on a family, by itself.

Owner decision 2026-11-12: "we don't need approval for tagging someone; always auto tag properly."
A family on the ATOB board with NO `loc-` tag gets `loc-921-n-18th` or `loc-2318-cecil-b-moore` when the
parent's own form fields name exactly one of those centers. No Claude call, no tap. Two entry points:

  run(cards, client)         the box loop: daycare_pipeline.refresh calls it after every GHL read.
                             Reads each untagged family's "Preferred Location" / "Tour Location" / "SMS
                             Center" custom fields (fields whose NAME says center/location/site/campus),
                             tags when exactly one center is named, posts one line in that site's Slack
                             channel, logs it (action_log trigger "auto_center_tag").
  safe_to_add(cid, tag)      the agents' gate: dash_live lets an agent's `ghl/tag` write that adds ONE
                             center tag to a provably-untagged ATOB family run without a card.

What never happens (the October 2026 reason center tags needed a tap was keeping the two legal entities
apart): never loc-1923 or any AMT mark (`entity-amt`, a 1923 tag, the contact on the AMT board, text that
names AMT / 1923 / Mother's Touch); never when the family already has ANY `loc-` tag (add-only, never a
move); never two centers named; never a ZZ test family; never when either board has never been read.
Intake / login tags (family-contact-form, form-type-*, confirm tags) stay owner-tapped: they start
enrollment and PIN texts. Kill: FORGE_DAYCARE_AUTO_CENTER=0. Box only (FORGE_MARCUS=1).
"""
from __future__ import annotations

import os
import re
import threading
import time

BOARD = "enrollment"                          # ATOB. Never "amt".
SITE_TAG = {"atob-one": "loc-921-n-18th", "atob-two": "loc-2318-cecil-b-moore"}
TAG_SITE = {v: k for k, v in SITE_TAG.items()}
CENTER_LABEL = {"loc-921-n-18th": "921 N 18th", "loc-2318-cecil-b-moore": "2318 Cecil B. Moore"}
FIELD_NAME = re.compile(r"center|location|site|campus", re.I)
_SITE_RX = (("atob-one", re.compile(r"\b921\b|\bn\.?\s*18th\b|\bnorth\s+18th\b", re.I)),
            ("atob-two", re.compile(r"\b2318\b", re.I)))
_AMT_RX = re.compile(r"\bAMT\b|\b1923\b|Mother.{0,3}s Touch|entity-amt", re.I)
MAX_READS, MAX_TAGS = 12, 10                  # per refresh: a bulk GHL import can't flood the lane
RECHECK_H = 6                                 # a family with no evidence yet is looked at again after this
_STATE = "daycare_center_tag.json"            # {"checked": {contactId: ts}, "tagged": {contactId: {...}}}
_LOCK = threading.Lock()
_FIELDS = {"at": 0.0, "ids": {}}              # center-ish custom-field ids, cached an hour


def enabled() -> bool:
    return os.environ.get("FORGE_DAYCARE_AUTO_CENTER", "1") != "0"


def center_from_text(*values) -> str | None:
    """The ONE ATOB site these field values name ("atob-one" | "atob-two"), else None. Any AMT / 1923
    mention, two sites, or none = None (ambiguous is never tagged)."""
    text = " ".join(str(v or "") for v in values)
    if not text.strip() or _AMT_RX.search(text):
        return None
    hits = {site for site, rx in _SITE_RX if rx.search(text)}
    return hits.pop() if len(hits) == 1 else None


def _test(name) -> bool:
    return str(name or "").strip().lower().startswith("zz")


def _boards():
    """-> (atob cards, amt contact ids) or None when either board was never read (cannot prove anything)."""
    import daycare_pipeline
    atob, amt = daycare_pipeline._load(BOARD), daycare_pipeline._load("amt")
    if not atob.get("fetchedAt") or not amt.get("fetchedAt"):
        return None
    return atob.get("cards") or [], {c.get("contactId") for c in amt.get("cards") or [] if c.get("contactId")}


def _amt_card(c) -> bool:
    return bool(c.get("amt")) or any("1923" in str(t) for t in (c.get("centers") or []) + [c.get("center") or ""])


def eligible(card, amt_ids) -> bool:
    """An untagged ATOB family: no loc- tag at all, no AMT mark, not on the AMT board, not a test family."""
    return bool(card.get("contactId")) and not card.get("centers") and not card.get("center") \
        and not _amt_card(card) and card["contactId"] not in amt_ids and not _test(card.get("name"))


def safe_to_add(contact_id, tag) -> tuple[bool, str]:
    """The agents' gate (dash_live): may an agent ADD this one center tag to this contact without a card?
    Only a center tag of an ATOB site, only to a family the boards prove is untagged ATOB."""
    if str(tag or "").strip().lower() not in TAG_SITE:
        return False, "not an A Touch of Blessings center tag"
    try:
        boards = _boards()
    except Exception:  # noqa: BLE001
        return False, "boards unreadable"
    if boards is None:
        return False, "a board has never been read"
    cards, amt_ids = boards
    mine = [c for c in cards if c.get("contactId") == str(contact_id or "")]
    if not mine:
        return False, "family is not on the ATOB board"
    if not all(eligible(c, amt_ids) for c in mine):
        return False, "family already has a center tag, an AMT mark, or is a test family"
    return True, ""


def _field_ids(client) -> dict:
    """{custom-field id: name} for fields whose name says center/location/site/campus (cached 1 h)."""
    if _FIELDS["ids"] and time.time() - _FIELDS["at"] < 3600:
        return _FIELDS["ids"]
    data = client.get(f"/locations/{client.location_id}/customFields") or {}
    ids = {f["id"]: f.get("name", "") for f in data.get("customFields") or []
           if f.get("id") and FIELD_NAME.search(f.get("name") or "")}
    _FIELDS.update(at=time.time(), ids=ids)
    return ids


def evidence(client, contact) -> tuple[str | None, str]:
    """-> (site, field name) from the contact's center-ish custom fields; (None, why) when none or conflicting."""
    ids = _field_ids(client)
    found = {}
    for item in contact.get("customFields") or contact.get("customField") or []:
        fid = item.get("id") or item.get("customFieldId")
        val = item.get("value") if item.get("value") is not None else item.get("field_value")
        if fid in ids and val not in (None, ""):
            if _AMT_RX.search(str(val)):
                return None, "names AMT / 1923"
            site = center_from_text(val)
            if site:
                found[ids[fid]] = site
    sites = set(found.values())
    if len(sites) == 1:
        return sites.pop(), next(iter(found))
    return None, ("two centers named" if len(sites) > 1 else "no center named")


def _contact_clean(contact) -> bool:
    """Right before the write: still no loc- tag, no AMT mark, not a test family."""
    tags = [str(t).strip().lower() for t in contact.get("tags") or []]
    name = ((contact.get("firstName") or "") + " " + (contact.get("lastName") or "")).strip()
    return not any(t.startswith("loc-") or t == "entity-amt" or "1923" in t for t in tags) and not _test(name)


def run(cards, client, now=None, force=False) -> int:
    """One pass after a GHL read of the ATOB board. -> tags added. Never raises."""
    try:
        if not enabled() or (os.environ.get("FORGE_MARCUS") != "1" and not force):
            return 0
        if client is None or not getattr(client, "configured", False):
            return 0
        import slack_io
        boards = _boards()
        if boards is None:
            return 0
        _, amt_ids = boards
        now = now or time.time()
        added = reads = 0
        with _LOCK:
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
                if not site:
                    continue
                import daycare_ghl
                res = daycare_ghl.tag_contact(client, cid, add=[SITE_TAG[site]])
                if not res.get("ok"):
                    print(f"[center_tag] tag failed for {cid[:6]}: {res.get('error')}", flush=True)
                    continue
                added += 1
                tagged[cid] = {"site": site, "field": field, "ts": int(now)}
                _announce(card, site, field)
            st["checked"] = {k: v for k, v in checked.items() if now - v < 30 * 86400}
            slack_io._write(_STATE, st)
        return added
    except Exception as e:  # noqa: BLE001 — a tagging pass never blocks the pipeline lane
        print(f"[center_tag] run failed: {type(e).__name__}", flush=True)
        return 0


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
            slack_io.send(f"🏷 Tagged <b>{html.escape(str(card.get('name') or 'a family'), quote=False)}</b> → "
                          f"{CENTER_LABEL[tag]} (from their {html.escape(field, quote=False)})", channel=ch,
                          dedupe_key=f"centertag:{card.get('contactId')}:{tag}")
    except Exception:  # noqa: BLE001
        pass
