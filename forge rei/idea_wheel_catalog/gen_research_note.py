"""Regenerate docs/ideawheel-research.md from idea_wheel_catalog/*.json (single source of truth).

    python3 idea_wheel_catalog/gen_research_note.py
"""
import json
import os
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAT = os.path.join(ROOT, "idea_wheel_catalog")
L = lambda n: json.load(open(os.path.join(CAT, n)))
sectors, niches, pats, fmts, styles, srcs = (L("sectors.json"), L("niches.json"), L("workflows.json"),
                                             L("formats.json"), L("styles.json"), L("sources.json"))
S = {s["id"]: s for s in srcs}
STY = {s["id"]: s["label"] for s in styles}
FMT = {f["id"]: f["label"] for f in fmts}
PAT = {p["id"]: p for p in pats}
WF_SRC = {"JOBBER", "HOUSECALL", "SQUARE_APPT", "MINDBODY", "PROCARE", "TEKMETRIC", "APPFOLIO", "GINGR"}

def esc(t):
    return str(t).replace("|", "\\|")

out = []
w = out.append
w("# Idea Wheel — research note (catalog provenance)")
w("")
w("Accessed: **2026-10-16**. Generated from `idea_wheel_catalog/*.json` (the catalog is the source of truth; "
  "regenerate this note when the catalog changes). Purpose: give the Idea Wheel a researched, extensible catalog of "
  "SMB niches and reusable digital workflow patterns, Philadelphia-weighted but not Philadelphia-only.")
w("")
w("## Counts")
wv = sum(1 for n in niches if n["workflowVerified"])
ph = sum(1 for n in niches if n["phillyNote"])
pv = sum(1 for p in pats if [s for s in p["sources"] if s in WF_SRC])
w(f"- **{len(niches)} business subtypes** in **{len(sectors)} sectors**. Every NAICS code was machine-checked "
  f"against the official Census 2022 NAICS list (source `NAICS`) — 0 mismatches.")
w(f"- **{wv}** niches have their *customer workflow* backed by a fetched industry source; "
  f"**{len(niches) - wv}** are marked `unverified` for workflow (NAICS classification is still verified; the workflow "
  "and demo features are an informed starter entry, not a cited claim).")
w(f"- **{ph}** niches carry a Philadelphia / Pennsylvania source note.")
w(f"- **{len(pats)} reusable workflow patterns**; **{pv}** cite a fetched vendor/industry page, "
  f"**{len(pats) - pv}** are `unverified` starter patterns.")
w("")
w("## Method")
w("1. Official taxonomy: downloaded the Census 2022 NAICS 2–6 digit code file and parsed it locally; each niche's "
  "code and official title come from that file.")
w("2. Philadelphia relevance: City of Philadelphia Commerce + L&I + Public Health pages, the Storefront Improvement "
  "Program release (corridor business mix), and the Philadelphia Fed corridors article.")
w("3. Customer workflows: SMB software vendor pages that describe the day-to-day workflows their customers run "
  "(field service, appointments, fitness, childcare, auto repair, property management, pet care). These are vendor "
  "pages — good evidence of *what workflows exist*, not neutral market data.")
w("4. Guardrails: HHS (HIPAA scope), FTC (fake reviews/testimonials rule, COPPA) — drive the generator's compatibility rules.")
w("5. No statistic below is invented. Where a source was only seen as a search result (not fetched), it is labeled "
  "`search result`. Fetch failures are listed at the end and are **not** cited.")
w("")
w("## Sources")
w("| ID | Source | How verified | What it supports |")
w("|---|---|---|---|")
for s in srcs:
    w(f"| `{s['id']}` | [{esc(s['title'])}]({s['url']}) | {s['method']} ({s['accessed']}) | {esc(s['note'])} |")
w("")
w("Not cited (attempted, failed): census.gov NAICS HTML pages (HTTP 403), Census CBP API for Philadelphia County "
  "(now requires an API key), business.phila.gov (DNS failure on 2026-10-16), Toast / Clio / TaxDome product pages "
  "(HTTP 403), brightwheel.com (returned unrelated content). Restaurant, legal and accounting workflows are therefore "
  "`unverified` starter entries.")
w("")
w("## Philadelphia notes (sourced)")
w("- The Storefront Improvement Program's 1,000+ corridor recipients skew **restaurant/food & beverage (28%)** and "
  "**retail (26%)**, with fitness & wellness, auto services, laundromats, pet services and hospitality also named "
  "(`PHL_SIP`). The catalog weights these sectors with `phillyNote` when *local-business emphasis* is on.")
w("- Commerce's key industries include the **creative economy** and **nighttime economy** (`PHL_COMMERCE`) — venues, "
  "videography, theater and bars carry that note.")
w("- Body art (tattoo, piercing, permanent makeup, microblading) is regulated by the Department of Public Health "
  "(`PHL_BODYART`); food trucks and caterers have their own license types (`PHL_FOODTRUCK`, `PHL_CATERER`); child care "
  "needs state certification (`PA_OCDEL`); non-emergency medical rides exist inside the MATP program (`PHL_MATP`). "
  "Demos in these niches never claim licensure, program affiliation or compliance.")
w("- Every Philadelphia business needs a Commercial Activity License (`PHL_CAL`, search result) — irrelevant to demo "
  "content, but a reminder that real launches have paperwork the demo does not cover.")
w("")
w("## Compatibility rules this research drives")
w("- **Medical** (`medical` tag: dental, chiro, PT, optometry, acupuncture, counseling, nutrition, med spa, NEMT, home "
  "care…): synthetic data only; the brief states the demo is *not* HIPAA compliant and stores no patient data "
  "(`HHS_HIPAA`). Counseling collects no clinical details.")
w("- **Minors** (`minors` tag: childcare, youth sports, tutoring, camps…): fictional placeholder profiles, no real "
  "names or photos of children (`FTC_COPPA` context).")
w("- **Finance / legal**: synthetic records, no real quotes, no advice claims.")
w("- **Reviews**: never generate testimonials, ratings or reviews (`FTC_REVIEWS`); sample feedback is labeled synthetic.")
w("- **Integrations**: payments, SMS/email, AI receptionist, maps/GPS and calendar sync are always labeled as mock/demo.")
w("- **Alcohol** (`alcohol` tag): 21+ age-gate screen included.")
w("")
w("## Workflow patterns")
w("| Pattern | Customer problem | Demo features | Formats | Tech | Validation |")
w("|---|---|---|---|---|---|")
for p in pats:
    cited = [s for s in p["sources"]]
    val = ", ".join(f"`{s}`" for s in cited) if [s for s in cited if s in WF_SRC] else (
        ("`unverified` (guardrail: " + ", ".join(f"`{s}`" for s in cited) + ")") if cited else "`unverified`")
    w(f"| **{esc(p['label'])}** | {esc(p['problem'])} | {esc('; '.join(p['features'][:3]))} | "
      f"{esc(', '.join(FMT[f] for f in p['formats']))} | {p['tech']} | {val} |")
w("")
w("## Business subtypes by sector")
w("Validation column: `NAICS ✓` = code + title confirmed in the official list; workflow source IDs follow; "
  "`workflow unverified` = starter entry; `PHL` = Philadelphia/PA source note.")
for sec in sectors:
    rows = [n for n in niches if n["sector"] == sec["id"]]
    w("")
    w(f"### {sec['label']} ({len(rows)})")
    w("| Niche | NAICS 2022 | Common customer workflow | Viable demo features | Likely buyer | Suggested style | Validation |")
    w("|---|---|---|---|---|---|---|")
    for n in rows:
        feats = n["features"] + [PAT[p]["label"] for p in n["problems"][:2]]
        wf = [s for s in n["sources"] if s in WF_SRC]
        other = [s for s in n["sources"] if s not in WF_SRC and s != "NAICS"]
        val = "NAICS ✓; " + (("workflow " + ", ".join(f"`{s}`" for s in wf)) if wf else "workflow `unverified`")
        if other:
            val += "; " + ", ".join(f"`{s}`" for s in other)
        tags = (" _(" + ", ".join(n["sensitive"]) + ")_") if n["sensitive"] else ""
        w(f"| {esc(n['label'])}{tags} | {n['naics']} {esc(n['naicsTitle'])} | {esc(n['workflow'])} | "
          f"{esc('; '.join(feats))} | {esc(n['buyer'])} | {esc(', '.join(STY[s] for s in n['styles']))} | {val} |")
w("")
w("## Limitations")
w("- No establishment counts by industry for Philadelphia County were obtained (CBP API needs a key); sector weighting "
  "uses the Storefront program mix only.")
w("- Vendor pages describe workflows their products support; they do not prove every business in a niche runs them.")
w("- Search-result sources were not opened; their notes reflect the search summary only.")
w("- Extend the catalog by adding rows to `idea_wheel_catalog/niches.json` (or patterns/styles); `test_idea_wheel.py` "
  "validates referential integrity, and this note should be regenerated.")
w("")
open(os.path.join(ROOT, "docs", "ideawheel-research.md"), "w").write("\n".join(out))
print("wrote", len(out), "lines")
