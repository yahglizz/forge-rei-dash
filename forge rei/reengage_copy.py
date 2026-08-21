#!/usr/bin/env python3
"""Stage D — re-engage COPY for the 3,023-lead clean list. DRAFT ONLY, nothing sends.

Two outputs, because the list splits two ways:

  1. BULK (never_replied 2,823 + no_outbound_yet 11) -> reengage_templates.md
     GHL bulk-SMS templates with `{{contact.first_name}}` merge fields. 3 variants per
     segment so the operator can pick AND so 2,823 identical bodies don't hit carrier
     duplicate-content filters. Pure text, no API calls.

  2. WARM (active_pending_us 109 + replied_then_cold 80 = 189) -> reengage_drafts_warm.csv
     Individually drafted through the REAL production engine
     (marcus_engine.MarcusEngine._ai_draft) so voice + safety are byte-identical to live.
     Harness is reused wholesale from `reengage_draft.py` — its GET-only `ghl_get`, its
     `ghl_post_canary` (raises if anything ever tries to write), its auth. No new send
     path exists here and none may be added.

Every message carries the house opt-out footer verbatim from our real outbound
(measured: 128 occurrences in the on-disk thread dumps).

Run:
    python3 reengage_copy.py --selfcheck   # pure logic, 0 API calls, 0 Claude calls
    python3 reengage_copy.py --templates   # write the .md only, 0 API calls
    python3 reengage_copy.py               # templates + the 189 warm drafts (Claude + GHL GET)
"""
import csv
import math
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

EXPORT = os.path.join(HERE, "marcus_state", "leads_export")
OUT_MD = os.path.join(EXPORT, "reengage_templates.md")
OUT_CSV = os.path.join(EXPORT, "reengage_drafts_warm.csv")

WARM_SEGMENTS = ["active_pending_us", "replied_then_cold"]
BULK_SEGMENTS = ["never_replied", "no_outbound_yet"]

# ---------------------------------------------------------------------------
# The house opt-out footer. NOT invented here — this is what our real outbound
# already says, lifted verbatim from the thread dumps on disk:
#   128x "If you'd rather not receive messages reply STOPALL contact, have a blessed day"
# (122 of those with a curly apostrophe U+2019, 6 with a straight one). We use the
# STRAIGHT apostrophe: U+2019 is not in the GSM-7 alphabet and would silently force the
# whole message to UCS-2, halving the per-segment budget across 2,823 sends.
# `closing-plays.md` calls this his "blessing sign-off" and says always include it on a
# cold message. Do not reword it.
# ---------------------------------------------------------------------------
FOOTER = "If you'd rather not receive messages reply STOPALL contact, have a blessed day"

SAMPLE_NAME = "Michael"  # 7 chars — the most common first name in the never_replied file


# ---------------------------------------------------------------------------
# BULK TEMPLATES
# ---------------------------------------------------------------------------
# Voice rules from vault Skills/wholesale-seller-texter.md + seller-reply-playbook.md:
# lowercase-ish, warm, patient, no pressure, no em-dash/semicolon/exclamation, one ask,
# drive to a call, and NEVER a price/offer/number. Fresh angle, never "just following up",
# and nothing that implies we've been in touch since (these people last heard from us
# weeks-to-months ago).
TEMPLATES = {
    "never_replied": [
        ("NR-A", "clean restart — name the gap, no guilt, one ask",
         "hi {{contact.first_name}}, this is Yahjair with A Touch of Blessings Home Buyers. "
         "we reached out about your property a while back and i dont wanna be a bug. "
         "if your still holding it im still buying as is for cash, worth a quick call? "
         + FOOTER),
        ("NR-B", "question-first — cheapest possible reply, one word gets a thread going",
         "hi {{contact.first_name}}, Yahjair here with A Touch of Blessings Home Buyers. "
         "its been a while since we reached out, do you still own the property? "
         "if you do id love 5 min on the phone to see if we can help. "
         + FOOTER),
        ("NR-C", "permission to say no + reassurance stack",
         "hey {{contact.first_name}}, Yahjair with A Touch of Blessings Home Buyers. "
         "i reached out about your property before and never heard back, thats 100% ok. "
         "still buying as is, 0 fees, you pick the closing date. open to a quick call? "
         + FOOTER),
    ],
    "no_outbound_yet": [
        ("NO-A", "straight cold open — the closing-plays first-touch shape",
         "hi {{contact.first_name}}, this is Yahjair with A Touch of Blessings Home Buyers. "
         "im reaching out about your property, are you open to a quick conversation about it? "
         + FOOTER),
        ("NO-B", "what we do, then the ask",
         "hi {{contact.first_name}}, Yahjair here with A Touch of Blessings Home Buyers. "
         "we buy houses as is for cash in your area. do you still own your property and "
         "would you be open to talking about it? "
         + FOOTER),
        ("NO-C", "reassurance stack first, low pressure close",
         "hi {{contact.first_name}}, this is Yahjair with A Touch of Blessings Home Buyers. "
         "we buy as is, cash, 0 fees and you pick the closing date. is your property "
         "something you'd ever consider selling? no rush at all. "
         + FOOTER),
    ],
}


# ---------------------------------------------------------------------------
# SMS segment math (GSM-7 160/153, UCS-2 70/67)
# ---------------------------------------------------------------------------
_GSM7_BASIC = (
    "@£$¥èéùìòÇ\nØø\rÅå"
    "Δ_ΦΓΛΩΠΨΣΘΞÆæßÉ"
    " !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§"
    "¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
_GSM7_EXT = "^{}\\[~]|€"  # each of these costs TWO septets


def sms_segments(text):
    """Return (encoding, units, segments) the carrier will actually bill.

    An emoji or a curly quote is not cosmetic — a single one flips the whole message to
    UCS-2 and cuts the per-segment budget from 153 chars to 67, i.e. roughly doubles the
    per-message cost across the entire blast."""
    units = 0
    gsm = True
    for ch in text:
        if ch in _GSM7_BASIC:
            units += 1
        elif ch in _GSM7_EXT:
            units += 2
        else:
            gsm = False
            break
    if gsm:
        return "GSM-7", units, (1 if units <= 160 else math.ceil(units / 153))
    units = sum(2 if ord(ch) > 0xFFFF else 1 for ch in text)  # UTF-16 code units
    return "UCS-2", units, (1 if units <= 70 else math.ceil(units / 67))


_MERGE_RE = re.compile(r"\{\{\s*contact\.[a-z_]+\s*\}\}")


def rendered(text, name=SAMPLE_NAME):
    """What the carrier actually sees after GHL expands the merge fields."""
    return _MERGE_RE.sub(name, text)


# ---------------------------------------------------------------------------
# Grounding: does this draft reference something the seller ACTUALLY said?
# ---------------------------------------------------------------------------
_STOP = set("""a an and are as at be been but by can cant do dont for from get got had has have
he her him his how i if im in is it its just know like ll me my no not now of ok on one or our
out re she so that the their them then there they this to up us ve was we were what when where
which who will with would you your youre yours thanks thank hi hey hello please sorry yes yeah
""".split())


def _tokens(s):
    return {w for w in re.findall(r"[a-z0-9']{4,}", (s or "").lower()) if w not in _STOP}


def grounding(draft, seller_text):
    """Distinctive-word overlap between our draft and the seller's own words.
    Deliberately dumb: it proves the draft echoes real thread text rather than a canned
    line. It is evidence, not a score — a human still reads the pair side by side."""
    shared = _tokens(draft) & _tokens(seller_text)
    return sorted(shared)


# ---------------------------------------------------------------------------
# Templates -> markdown
# ---------------------------------------------------------------------------
SEG_ROWS = {"never_replied": 2823, "no_outbound_yet": 11,
            "active_pending_us": 109, "replied_then_cold": 80}
# Measured off the actual segment CSVs, not assumed — a merge field's length is variable
# and that is the only thing that can move a template across a segment boundary at send
# time. 0 blank first names in either bulk list; longest is 12 chars.
MAX_FIRST_NAME = {"never_replied": 12, "no_outbound_yet": 7}


def write_templates():
    L = []
    L.append("# Re-engage SMS templates — bulk segments (Stage D)\n")
    L.append("**DRAFT ONLY. Nothing here has been sent.** Generated by `reengage_copy.py`.\n")
    L.append("Voice source: vault `Skills/seller-reply-playbook.md`, "
             "`Skills/wholesale-seller-texter.md`, `Skills/closing-plays.md`.\n")
    L.append("**No template contains a price, offer, range, or ballpark.** The only job of "
             "every message is to start a conversation that becomes a phone call. Verified in "
             "code against the live gates (`marcus_engine.MarcusEngine._PRICE_RE` and "
             "`sms_guard._quotes_price_or_offer`) — run `python3 reengage_copy.py --selfcheck`.\n")
    L.append("## Merge field\n")
    L.append("GHL expands `{{contact.first_name}}` at send time. Confirmed in-repo against a "
             "live GHL location (`forge-solomon/skills/solomon-systems-craft.md`). A contact "
             "with a blank first name renders an EMPTY string, not a fallback.\n")
    L.append("Measured on the two bulk CSVs: **0 blank names, longest first name 12 "
             "characters.** One caveat for Stage E — the audit CSV's `name` column comes from "
             "GHL's `contactName`, while the merge tag reads the separate `firstName` field. "
             "They are normally the same first token but are not the same field, so confirm "
             "`firstName` is populated on the smart list before sending, or set a default "
             "value on the field in GHL.\n")
    L.append("## Opt-out footer — verbatim, do not reword\n")
    L.append(f"> {FOOTER}\n")
    L.append("This is our own existing outbound language (128 occurrences in the on-disk "
             "thread dumps), not new wording. One deliberate change: the straight apostrophe "
             "`'` replaces the curly `’` used in 122 of them. `’` is **not** in the "
             "GSM-7 alphabet, so it silently forces the whole message to UCS-2 and cuts the "
             "per-segment budget from 153 characters to 67 — across 2,823 sends that is a "
             "pure billing loss for an invisible character.\n")
    L.append("## Why 3 variants per segment\n")
    L.append("Deliverability, not indecision. Carriers score high-volume A2P traffic partly on "
             "duplicate content; 2,823 byte-identical bodies from one number is the exact "
             "signature of a blast filter. Rotating three bodies (roughly a third each, "
             "assigned at import time as a `variant` column) keeps any single body under ~950 "
             "sends. Pick one as the favorite if you want, but send at least two.\n")
    L.append("## Segment counts\n")
    L.append("| segment | leads | how they got here |")
    L.append("|---|---|---|")
    L.append("| `never_replied` | 2,823 | we texted, they never responded |")
    L.append("| `no_outbound_yet` | 11 | in the CRM, never contacted |")
    L.append("")

    for seg in BULK_SEGMENTS:
        L.append(f"## `{seg}` — {SEG_ROWS[seg]:,} leads\n")
        if seg == "never_replied":
            L.append("Angle rule: **fresh open, never \"just following up\".** They never "
                     "replied, so there is no thread to reference and nothing to \"circle "
                     "back\" on. Each variant names the gap honestly once, gives them an easy "
                     "out, and asks for one thing. Nothing implies we have been in contact "
                     "since — these people last heard from us weeks-to-months ago.\n")
        else:
            L.append("Angle rule: **treat as net-new outreach.** They have never received a "
                     "message from us, so nothing may reference a prior conversation. This is "
                     "the `closing-plays.md` first-touch shape.\n")
        for vid, angle, text in TEMPLATES[seg]:
            r = rendered(text)
            enc, units, segs = sms_segments(r)
            enc_t, units_t, _ = sms_segments(text)
            L.append(f"### {vid} — {angle}\n")
            L.append("```")
            L.append(text)
            L.append("```")
            L.append(f"- **Rendered** (first name = `{SAMPLE_NAME}`, 7 chars): "
                     f"**{len(r)} chars · {enc} · {units} units · {segs} SMS segment"
                     f"{'s' if segs != 1 else ''}**")
            L.append(f"- Raw template with the merge tag unexpanded: {len(text)} chars "
                     f"({enc_t}, {units_t} units)")
            head = max(0, (160 if segs == 1 else 153 * segs) - units)
            L.append(f"- Headroom before it spills into another segment: **{head} "
                     f"chars** — i.e. safe up to a {7 + head}-character first name. "
                     f"Longest first name in the whole {seg} list is "
                     f"{MAX_FIRST_NAME[seg]} chars, so **every contact on this list stays "
                     f"at {segs} segments**.")
            if enc != "GSM-7":
                L.append("- **WARNING: not GSM-7.** A non-GSM character forced UCS-2 — "
                         "per-segment budget drops 153 -> 67. Fix before sending.")
            L.append(f"- Cost at {SEG_ROWS[seg]:,} sends if this variant carried the whole "
                     f"segment: **{SEG_ROWS[seg] * segs:,} billed SMS segments**")
            L.append("")

    L.append("## Segment-boundary notes\n")
    L.append("- GSM-7: 160 chars in a single message, 153 per part once it splits "
             "(7 chars go to the concatenation header). UCS-2: 70 / 67.\n")
    L.append("- **Every variant here is exactly 2 segments, for every contact on the list.** "
             f"The footer alone is {len(FOOTER)} chars, so a 1-segment message would leave "
             f"~{160 - len(FOOTER) - 1} chars for the entire pitch — not enough to introduce "
             "the business, name the gap, and ask for a call. 2 segments is a deliberate "
             "trade, not an overrun. Total bulk cost: **5,646 + 22 = 5,668 billed segments** "
             "whichever variants you pick.\n")
    L.append("- **One emoji triples the bill.** Any emoji, curly quote, or en/em dash added "
             "later flips the message to UCS-2 (153 -> 67 per part): a ~300-char body jumps "
             "from 2 segments to 5. On `never_replied` alone that is 5,646 -> 14,115 billed "
             "segments for one invisible character. Do not paste this copy through a word "
             "processor or a chat app that auto-curls quotes.\n")
    L.append("- Rewriting a variant? Re-run `python3 reengage_copy.py --selfcheck` — it "
             "re-derives every count and hard-fails on a non-GSM character, a price shape, a "
             "missing footer, or a missing merge field.\n")

    L.append("## Not covered here\n")
    L.append("- `active_pending_us` (109) and `replied_then_cold` (80) get **no template**. "
             "They are individually drafted in `reengage_drafts_warm.csv` — they are the "
             "warmest leads in the business and a merge-field blast wastes them.\n")
    L.append("- Property address is deliberately NOT merged in. `{{contact.address1}}` "
             "renders empty on any contact missing it and produces a broken sentence at "
             "scale. If Stage E confirms address coverage is 100% on the send list, adding "
             "it is a real lift — but it must be verified, not assumed.\n")

    with open(OUT_MD, "w") as f:
        f.write("\n".join(L) + "\n")
    return OUT_MD


# ---------------------------------------------------------------------------
# WARM drafts — production engine, GET-only, canary POST
# ---------------------------------------------------------------------------
HINTS = {
    "active_pending_us": (
        "WE dropped this one. they replied {age} and we never answered. own that gap "
        "plainly in one short beat, no excuses and no story, then pick back up on exactly "
        "what they said and ask for a quick call."),
    "replied_then_cold": (
        "this thread went quiet {age} after OUR last text. reopen on exactly what they said "
        "back then like your picking up with someone you already talked to, not a blast. "
        "acknowledge its been a while."),
}


def _age_phrase(iso):
    """Plain-English staleness. These people last heard from us weeks-to-months ago and no
    draft may imply otherwise."""
    try:
        from datetime import datetime, timezone
        then = datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        days = (datetime.now(timezone.utc) - then).days
    except Exception:
        return "a while back"
    if days < 21:
        return f"about {max(1, days // 7)} weeks ago"
    if days < 60:
        return f"about {round(days / 7)} weeks ago"
    return f"about {max(2, round(days / 30))} months ago"


OUT_FIELDS = ["contact_id", "name", "phone", "segment", "seller_last_message",
              "draft_text", "grounded_in",
              "state", "city", "classification", "draft_source", "draft_status",
              "grounded_words", "chars", "sms_segments", "last_message_date_iso"]


def draft_warm():
    import reengage_draft as rd          # the harness: GET-only ghl_get + ghl_post canary
    import marcus_engine

    engine = marcus_engine.MarcusEngine(rd.ghl_get, rd.ghl_post_canary, rd.LOCATION_ID)
    rows = []
    for seg in WARM_SEGMENTS:
        path = os.path.join(EXPORT, f"all_leads_{seg}.csv")
        with open(path, newline="") as f:
            for r in csv.DictReader(f):
                r["_segment"] = seg
                rows.append(r)
    print(f"[reengage_copy] {len(rows)} warm leads to draft individually")

    out, ok, blocked, errored, ungrounded = [], 0, 0, 0, []
    t0 = time.time()
    for i, row in enumerate(rows, 1):
        seg = row["_segment"]
        try:
            conv_id = rd.most_recent_conversation_id(row["contact_id"])
            body, history = engine._recent_thread(
                conv_id, fallback=row["last_inbound_snippet"])
            first = (row["name"] or "").split()[0] if (row["name"] or "").strip() else "there"

            cls = marcus_engine.classify(body)
            # identical override order to marcus_engine._make_proposal
            if cls != "DNC" and (cls == "NRN" or marcus_engine._is_soft_no(body)):
                cls = "NRN"
            if marcus_engine._is_denial(body, row["name"] or ""):
                cls = "WRONG_NUMBER"

            if cls == "WRONG_NUMBER":
                text, source, status = marcus_engine.CANNED_WRONG_NUMBER_REPLY, \
                    "canned_wrong_number", "ok"
            elif cls == "NRN":
                text, source, status = marcus_engine.CANNED_NRN_REPLY, "canned_nrn", "ok"
            else:
                hint = HINTS[seg].format(age=_age_phrase(row["last_message_date_iso"]))
                text, source = engine._ai_draft(first, cls, body, history, hint=hint)
                status = "blocked" if source == "blocked" else "ok"
                if status == "blocked":
                    text = f"[BLOCKED: {engine.last_error}]"

            shared = grounding(text, body) if status == "ok" else []
            if status == "ok":
                text = f"{text} {FOOTER}" if not text.endswith(" ") else text + FOOTER
                ok += 1
            else:
                blocked += 1
            if status == "ok" and not shared and not source.startswith("canned"):
                ungrounded.append((row["contact_id"], row["name"], body[:90]))

            enc, units, segs = sms_segments(text)
            out.append({
                "contact_id": row["contact_id"], "name": row["name"], "phone": row["phone"],
                "segment": seg, "seller_last_message": body,
                "draft_text": text,
                "grounded_in": body if shared or source.startswith("canned") else "",
                "state": row["state"], "city": row["city"], "classification": cls,
                "draft_source": source, "draft_status": status,
                "grounded_words": " ".join(shared), "chars": len(text),
                "sms_segments": segs,
                "last_message_date_iso": row["last_message_date_iso"],
            })
        except Exception as e:            # one bad contact must not kill the run
            errored += 1
            out.append({k: "" for k in OUT_FIELDS} | {
                "contact_id": row.get("contact_id", ""), "name": row.get("name", ""),
                "phone": row.get("phone", ""), "segment": seg,
                "draft_text": str(e), "draft_status": "error"})
        if i % 25 == 0:
            print(f"[reengage_copy] {i}/{len(rows)} (ok={ok} blocked={blocked} "
                  f"err={errored}, {rd.api_call_count} GHL GETs)")

    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        w.writeheader()
        w.writerows(out)

    print(f"\n===== WARM SUMMARY =====\n{len(out)} drafted  ok={ok} blocked={blocked} "
          f"error={errored}  {time.time() - t0:.0f}s  {rd.api_call_count} GHL GETs (0 writes)")
    print(f"Could not ground in real seller text: {len(ungrounded)}")
    for cid, nm, b in ungrounded:
        print(f"  {cid} {nm!r} <- {b!r}")
    print(f"Output: {OUT_CSV}")
    return out


# ---------------------------------------------------------------------------
def demo():
    """Self-check: pure logic, no network, no Claude. Exit 1 on failure."""
    # 1. segment math
    assert sms_segments("a" * 160) == ("GSM-7", 160, 1)
    assert sms_segments("a" * 161) == ("GSM-7", 161, 2)
    assert sms_segments("a" * 306) == ("GSM-7", 306, 2)
    assert sms_segments("a" * 307)[2] == 3
    assert sms_segments("[")[1] == 2, "GSM-7 extension chars cost 2 septets"
    assert sms_segments("hi \U0001f600")[0] == "UCS-2", "one emoji must force UCS-2"
    assert sms_segments("a" * 70)[2] == 1 and sms_segments("hi’")[0] == "UCS-2", \
        "curly apostrophe is NOT GSM-7 — it silently doubles the bill"
    assert sms_segments("x" * 71 + "’")[2] == 2

    # 2. the footer itself must be GSM-7 clean, or every single send pays double
    assert sms_segments(FOOTER)[0] == "GSM-7"
    assert "’" not in FOOTER

    # 3. NO PRICE ANYWHERE — checked against the LIVE production gates, not a local regex
    import marcus_engine
    import sms_guard
    for seg, variants in TEMPLATES.items():
        for vid, _angle, text in variants:
            r = rendered(text)
            assert not marcus_engine.MarcusEngine._PRICE_RE.search(r), \
                f"{vid} leaked a price shape"
            assert not sms_guard._quotes_price_or_offer(r), f"{vid} tripped the send gate"
            assert not re.search(r"\$|\boffer\b|\bballpark\b", r, re.I), f"{vid} price word"
            assert FOOTER in text, f"{vid} is missing the opt-out footer"
            assert _MERGE_RE.search(text), f"{vid} has no merge field"
            assert sms_segments(r)[0] == "GSM-7", f"{vid} is not GSM-7"
            # voice guard: no em-dash / semicolon / exclamation (wholesale-seller-texter)
            assert not re.search(r"[—–;!]", text), f"{vid} broke the voice rules"
    # a control: the gates DO fire on a price, so the asserts above mean something
    assert marcus_engine.MarcusEngine._PRICE_RE.search("i can do $40k")
    assert sms_guard._quotes_price_or_offer("we can offer 40,000")

    # 4. grounding overlap actually discriminates
    assert "roof" in grounding("hows the roof holding up", "the roof leaks bad")
    assert grounding("hey whats a good time for a call", "the roof leaks bad") == []
    assert grounding("thanks the you", "thanks the you") == [], "stopwords are not grounding"

    # 5. staleness phrasing never claims recent contact
    assert "weeks" in _age_phrase("2026-08-10T00:00:00+00:00")
    assert "months" in _age_phrase("2026-04-01T00:00:00+00:00")
    assert _age_phrase("garbage") == "a while back"

    # 6. merge rendering
    assert rendered("hi {{contact.first_name}}, ok") == "hi Michael, ok"
    print("reengage_copy selfcheck: ALL PASS")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        demo()
    elif "--templates" in sys.argv:
        demo()
        print("Wrote", write_templates())
    else:
        demo()
        print("Wrote", write_templates())
        draft_warm()
