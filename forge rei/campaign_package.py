#!/usr/bin/env python3
"""Stage E — package the Stage C keep-list into GHL-import-ready per-segment CSVs.

PURE LOCAL. Zero network calls, zero GHL calls, zero writes outside marcus_state/.
Reads the Stage C output, splits names, applies the campaign/segment tag, and
PROVES no excluded / dead_end contact leaked into a send file before writing.

Header spec source (verified, not guessed):
  ~/Desktop/marcus-wholesale-agent/skills/wholesale-list-cleaner/SKILL.md  ("Output
  Format (GHL-Ready)") and its three scripts clean_list.py / clean_multiphone.py /
  clean_batchdata_list.py, which all emit exactly:
      First Name | Last Name | Phone | Email | Address1 | City | State | Postal Code
  Phone in E164 (+1XXXXXXXXXX).

Run: python3 campaign_package.py
"""
import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXPORT = os.path.join(HERE, "marcus_state", "leads_export")

CAMPAIGN_TAG = "reengage-2026-08"
SEND_SEGMENTS = ["active_pending_us", "replied_then_cold", "no_outbound_yet", "never_replied"]
BLOCK_FILES = ["all_leads_excluded.csv", "all_leads_dead_end.csv"]

# The verified GHL-ready spec, plus 3 operational columns. Contact Id is here because
# these contacts ALREADY EXIST in GHL — this is an update/tag, never a create.
GHL_COLUMNS = ["First Name", "Last Name", "Phone", "Email",
               "Address1", "City", "State", "Postal Code",
               "Tags", "Contact Id", "Segment"]

# Never text ourselves. The operator's own contact record sits in the CRM.
INTERNAL_EMAILS = {"yahjair@atouchofblessing.com"}

_SUFFIX = re.compile(r"\b(llc|inc|ltd|corp|co|trust|lp|llp)\b\.?$", re.I)


def norm_phone(raw):
    d = re.sub(r"\D", "", str(raw or ""))
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return d if len(d) == 10 else ""


def split_name(full):
    """'clive wilson' -> ('Clive','Wilson'). LLC/Trust suffixes ride with the last name."""
    parts = [p for p in str(full or "").strip().split() if p]
    if not parts:
        return "", ""
    parts = [p.upper() if _SUFFIX.fullmatch(p) else p.title() for p in parts]
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def read_rows(name):
    path = os.path.join(EXPORT, name)
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def ids_and_phones(rows):
    """Every contact_id (incl. dedupe-collapsed siblings) + every phone in a block file."""
    ids, phones = set(), set()
    for r in rows:
        cid = (r.get("contact_id") or "").strip()
        if cid:
            ids.add(cid)
        for dup in (r.get("duplicate_contact_ids") or "").replace(";", ",").split(","):
            dup = dup.strip()
            if dup:
                ids.add(dup)
        p = norm_phone(r.get("phone"))
        if p:
            phones.add(p)
    return ids, phones


def main():
    block_rows = []
    for fn in BLOCK_FILES:
        block_rows += read_rows(fn)
    block_ids, block_phones = ids_and_phones(block_rows)

    # Person-level exclusions only: these can never be beaten by a sibling contact.
    person_level_phones = {
        norm_phone(r.get("phone")) for r in block_rows
        if (r.get("dnd_class") == "opt_out"
            or (r.get("exclude_reason") or "").split("/")[0] in ("dnc", "opt_out")
            or (r.get("dead_end_reason") or "") in ("dnc", "opt_out", "hard_no", "sold",
                                                    "soft_no_refusal"))
    } - {""}

    report = {"campaign_tag": CAMPAIGN_TAG, "block_contact_ids": len(block_ids),
              "block_phones": len(block_phones),
              "person_level_block_phones": len(person_level_phones),
              "segments": {}, "violations": [], "dropped": []}
    grand = 0

    for seg in SEND_SEGMENTS:
        rows = read_rows(f"all_leads_{seg}.csv")
        out, seen = [], set()
        for r in rows:
            cid = (r.get("contact_id") or "").strip()
            phone = (r.get("phone") or "").strip()
            key = norm_phone(phone)
            email = (r.get("email") or "").strip()

            if email.lower() in INTERNAL_EMAILS:
                report["dropped"].append([seg, cid, "internal_contact"])
                continue
            if not key:
                report["dropped"].append([seg, cid, "no_sendable_phone"])
                continue
            if cid in block_ids:
                report["violations"].append([seg, cid, "contact_id in block list"])
                continue
            if key in person_level_phones:
                report["violations"].append([seg, cid, "phone matches person-level exclusion"])
                continue
            if key in block_phones:
                report["violations"].append([seg, cid, "phone in block list"])
                continue
            if key in seen:
                report["dropped"].append([seg, cid, "duplicate_phone_within_segment"])
                continue
            seen.add(key)

            first, last = split_name(r.get("name"))
            out.append({
                "First Name": first, "Last Name": last,
                "Phone": phone if phone.startswith("+") else "+1" + key,
                "Email": email,
                "Address1": (r.get("address1") or "").strip(),
                "City": (r.get("city") or "").strip(),
                "State": (r.get("state") or "").strip(),
                "Postal Code": (r.get("postal_code") or "").strip(),
                "Tags": f"{CAMPAIGN_TAG}-{seg.replace('_', '-')}",
                "Contact Id": cid,
                "Segment": seg,
            })

        path = os.path.join(EXPORT, f"GHL_IMPORT_{seg}.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=GHL_COLUMNS)
            w.writeheader()
            w.writerows(out)
        report["segments"][seg] = {"in": len(rows), "out": len(out), "file": path}
        grand += len(out)

    # Cross-segment: no contact may appear in two send files.
    allc = []
    for seg in SEND_SEGMENTS:
        with open(os.path.join(EXPORT, f"GHL_IMPORT_{seg}.csv"), newline="",
                  encoding="utf-8") as f:
            allc += [(seg, r["Contact Id"], norm_phone(r["Phone"]))
                     for r in csv.DictReader(f)]
    seen_id, seen_ph = {}, {}
    for seg, cid, ph in allc:
        if cid in seen_id:
            report["violations"].append([seg, cid, f"also in {seen_id[cid]}"])
        seen_id[cid] = seg
        if ph in seen_ph:
            report["violations"].append([seg, cid, f"phone dup with {seen_ph[ph]}"])
        seen_ph[ph] = seg

    report["total_sendable"] = grand
    with open(os.path.join(EXPORT, "GHL_IMPORT_verification.json"), "w") as f:
        json.dump(report, f, indent=2)

    print("=" * 62)
    print("  STAGE E — GHL IMPORT PACKAGE")
    print("=" * 62)
    print(f"  block list: {len(block_ids)} contact_ids / {len(block_phones)} phones "
          f"({len(person_level_phones)} person-level)")
    for seg, v in report["segments"].items():
        print(f"  {seg:20} {v['in']:5} in -> {v['out']:5} out   {os.path.basename(v['file'])}")
    print(f"  {'TOTAL SENDABLE':20} {grand:5}")
    print("-" * 62)
    for seg, cid, why in report["dropped"]:
        print(f"  DROPPED  {seg}/{cid}: {why}")
    if report["violations"]:
        print(f"  ** {len(report['violations'])} EXCLUSION LEAKS **")
        for v in report["violations"][:20]:
            print("   ", v)
        return 1
    print("  LEAK CHECK: 0 excluded/dead_end contacts in any send file.  PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
