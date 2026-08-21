#!/usr/bin/env python3
"""FULL wholesale GHL audit — ALL contacts, EVERY state (blank included), READ-ONLY.

Stage A of WHOLESALE_REENGAGE_PLAN.md. Thin wrapper over leads_audit.py: reuses its
env loading, retrying ghl_get, cursor pagination, thread pull, and classifier. Four
deltas (see WHAT CHANGED below).

GET requests only. No sends, no tag writes, no pipeline moves. Safe to re-run.

Run:
    python3 full_leads_audit.py                # full sweep (all 7,363)
    AUDIT_LIMIT=50 python3 full_leads_audit.py # 50-contact smoke slice -> slice50_*.csv
    python3 full_leads_audit.py --selfcheck    # pure-logic asserts, zero API calls

WHAT CHANGED vs leads_audit.py
------------------------------
1. No TARGET_STATE filter and no blank-state drop. Every contact is audited; the raw
   `state` value stays in the output column for downstream segmentation.
2. `soft_no` is split. leads_audit collapsed 19 phrases into one bucket and threw it
   all away as dead_end. Six of those phrases are timing ("not right now", "maybe
   later"); thirteen are refusals ("not interested", "not for sale"). Timing ->
   `soft_no_revisit` (KEEP). Refusal -> stays `dead_end` / `soft_no_refusal`.
   Flip SOFT_NO_REFUSAL_IS_KEEP=True to get the literal "all soft_no is KEEP" behavior.
3. THE COMPLIANCE GATE (plan section 4). Contact-level opt-out is read BEFORE any
   thread work: `dnd` boolean, `dndSettings.SMS`, and DNC/opt-out tags. Any hit ->
   status_category="excluded", exclude_reason="ghl_dnd". Verified live 2026-08-21:
   dnd bool is near-useless (4 of 7,363) but dndSettings.SMS fires on 2,957 and 34
   contacts carry a `dnc` tag with NO dnd flag at all -- those would have blasted.
4. Reconciliation. pulled == kept + excluded + errored, printed and written to JSON.
"""
import csv
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import leads_audit as LA  # noqa: E402  (env/auth/ghl_get/pagination/classifier all reused)

# ---------------------------------------------------------------------------
# Knobs
# ---------------------------------------------------------------------------
AUDIT_LIMIT = int(os.environ.get("AUDIT_LIMIT") or 0)  # 0 = all contacts

# Skip the (2 API calls/contact) thread pull for contacts already excluded by the
# compliance gate. Their thread cannot change the outcome -- they are off the list
# either way -- and on the live data this drops ~40% of the run. Set 0 to pull anyway
# (e.g. if the Thread Auditor wants excluded threads too).
SKIP_THREADS_FOR_EXCLUDED = os.environ.get("AUDIT_PULL_EXCLUDED_THREADS", "0") != "1"

# Literal reading of "soft_no is a KEEP bucket". Default False: "not interested" /
# "not for sale" is a refusal, and shipping it into a 5,000-person blast is exactly
# what plan section 5 rule 5 (exclusion beats inclusion) exists to stop.
SOFT_NO_REFUSAL_IS_KEEP = False

OUT_DIR = LA.OUT_DIR
PREFIX = f"slice{AUDIT_LIMIT}_" if AUDIT_LIMIT else ""
OUT_CSV = os.path.join(OUT_DIR, f"{PREFIX}all_leads_audit.csv")
DEDUP_CSV = os.path.join(OUT_DIR, f"{PREFIX}all_leads_audit_deduped.csv")
SUMMARY_JSON = os.path.join(OUT_DIR, f"{PREFIX}all_leads_audit_summary.json")

KEEP_SEGMENTS = ("active_pending_us", "replied_then_cold", "soft_no_revisit",
                 "never_replied", "no_outbound_yet")

# ---------------------------------------------------------------------------
# 2. soft_no split -- partition of LA._SOFT_NO_PHRASES, refusal checked first so an
#    ambiguous "not selling right now" lands on the exclude side.
# ---------------------------------------------------------------------------
SOFT_NO_REFUSAL_PHRASES = [
    "not for sale", "not selling", "not interested", "no longer selling",
    "not looking to sell", "not gonna sell", "not going to sell", "won't sell",
    "wont sell", "decided not to sell", "changed my mind",
    "keeping the house", "keeping the property",
]
SOFT_NO_TIMING_PHRASES = [
    "not right now", "not at this time", "not at the moment", "maybe later",
    "not the right time", "not ready to sell",
    # not in LA's list, so only ever consulted once LA has already said soft_no
    "in a few months", "in a couple months", "next year", "check back",
    "down the road", "not yet", "call me back in", "try me in",
]


def soft_no_kind(body):
    """'timing' (re-engageable) or 'refusal'. Unclassifiable -> refusal (exclude)."""
    b = (body or "").lower()
    if any(p in b for p in SOFT_NO_REFUSAL_PHRASES):
        return "refusal"
    # LA._TIMING_RE carries the widened forms ("give me 2 weeks", "call me in a few
    # months", "check back in the spring") that no phrase list here can spell out.
    if any(p in b for p in SOFT_NO_TIMING_PHRASES) or LA._is_timing(b):
        return "timing"
    return "refusal"


# ---------------------------------------------------------------------------
# 3. The compliance gate
# ---------------------------------------------------------------------------
# Live field dump (2026-08-21) -- dndSettings is per-channel:
#   {"SMS": {"status": "permanent", "message": "STOP_KEYWORD"}}
#   {"SMS": {"status": "active",    "message": "TWILIO_ERROR_CODE: 30005"}}
# status "inactive" (or absent) means no DND. Anything else is a block.
_DND_INACTIVE = {"inactive", "", "none", "null"}

# STOP_KEYWORD / Twilio 21610 (blacklist) are carrier-level opt-outs. Twilio 3000x are
# undeliverable-handset errors -- a dead NUMBER, not an opted-out PERSON. Both are
# excluded, but only the opt-out class poisons the person's other phone number during
# dedupe (see merge_rank). Anything unrecognised, including an operator's manual DND,
# is treated as opt_out: exclusion beats inclusion.
_UNDELIVERABLE_RE = re.compile(r"TWILIO_ERROR_CODE:\s*3000\d", re.I)

# Matched against tags with boundaries so "sms blasted" / "read-taxdel-0515" cannot
# false-positive. Live tag hits: `dnc` (78), `wrong-number` (1).
_DNC_TAG_RE = re.compile(
    r"(?:^|[^a-z])("
    r"dnc|do ?not ?(?:contact|call|text|disturb)|opt[- _]?ed?[- _]?out|"
    r"unsubscrib\w*|stop|remove[- _]?me|black[- _]?list\w*|litigat\w*|"
    r"suppress\w*|wrong[- _]?number"
    r")(?:[^a-z]|$)", re.I)


def dnd_sms_entry(contact):
    """Raw 'status:message' for the SMS channel when DND is on, else ''."""
    ds = contact.get("dndSettings")
    if not isinstance(ds, dict):
        return ""
    v = ds.get("SMS") or ds.get("sms")
    if isinstance(v, dict):
        status, message = v.get("status"), v.get("message")
    elif v:
        status, message = v, ""
    else:
        return ""
    if str(status or "").strip().lower() in _DND_INACTIVE:
        return ""
    return f"{status}:{message or ''}".strip(":")


def dnc_tag_hits(contact):
    return [str(t) for t in (contact.get("tags") or []) if _DNC_TAG_RE.search(str(t))]


def compliance_check(contact):
    """(dnd_flag, dnd_sms, dnc_tags, exclude_reason, dnd_class).

    exclude_reason is 'ghl_dnd' on any hit, '' otherwise. dnd_class is 'opt_out'
    (person-level, permanent) or 'undeliverable' (that phone number only)."""
    dnd_flag = contact.get("dnd") is True
    dnd_sms = dnd_sms_entry(contact)
    tags = dnc_tag_hits(contact)
    if not (dnd_flag or dnd_sms or tags):
        return (dnd_flag, "", "", "", "")
    if dnd_sms and not dnd_flag and not tags:
        status, _, message = dnd_sms.partition(":")
        undeliverable = (status.strip().lower() != "permanent"
                         and bool(_UNDELIVERABLE_RE.search(message)))
        cls = "undeliverable" if undeliverable else "opt_out"
    else:
        cls = "opt_out"  # explicit dnd boolean or a DNC tag is about the person
    return (dnd_flag, dnd_sms, ";".join(tags), "ghl_dnd", cls)


# ---------------------------------------------------------------------------
# Dedupe ranking
# ---------------------------------------------------------------------------
COMPLIANCE_DEAD_END = {"dnc", "opt_out"}  # thread-derived; unchanged from leads_audit
# Every dead-end reason now beats a live duplicate of the same seller (7 Ohio KEEP
# survivors had swallowed one). The exception is wrong_number: like a Twilio
# undeliverable it is scoped to THAT HANDSET, not the person, so it must not delete
# the seller's good second number -- exactly the split plan section 4 mandates.
HANDSET_SCOPED_DEAD_END = {"wrong_number"}
STATUS_RANK = {"active_pending_us": 5, "replied_then_cold": 4, "soft_no_revisit": 3,
               "dead_end": 2, "never_replied": 1, "no_outbound_yet": 0,
               "excluded": -1}


def merge_rank(row):
    """Compliance wins over everything; a dead handset loses to a live sibling."""
    if row["status_category"] == "excluded":
        return 100 if row["dnd_class"] == "opt_out" else -1
    if row["status_category"] == "dead_end":
        # handset-scoped: must LOSE to any live sibling row for the same address,
        # exactly like an undeliverable number does.
        return -1 if row["dead_end_reason"] in HANDSET_SCOPED_DEAD_END else 100
    return STATUS_RANK.get(row["status_category"], -1)


def dedup_key(row):
    addr = (row["address1"] or "").strip().lower()
    if addr:
        return f"addr:{addr}|{row['postal_code']}"
    return f"name:{row['name'].strip().lower()}"


CSV_FIELDS = [
    "contact_id", "name", "phone", "email", "address1", "city", "state",
    "postal_code", "current_tags",
    "dnd_flag", "dnd_sms", "dnd_class", "dnc_tags", "exclude_reason",
    "last_message_date_iso", "last_message_direction", "status_category",
    "dead_end_reason", "last_inbound_snippet", "last_outbound_snippet",
    "total_inbound_count", "total_outbound_count",
]


def contact_name(c):
    return c.get("contactName") or LA.contact_name(c)


def audit_contact(c):
    """One contact -> one output row. Compliance gate runs BEFORE any thread pull."""
    dnd_flag, dnd_sms, dnc_tags, exclude_reason, dnd_class = compliance_check(c)
    row = {
        "contact_id": c.get("id"),
        "name": contact_name(c),
        "phone": c.get("phone") or "",
        "email": c.get("email") or "",
        "address1": c.get("address1") or "",
        "city": c.get("city") or "",
        "state": c.get("state") or "",          # blank kept, never a drop reason
        "postal_code": c.get("postalCode") or "",
        "current_tags": ";".join(str(t) for t in (c.get("tags") or [])),
        "dnd_flag": "1" if dnd_flag else "0",
        "dnd_sms": dnd_sms,
        "dnd_class": dnd_class,
        "dnc_tags": dnc_tags,
        "exclude_reason": exclude_reason,
        "last_message_date_iso": "", "last_message_direction": "",
        "status_category": "excluded" if exclude_reason else "",
        "dead_end_reason": "", "last_inbound_snippet": "", "last_outbound_snippet": "",
        "total_inbound_count": 0, "total_outbound_count": 0,
    }
    if exclude_reason and SKIP_THREADS_FOR_EXCLUDED:
        return row

    messages = LA.full_thread(c.get("id"))
    (status, last_in, last_out, n_in, n_out,
     last_dir, last_ms, reason) = LA.classify(messages, row["name"])

    if reason == "soft_no":
        kind = soft_no_kind(last_in.get("body") if last_in else "")
        if kind == "timing" or SOFT_NO_REFUSAL_IS_KEEP:
            reason, status = f"soft_no_{kind}", "soft_no_revisit"
        else:
            reason = "soft_no_refusal"  # stays dead_end
    elif not reason and status in ("active_pending_us", "replied_then_cold"):
        # Real timing language ("call me back in the spring", "give me 2 weeks")
        # never reaches LA's 6-phrase soft_no list, so it lands here. Re-label so
        # Stage D writes timing-aware copy. KEEP either way -- never an exclusion.
        if LA._is_timing(last_in.get("body") if last_in else ""):
            reason, status = "soft_no_timing", "soft_no_revisit"

    row.update({
        "last_message_date_iso": LA.iso(last_ms),
        "last_message_direction": last_dir,
        "status_category": "excluded" if exclude_reason else status,
        "dead_end_reason": reason or "",
        "last_inbound_snippet": LA.snippet(last_in.get("body")) if last_in else "",
        "last_outbound_snippet": LA.snippet(last_out.get("body")) if last_out else "",
        "total_inbound_count": n_in,
        "total_outbound_count": n_out,
    })
    return row


def write_csv(path, fields, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def tally(rows, key):
    out = {}
    for r in rows:
        v = r.get(key) or "(none)"
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)

    print(f"[full_audit] pulling ALL contacts for location {LA.LOCATION_ID} ...")
    all_contacts = LA.list_all_contacts()
    pulled_total = len(all_contacts)
    print(f"[full_audit] total contacts pulled: {pulled_total} "
          f"({LA.api_call_count} api calls)")

    contacts = all_contacts[:AUDIT_LIMIT] if AUDIT_LIMIT else all_contacts
    if AUDIT_LIMIT:
        print(f"[full_audit] AUDIT_LIMIT={AUDIT_LIMIT} -> slicing to {len(contacts)}")

    rows, errors = [], []
    for i, c in enumerate(contacts, 1):
        try:
            rows.append(audit_contact(c))
        except Exception as e:
            errors.append({"contact_id": c.get("id"), "name": contact_name(c),
                           "error": str(e)})
        if i % 250 == 0:
            print(f"[full_audit] {i}/{len(contacts)} ({LA.api_call_count} api calls, "
                  f"{time.time() - t0:.0f}s)")

    write_csv(OUT_CSV, CSV_FIELDS, rows)

    # ---- dedupe: one row per real-world lead (same address = same seller, two phones)
    groups = {}
    for row in rows:
        groups.setdefault(dedup_key(row), []).append(row)
    deduped = []
    for group in groups.values():
        best = max(group, key=merge_rank)
        merged = dict(best)
        merged["duplicate_contact_ids"] = ";".join(
            r["contact_id"] for r in group if r["contact_id"] != best["contact_id"])
        merged["duplicate_count"] = len(group) - 1
        deduped.append(merged)
    write_csv(DEDUP_CSV, CSV_FIELDS + ["duplicate_contact_ids", "duplicate_count"],
              deduped)

    # ---- per-segment files off the deduped set
    seg_files = {}
    for seg in KEEP_SEGMENTS + ("dead_end", "excluded"):
        seg_rows = [r for r in deduped if r["status_category"] == seg]
        if not seg_rows:
            continue
        p = os.path.join(OUT_DIR, f"{PREFIX}all_leads_{seg}.csv")
        write_csv(p, CSV_FIELDS + ["duplicate_contact_ids", "duplicate_count"], seg_rows)
        seg_files[seg] = {"file": p, "rows": len(seg_rows)}

    # ---- 4. reconciliation: nothing may be silently dropped
    kept = [r for r in rows if r["status_category"] in KEEP_SEGMENTS]
    excluded = [r for r in rows if r["status_category"] in ("excluded", "dead_end")]
    accounted = len(kept) + len(excluded) + len(errors)
    balanced = accounted == len(contacts)

    exclude_reasons = {}
    for r in excluded:
        reason = r["exclude_reason"] or r["dead_end_reason"] or "unknown"
        if r["exclude_reason"] == "ghl_dnd":
            reason = f"ghl_dnd/{r['dnd_class']}"
        exclude_reasons[reason] = exclude_reasons.get(reason, 0) + 1
    exclude_reasons = dict(sorted(exclude_reasons.items(), key=lambda kv: -kv[1]))

    summary = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "location_id": LA.LOCATION_ID,
        "audit_limit": AUDIT_LIMIT,
        "contacts_in_location": pulled_total,
        "contacts_processed": len(contacts),
        "rows_written": len(rows),
        "kept": len(kept),
        "excluded": len(excluded),
        "errored": len(errors),
        "reconciliation_balanced": balanced,
        "status_counts": tally(rows, "status_category"),
        "exclude_reason_counts": exclude_reasons,
        "state_counts": tally(rows, "state"),
        "dedup_total": len(deduped),
        "dedup_status_counts": tally(deduped, "status_category"),
        "dedup_kept": sum(1 for r in deduped if r["status_category"] in KEEP_SEGMENTS),
        "segment_files": seg_files,
        "errors": errors[:100],
        "api_calls": LA.api_call_count,
        "elapsed_sec": round(time.time() - t0, 1),
        "files": {"raw": OUT_CSV, "deduped": DEDUP_CSV},
    }
    with open(SUMMARY_JSON, "w") as f:
        json.dump(summary, f, indent=2)

    print("\n===== RECONCILIATION =====")
    print(f"contacts in location : {pulled_total}")
    print(f"contacts processed   : {len(contacts)}")
    print(f"  kept               : {len(kept)}")
    print(f"  excluded           : {len(excluded)}")
    print(f"  errored            : {len(errors)}")
    print(f"  accounted          : {accounted}  "
          f"{'BALANCED' if balanced else '*** MISMATCH ***'}")
    print("\nstatus_category:")
    for k, v in summary["status_counts"].items():
        print(f"  {k:<20} {v}")
    print("\nexclude reasons:")
    for k, v in exclude_reasons.items():
        print(f"  {k:<24} {v}")
    print("\nstates (blank shown as '(none)'):")
    for k, v in summary["state_counts"].items():
        print(f"  {k:<10} {v}")
    if errors:
        print(f"\nerrors ({len(errors)}):")
        for e in errors[:20]:
            print(f"  {e['contact_id']}: {e['error']}")
    print(f"\n===== DEDUPED ({len(deduped)} unique leads from {len(rows)} rows) =====")
    for k, v in summary["dedup_status_counts"].items():
        print(f"  {k:<20} {v}")
    print(f"\nkeep-list size after dedupe: {summary['dedup_kept']}")
    print("\nfiles:")
    print(f"  {OUT_CSV}")
    print(f"  {DEDUP_CSV}")
    for seg, info in seg_files.items():
        print(f"  {info['file']}  ({info['rows']})")
    print(f"  {SUMMARY_JSON}")
    print(f"\napi calls: {LA.api_call_count}   elapsed: {time.time() - t0:.1f}s")
    return summary


# ---------------------------------------------------------------------------
# Self-check -- pure logic, zero API calls: python3 full_leads_audit.py --selfcheck
# ---------------------------------------------------------------------------
def selfcheck():
    # the soft_no partition must cover every phrase leads_audit can fire on, or a
    # real seller reply silently falls through to the exclude default
    for p in LA._SOFT_NO_PHRASES:
        assert p in SOFT_NO_REFUSAL_PHRASES or p in SOFT_NO_TIMING_PHRASES, p
    assert soft_no_kind("not right now, maybe in the spring") == "timing"
    assert soft_no_kind("im not interested") == "refusal"
    assert soft_no_kind("not selling right now") == "refusal"   # ambiguous -> exclude
    assert soft_no_kind("") == "refusal"

    stop = {"dndSettings": {"SMS": {"status": "permanent", "message": "STOP_KEYWORD"}}}
    dead = {"dndSettings": {"SMS": {"status": "active",
                                    "message": "TWILIO_ERROR_CODE: 30005"}}}
    manual = {"dndSettings": {"SMS": {"status": "active",
                                      "message": "Updated by 'Yahjair Mack' at X"}}}
    off = {"dndSettings": {"SMS": {"status": "inactive", "message": ""}},
           "tags": ["sms blasted", "ohio 1 st number", "read-taxdel-0515"]}
    tagged = {"tags": ["wholesale lead", "DNC"]}
    flagged = {"dnd": True}
    assert compliance_check(stop)[3:] == ("ghl_dnd", "opt_out")
    assert compliance_check(dead)[3:] == ("ghl_dnd", "undeliverable")
    assert compliance_check(manual)[3:] == ("ghl_dnd", "opt_out")   # unknown -> exclude
    assert compliance_check(off) == (False, "", "", "", "")         # no false positives
    assert compliance_check(tagged)[2:] == ("DNC", "ghl_dnd", "opt_out")
    assert compliance_check(flagged)[3:] == ("ghl_dnd", "opt_out")
    assert dnd_sms_entry({"dndSettings": {"Call": {"status": "active"}}}) == ""
    assert dnd_sms_entry({}) == "" and dnd_sms_entry({"dndSettings": None}) == ""

    def R(status, **kw):
        r = {"status_category": status, "dead_end_reason": "", "dnd_class": ""}
        r.update(kw)
        return r
    # an opt-out on one of a seller's numbers kills the whole seller...
    assert merge_rank(R("excluded", dnd_class="opt_out")) > merge_rank(R("active_pending_us"))
    assert merge_rank(R("dead_end", dead_end_reason="dnc")) > merge_rank(R("active_pending_us"))
    # ...but a dead handset must lose to that seller's live second number
    assert merge_rank(R("excluded", dnd_class="undeliverable")) < merge_rank(R("no_outbound_yet"))
    # dead_end with a reason is now unbeatable, so this contract is stated against
    # the handset-scoped one (a bare dead_end row with no reason cannot occur:
    # LA.classify only sets status "dead_end" when a reason fired).
    assert merge_rank(R("soft_no_revisit")) > merge_rank(
        R("dead_end", dead_end_reason="wrong_number"))
    assert merge_rank(R("replied_then_cold")) > merge_rank(R("soft_no_revisit"))
    # every dead-end reason is unbeatable now, EXCEPT the handset-scoped one
    for reason in ("hard_no", "sold", "soft_no_refusal", "dnc", "opt_out"):
        assert merge_rank(R("dead_end", dead_end_reason=reason)) > merge_rank(
            R("active_pending_us")), reason
    assert merge_rank(R("dead_end", dead_end_reason="wrong_number")) < merge_rank(
        R("never_replied"))
    # widened timing detection reaches soft_no_kind
    assert soft_no_kind("call me back in a few months") == "timing"
    assert soft_no_kind("give me 2 weeks") == "timing"
    assert soft_no_kind("check back in the spring") == "timing"
    assert soft_no_kind("not interested, call me in a few months") == "refusal"
    print("selfcheck OK")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        selfcheck()
    else:
        main()
