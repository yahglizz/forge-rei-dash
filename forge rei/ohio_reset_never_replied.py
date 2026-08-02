#!/usr/bin/env python3
"""Standalone GHL reset script: for every OHIO contact in the RAW audit CSV whose
status_category == "never_replied", strip stale triage tags and move any open
opportunity back to the "New Lead" pipeline stage — resetting them to look like a
fresh, untouched lead.

DRY_RUN = True by default (see below). In dry-run, every GET call is real (tags +
opportunities are fetched live from GHL) but NO writes happen — no DELETE, no PUT.
Only a human flipping DRY_RUN to False makes this live. Re-run safe either way.

Run: python3 ohio_reset_never_replied.py
"""
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------------------
DRY_RUN = True   # flip to False only after a human reviews the dry-run report
# ---------------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, "..", "marcus-wholesale-agent", "config", "ghl.env")
RAW_CSV = os.path.join(HERE, "marcus_state", "leads_export", "ohio_leads_audit.csv")

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

RETRY_MAX = 3
RETRY_STATUSES = {429, 500, 502, 503}
PIPELINE_PREF = "wholesal"  # same convention as scout_triage.py:121 PIPELINE_PREF


# ---------------------------------------------------------------------------
# Env / auth — identical pattern to leads_audit.py
# ---------------------------------------------------------------------------
def load_env(path):
    cfg = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    return cfg


ENV = load_env(ENV_PATH)
API_KEY = ENV["GHL_API_KEY"]
LOCATION_ID = ENV["GHL_LOCATION_ID"]
BASE_URL = ENV.get("GHL_BASE_URL", "https://services.leadconnectorhq.com")
API_VERSION = ENV.get("GHL_API_VERSION", "2021-07-28")

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Version": API_VERSION,
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": USER_AGENT,
}

api_call_count = 0


def _request(method, path, params=None, body=None):
    """Shared GET/PUT/DELETE with the same retry/backoff as leads_audit.py's ghl_get."""
    global api_call_count
    url = f"{BASE_URL}{path}"
    if params:
        qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{url}?{qs}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    last_err = None
    for attempt in range(1, RETRY_MAX + 1):
        api_call_count += 1
        req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                return json.loads(raw.decode("utf-8")) if raw else {}
        except urllib.error.HTTPError as e:
            if e.code in RETRY_STATUSES and attempt < RETRY_MAX:
                time.sleep(0.6 * attempt)
                last_err = e
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt < RETRY_MAX:
                time.sleep(0.6 * attempt)
                last_err = e
                continue
            raise
    raise last_err or RuntimeError(f"{method} {path} failed with no response")


def ghl_get(path, params=None):
    return _request("GET", path, params=params)


def ghl_put(path, body):
    return _request("PUT", path, body=body)


def ghl_delete(path, body):
    return _request("DELETE", path, body=body)


# ---------------------------------------------------------------------------
# Tag-strip rule: remove stale triage tags, keep import/lineage tags untouched.
# ---------------------------------------------------------------------------
_STRIP_PREFIXES = ("triage:", "motivated:", "ask:")
_STRIP_EXACT = {"offer-made"}


def tags_to_strip(current_tags):
    out = []
    for t in current_tags or []:
        low = (t or "").strip().lower()
        if any(low.startswith(p) for p in _STRIP_PREFIXES) or low in _STRIP_EXACT:
            out.append(t)
    return out


# ---------------------------------------------------------------------------
# Pipeline / stage resolution
# ---------------------------------------------------------------------------
def resolve_pipeline_and_stage():
    data = ghl_get("/opportunities/pipelines", {"locationId": LOCATION_ID})
    pipes = data.get("pipelines", []) or []
    pipeline = next((p for p in pipes if PIPELINE_PREF in (p.get("name") or "").lower()),
                     None)
    if not pipeline:
        names = [p.get("name") for p in pipes]
        print(f"ERROR: no pipeline name contains {PIPELINE_PREF!r}. "
              f"Pipelines found: {names}")
        sys.exit(1)

    stages = pipeline.get("stages", []) or []
    stage = next((s for s in stages if (s.get("name") or "").strip().lower() == "new lead"),
                 None)
    if not stage:
        stage = next((s for s in stages if "new lead" in (s.get("name") or "").lower()),
                     None)
    if not stage:
        print(f"ERROR: no stage matching 'New Lead' in pipeline "
              f"{pipeline.get('name')!r} ({pipeline.get('id')}). "
              f"Stages found: {[s.get('name') for s in stages]}")
        sys.exit(1)

    return pipeline, stage


# ---------------------------------------------------------------------------
# Per-contact GHL reads
# ---------------------------------------------------------------------------
def live_tags(contact_id):
    data = ghl_get(f"/contacts/{contact_id}") or {}
    contact = data.get("contact") or data  # GHL inconsistent: wrapped or bare
    return contact.get("tags") or []


def opportunities_for(contact_id):
    data = ghl_get("/opportunities/search",
                    {"location_id": LOCATION_ID, "contactId": contact_id, "limit": 20})
    return data.get("opportunities") or []


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def load_never_replied(csv_path):
    rows = []
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            if row.get("status_category") == "never_replied":
                rows.append(row)
    return rows


def main():
    t0 = time.time()
    print(f"[ohio_reset] DRY_RUN = {DRY_RUN}")

    pipeline, stage = resolve_pipeline_and_stage()
    stage_id = stage["id"]
    stage_name = stage["name"]
    pipeline_id = pipeline["id"]
    print(f"[ohio_reset] Resolved pipeline: {pipeline.get('name')!r} ({pipeline_id})")
    print(f"[ohio_reset] Resolved stage:    {stage_name!r} ({stage_id})")
    stage_names_by_id = {s["id"]: s.get("name") for s in pipeline.get("stages", [])}

    rows = load_never_replied(RAW_CSV)
    print(f"[ohio_reset] never_replied rows loaded: {len(rows)}")

    processed = 0
    tags_stripped_count = 0
    opps_moved_count = 0
    opps_already_reset_count = 0
    errors = []
    preview_lines = []

    for i, row in enumerate(rows, 1):
        cid = row["contact_id"]
        name = row["name"]
        try:
            current_tags = live_tags(cid)
            strip = tags_to_strip(current_tags)

            opps = opportunities_for(cid)
            to_move = []
            for opp in opps:
                if opp.get("pipelineStageId") != stage_id:
                    to_move.append(opp)
                else:
                    opps_already_reset_count += 1

            if DRY_RUN:
                move_desc = ", ".join(
                    f"{o.get('id')} ({stage_names_by_id.get(o.get('pipelineStageId'), o.get('pipelineStageId'))} -> {stage_name})"
                    for o in to_move
                )
                line = (f"contact={cid} name={name!r} "
                        f"tags_to_remove={strip} opps_to_move=[{move_desc}]")
                if len(preview_lines) < 10:
                    preview_lines.append(line)
                if strip:
                    tags_stripped_count += 1
                if to_move:
                    opps_moved_count += len(to_move)
            else:
                if strip:
                    ghl_delete(f"/contacts/{cid}/tags", {"tags": strip})
                    tags_stripped_count += 1
                for opp in to_move:
                    ghl_put(f"/opportunities/{opp['id']}",
                            {"pipelineStageId": stage_id, "pipelineId": pipeline_id})
                    opps_moved_count += 1

            processed += 1
        except Exception as e:
            errors.append((cid, name, str(e)))

        if i % 25 == 0:
            print(f"[ohio_reset] processed {i}/{len(rows)} "
                  f"({api_call_count} api calls so far)...")

    elapsed = time.time() - t0
    print("\n===== SUMMARY =====")
    print(f"DRY_RUN: {DRY_RUN}")
    print(f"Pipeline: {pipeline.get('name')!r} ({pipeline_id})  Stage: {stage_name!r} ({stage_id})")
    print(f"Total processed: {processed}/{len(rows)}")
    print(f"Contacts with tags stripped: {tags_stripped_count}")
    print(f"Opportunities moved: {opps_moved_count}")
    print(f"Opportunities already reset (no-op): {opps_already_reset_count}")
    print(f"Errors: {len(errors)}")
    for cid, name, err in errors[:50]:
        print(f"  ERROR contact={cid} name={name!r}: {err}")
    print(f"API calls made: {api_call_count}")
    print(f"Elapsed: {elapsed:.1f}s")

    if DRY_RUN:
        print("\n===== SAMPLE PREVIEW (first 10) =====")
        for line in preview_lines:
            print(f"  {line}")

    return {
        "pipeline_id": pipeline_id, "pipeline_name": pipeline.get("name"),
        "stage_id": stage_id, "stage_name": stage_name,
        "processed": processed, "tags_stripped": tags_stripped_count,
        "opps_moved": opps_moved_count, "opps_already_reset": opps_already_reset_count,
        "errors": errors, "api_calls": api_call_count, "elapsed": elapsed,
    }


if __name__ == "__main__":
    main()
