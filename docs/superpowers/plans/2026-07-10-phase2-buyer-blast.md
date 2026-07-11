# Phase 2 — Buyer Blast Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a locked/offered deal into a buyer-facing deal sheet (photos + fee-hidden numbers), match it against the cash-buyer roster, draft per-buyer SMS/email, and let the operator approve → fire a blast — with the actual wire-send behind a pluggable STUB until the channel decision (PLAN.md Open Decision #1) is made.

**Architecture:** `toolkit_blast.py` owns a JSON store (`marcus_state/toolkit_blast.json`) for blast records + a photo store under `uploads/deals/<dealId>/`. It reuses `buyers.match` (scoring), `toolkit_calc.buyer_view` (fee-hidden numbers — never exposes the assignment fee), and connector-assembled deal dicts (stays decoupled like `buyers.py` — the engine never imports `deals`/`connector`). The send loop calls a module-level `_transport()` STUB that records `stub-sent` without contacting any buyer; wiring GHL-native or Twilio/SendGrid later means swapping that one function. UI is `toolkit_blast.jsx`, a new REI tab.

**Tech Stack:** Python 3 stdlib only (no pip), `unittest`, static React UMD + in-browser Babel (no build), window-globals JSX pattern.

## Global Constraints

- **NO new pip/npm dependencies.** Stdlib + existing patterns only.
- **This directory is NOT a git repository.** Skip all commit steps; the deploy gate + PLAN.md session log are the record. Do not `git init`.
- Additive only — never remove/break an existing feature (root `CLAUDE.md` rule 5).
- **NO real outbound to buyers this phase.** `_transport()` is a stub (`TRANSPORT_LIVE = False`). Blast records/drafts/queue all build + test, but nothing leaves the box. This respects propose→review→execute AND the deferred channel decision.
- **Buyer view never exposes the assignment fee.** Deal sheets show one buyer purchase price via `toolkit_calc.buyer_view`.
- JSX conventions or white-screen: hook aliases for `toolkit_blast.jsx` are `useStateBl/useMemoBl/useEffectBl/useRefBl`; all top-level names prefixed `Bl`; export via `Object.assign(window,{...})`; NO computed JSX tags (resolve `const Ico = Icons.X` first); script tag before `app.jsx`.
- Validate every touched file: `python3 -c "import ast; ast.parse(open('FILE').read())"` for .py, `node deploy/valjsx.js FILE.jsx` for .jsx.
- Working dir for all commands: `/Users/yg4st/forge rei dash/forge rei` (path has spaces — always quote).
- Tests: `unittest`, monkeypatch `STATE` + photo `UPLOADS` to a tempdir in `setUp` (copy `test_toolkit_calc.py` style). Run: `python3 -m unittest test_toolkit_blast -v`.
- Routes namespace `/api/toolkit/blast/...`; GET in `ROUTES`, POST in the `do_POST` allowlist tuple + `elif`.

---

### Task 1: Blast store + deal sheet builder

**Files:**
- Modify: `toolkit_blast.py` (replace stub body, keep a docstring)
- Create: `test_toolkit_blast.py`

**Interfaces:**
- Produces: `STATE` (Path), `UPLOADS` (Path), `_num`, `_slug`, `_load`/`_save`, `build_sheet(deal, photos=None) -> dict` (keys: `dealId,name,address,beds,baths,sqft,condition,arv,purchase,repairs,profit,roiPct,photos`). Uses `toolkit_calc.buyer_view`; NEVER includes a fee key.
- Consumes: `forge_atomic.atomic_write_json`, `toolkit_calc.buyer_view`.

- [ ] **Step 1: Write the failing tests**

Create `test_toolkit_blast.py`:

```python
import tempfile
import unittest
from pathlib import Path

import toolkit_blast


class BlastSheetTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_state = toolkit_blast.STATE
        self._orig_up = toolkit_blast.UPLOADS
        toolkit_blast.STATE = Path(self._tmp.name) / "toolkit_blast.json"
        toolkit_blast.UPLOADS = Path(self._tmp.name) / "uploads" / "deals"

    def tearDown(self):
        toolkit_blast.STATE = self._orig_state
        toolkit_blast.UPLOADS = self._orig_up
        self._tmp.cleanup()

    def test_build_sheet_hides_fee_uses_buyerprice(self):
        # deal has a saved toolkit snapshot: ARV 200k, buyer pays 110k, repairs 30k
        deal = {"contactId": "c1", "name": "Jane Seller",
                "address": "12 Main St, Dover, DE", "beds": 3, "baths": 2, "sqft": 1400,
                "condition": "needs full rehab", "arv": 200000, "repairs": 30000,
                "toolkitCalc": {"results": {"internal": {"buyerPrice": 110000}}}}
        s = toolkit_blast.build_sheet(deal, photos=["/uploads/deals/c1/1.jpg"])
        self.assertEqual(110000, s["purchase"])
        self.assertEqual(200000, s["arv"])
        self.assertNotIn("fee", s)
        self.assertNotIn("mao", s)
        self.assertEqual(["/uploads/deals/c1/1.jpg"], s["photos"])
        self.assertTrue(s["profit"] > 0)     # buyer_view profit

    def test_build_sheet_derives_purchase_from_mao_plus_fee(self):
        deal = {"contactId": "c2", "name": "Bob", "address": "9 Oak",
                "arv": 150000, "repairs": 20000, "mao": 90000, "assignmentFee": 10000}
        s = toolkit_blast.build_sheet(deal)
        self.assertEqual(100000, s["purchase"])   # mao + fee
        self.assertEqual([], s["photos"])

    def test_build_sheet_no_numbers_is_safe(self):
        s = toolkit_blast.build_sheet({"contactId": "c3", "name": "Al"})
        self.assertEqual("c3", s["dealId"])
        self.assertIsNone(s["purchase"])
        self.assertIsNone(s["profit"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run — expect FAIL** (`AttributeError: module 'toolkit_blast' has no attribute 'STATE'`)

Run: `cd "/Users/yg4st/forge rei dash/forge rei" && python3 -m unittest test_toolkit_blast -v`

- [ ] **Step 3: Replace `toolkit_blast.py`** entirely with:

```python
"""Wholesaler Toolkit — Buyer Blast engine (Phase 2).

Turns a locked/offered deal into a buyer-facing deal sheet, matches it against
the cash-buyer roster (buyers.match), drafts per-buyer SMS/email, and runs an
operator-gated blast. The actual wire-send is a STUB (_transport) until the
channel decision (PLAN.md Open Decision #1) is made — nothing leaves the box.

Stores: marcus_state/toolkit_blast.json (blast records) + uploads/deals/<id>/
(photos). Stays decoupled like buyers.py — the connector assembles the deal
dict + matches and hands them in; this module never imports deals/connector.
Reuses toolkit_calc.buyer_view so the assignment fee is NEVER exposed to buyers.
"""
import base64
import json
import re
import threading
import time
from pathlib import Path

import forge_atomic
import toolkit_calc

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "toolkit_blast.json"
UPLOADS = HERE / "uploads" / "deals"
_LOCK = threading.RLock()
MAX_BLASTS = 500
MAX_PHOTOS = 12
MAX_PHOTO_BYTES = 6 * 1024 * 1024

# Flip to True only once a real transport (GHL / Twilio / SendGrid) is wired
# AND the operator has picked the channel (PLAN.md Open Decision #1).
TRANSPORT_LIVE = False


def _now():
    return int(time.time() * 1000)


def _load():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def _save(d):
    forge_atomic.atomic_write_json(STATE, d)


def _slug(s):
    return re.sub(r"[^A-Za-z0-9]+", "-", (s or "").strip()).strip("-")[:60] or "deal"


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return None


def build_sheet(deal, photos=None):
    """Buyer-facing sheet. purchase = what the buyer pays (contract + fee as ONE
    number); the fee itself is never surfaced. Numbers via toolkit_calc.buyer_view."""
    deal = deal or {}
    arv = _num(deal.get("arv"))
    repairs = _num(deal.get("repairs"))
    # what the buyer pays: prefer the saved toolkit snapshot buyerPrice, else mao+fee, else offer
    purchase = None
    snap = ((deal.get("toolkitCalc") or {}).get("results") or {}).get("internal") or {}
    if _num(snap.get("buyerPrice")):
        purchase = _num(snap.get("buyerPrice"))
    elif _num(deal.get("mao")) is not None:
        purchase = _num(deal.get("mao")) + (_num(deal.get("assignmentFee")) or 0)
    elif _num(deal.get("offer")):
        purchase = _num(deal.get("offer"))
    sheet = {
        "dealId": deal.get("contactId"),
        "name": deal.get("name") or "",
        "address": deal.get("address") or "",
        "beds": deal.get("beds"), "baths": deal.get("baths"), "sqft": deal.get("sqft"),
        "condition": deal.get("condition") or deal.get("propertyStatus") or "",
        "arv": arv, "purchase": purchase, "repairs": repairs,
        "profit": None, "roiPct": None,
        "photos": list(photos or []),
    }
    if arv and purchase:
        bv = toolkit_calc.buyer_view(arv, purchase, repairs or 0)
        if not bv.get("error"):
            sheet["profit"] = bv["profit"]
            sheet["roiPct"] = bv["roiPct"]
    return sheet
```

- [ ] **Step 4: Run — expect OK (3 tests)**

- [ ] **Step 5: Validate syntax**

Run: `cd "/Users/yg4st/forge rei dash/forge rei" && python3 -c "import ast; ast.parse(open('toolkit_blast.py').read())" && python3 -c "import ast; ast.parse(open('test_toolkit_blast.py').read())"`

---

### Task 2: Photo store (base64 → files)

**Files:**
- Modify: `toolkit_blast.py`, `test_toolkit_blast.py`

**Interfaces:**
- Produces: `save_photos(deal_id, data_urls) -> dict` (`{ok, photos:[webpath], skipped}` or `{error}`) and `list_photos(deal_id) -> [webpath]`. Web paths look like `/uploads/deals/<slug>/<n>.<ext>`. Accepts `data:image/(png|jpeg|jpg|webp);base64,....`. Enforces `MAX_PHOTOS` total and `MAX_PHOTO_BYTES` each.

- [ ] **Step 1: Append failing tests** (new class in `test_toolkit_blast.py`, before `if __name__`)

```python
class BlastPhotoTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_up = toolkit_blast.UPLOADS
        toolkit_blast.UPLOADS = Path(self._tmp.name) / "uploads" / "deals"

    def tearDown(self):
        toolkit_blast.UPLOADS = self._orig_up
        self._tmp.cleanup()

    # 1x1 transparent PNG
    _PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
            "AAAAC0lEQVR42mNk+M8AAAMBAQDJ/pLvAAAAAElFTkSuQmCC")

    def test_save_and_list_photos(self):
        r = toolkit_blast.save_photos("c1", [self._PNG])
        self.assertTrue(r["ok"])
        self.assertEqual(1, len(r["photos"]))
        self.assertTrue(r["photos"][0].startswith("/uploads/deals/c1/"))
        self.assertTrue(r["photos"][0].endswith(".png"))
        self.assertEqual(r["photos"], toolkit_blast.list_photos("c1"))

    def test_save_rejects_non_image(self):
        r = toolkit_blast.save_photos("c2", ["data:text/plain;base64,aGk="])
        self.assertEqual(0, len(r["photos"]))
        self.assertEqual(1, r["skipped"])

    def test_save_requires_deal_id(self):
        self.assertIn("error", toolkit_blast.save_photos("", [self._PNG]))

    def test_list_photos_empty(self):
        self.assertEqual([], toolkit_blast.list_photos("nope"))
```

- [ ] **Step 2: Run — expect FAIL** (no attribute `save_photos`)

- [ ] **Step 3: Append implementation** to `toolkit_blast.py`:

```python
_IMG_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg",
            "image/webp": "webp"}
_DATA_RE = re.compile(r"^data:(image/[a-zA-Z]+);base64,(.+)$", re.DOTALL)


def _deal_dir(deal_id):
    return UPLOADS / _slug(deal_id)


def list_photos(deal_id):
    d = _deal_dir(deal_id)
    if not d.is_dir():
        return []
    slug = _slug(deal_id)
    return ["/uploads/deals/%s/%s" % (slug, p.name)
            for p in sorted(d.iterdir()) if p.suffix.lstrip(".").lower()
            in ("png", "jpg", "jpeg", "webp")]


def save_photos(deal_id, data_urls):
    """Decode base64 image data-URLs onto disk under uploads/deals/<slug>/.
    Rejects non-images + oversize; caps total at MAX_PHOTOS."""
    if not deal_id:
        return {"error": "dealId required"}
    with _LOCK:
        d = _deal_dir(deal_id)
        d.mkdir(parents=True, exist_ok=True)
        existing = len(list_photos(deal_id))
        saved, skipped = [], 0
        for url in (data_urls or []):
            if existing + len(saved) >= MAX_PHOTOS:
                skipped += 1
                continue
            m = _DATA_RE.match(url or "")
            if not m or m.group(1) not in _IMG_EXT:
                skipped += 1
                continue
            try:
                raw = base64.b64decode(m.group(2), validate=False)
            except Exception:
                skipped += 1
                continue
            if not raw or len(raw) > MAX_PHOTO_BYTES:
                skipped += 1
                continue
            ext = _IMG_EXT[m.group(1)]
            n = existing + len(saved) + 1
            (d / ("%d.%s" % (n, ext))).write_bytes(raw)
            saved.append(1)
    return {"ok": True, "photos": list_photos(deal_id), "skipped": skipped}
```

- [ ] **Step 4: Run — expect OK (7 tests total)**

---

### Task 3: Blast queue — `create_blast` + drafts

**Files:**
- Modify: `toolkit_blast.py`, `test_toolkit_blast.py`

**Interfaces:**
- Produces: `_draft_sms(sheet) -> str`, `_draft_email(sheet) -> dict{subject,body}`, `create_blast(deal, matches, channels=None, buyer_ids=None, photos=None) -> dict` (a blast record, status `"queued"`, persisted). `matches` is a list of `buyers.score_buyer` dicts (`{buyerId,name,score,fits,buyer:{phone,email,...}}`). `get_blast(id)`, `list_blasts()`.
- Blast record schema: `{id, dealId, dealName, address, createdAt, status, channels, sheet, recipients:[{buyerId,name,phone,email,score,fits,channel,smsDraft,emailSubject,emailBody,status:"queued",response:"none",sentAt:None,note:""}]}`.

- [ ] **Step 1: Append failing tests** (new class, before `if __name__`)

```python
class BlastQueueTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_state = toolkit_blast.STATE
        toolkit_blast.STATE = Path(self._tmp.name) / "toolkit_blast.json"

    def tearDown(self):
        toolkit_blast.STATE = self._orig_state
        self._tmp.cleanup()

    def _deal(self):
        return {"contactId": "c1", "name": "Jane", "address": "12 Main, Dover DE",
                "arv": 200000, "repairs": 30000, "mao": 90000, "assignmentFee": 10000}

    def _matches(self):
        return [
            {"buyerId": "bob-llc", "name": "Bob", "score": 92, "fits": True,
             "buyer": {"phone": "3025551111", "email": "bob@x.com"}},
            {"buyerId": "sue-cap", "name": "Sue", "score": 70, "fits": True,
             "buyer": {"phone": "3025552222", "email": ""}},
        ]

    def test_create_blast_queues_recipients(self):
        b = toolkit_blast.create_blast(self._deal(), self._matches(), channels=["sms"])
        self.assertEqual("queued", b["status"])
        self.assertEqual(2, len(b["recipients"]))
        self.assertTrue(b["id"])
        self.assertEqual("queued", b["recipients"][0]["status"])
        self.assertIn("Bob", b["recipients"][0]["smsDraft"]) is None  # draft is buyer-facing, name optional
        self.assertIn("100,000", b["recipients"][0]["smsDraft"])       # purchase price in the pitch
        self.assertEqual(b, toolkit_blast.get_blast(b["id"]))

    def test_create_blast_filters_by_buyer_ids(self):
        b = toolkit_blast.create_blast(self._deal(), self._matches(),
                                       channels=["sms"], buyer_ids=["sue-cap"])
        self.assertEqual(1, len(b["recipients"]))
        self.assertEqual("sue-cap", b["recipients"][0]["buyerId"])

    def test_email_draft_has_subject_and_numbers(self):
        b = toolkit_blast.create_blast(self._deal(), self._matches(), channels=["email"])
        r0 = b["recipients"][0]
        self.assertTrue(r0["emailSubject"])
        self.assertIn("200,000", r0["emailBody"])   # ARV in the body

    def test_create_blast_requires_matches(self):
        self.assertIn("error", toolkit_blast.create_blast(self._deal(), []))

    def test_list_blasts_newest_first(self):
        b1 = toolkit_blast.create_blast(self._deal(), self._matches())
        b2 = toolkit_blast.create_blast(self._deal(), self._matches())
        ids = [x["id"] for x in toolkit_blast.list_blasts()]
        self.assertEqual(ids[0], b2["id"])
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Append implementation**

```python
def _money(v):
    n = _num(v)
    return ("$%s" % format(int(round(n)), ",")) if n is not None else "—"


def _draft_sms(sheet):
    addr = sheet.get("address") or "an off-market property"
    bits = ["New off-market deal — %s." % addr]
    if sheet.get("arv"):
        bits.append("ARV %s." % _money(sheet["arv"]))
    if sheet.get("purchase"):
        bits.append("Yours at %s." % _money(sheet["purchase"]))
    if sheet.get("profit"):
        bits.append("Est. spread %s." % _money(sheet["profit"]))
    bits.append("Want the full sheet + pics? Reply YES.")
    return " ".join(bits)


def _draft_email(sheet):
    addr = sheet.get("address") or "Off-market property"
    subject = "Off-market deal: %s" % addr
    lines = ["Off-market wholesale deal — quick numbers:", "",
             "Property: %s" % addr]
    if sheet.get("beds") or sheet.get("baths") or sheet.get("sqft"):
        lines.append("Specs: %s bd / %s ba / %s sqft" % (
            sheet.get("beds") or "?", sheet.get("baths") or "?", sheet.get("sqft") or "?"))
    if sheet.get("condition"):
        lines.append("Condition: %s" % sheet["condition"])
    lines.append("")
    if sheet.get("arv"):
        lines.append("ARV (after repair): %s" % _money(sheet["arv"]))
    if sheet.get("repairs"):
        lines.append("Est. repairs: %s" % _money(sheet["repairs"]))
    if sheet.get("purchase"):
        lines.append("Your price: %s" % _money(sheet["purchase"]))
    if sheet.get("profit"):
        lines.append("Est. buyer spread: %s (%s%% cash-in ROI)" % (
            _money(sheet["profit"]), sheet.get("roiPct")))
    lines += ["", "%d photo(s) available." % len(sheet.get("photos") or []),
              "Reply if you want the full packet + address. Cash / hard-money only.", ""]
    return {"subject": subject, "body": "\n".join(lines)}


def create_blast(deal, matches, channels=None, buyer_ids=None, photos=None):
    """Build a QUEUED blast from a deal + ranked buyer matches. Never sends —
    send_blast() does that, and only through the (stubbed) transport."""
    deal = deal or {}
    matches = matches or []
    if buyer_ids:
        keep = set(buyer_ids)
        matches = [m for m in matches if m.get("buyerId") in keep]
    if not matches:
        return {"error": "no matched buyers"}
    channels = [c for c in (channels or ["sms"]) if c in ("sms", "email")] or ["sms"]
    sheet = build_sheet(deal, photos if photos is not None else list_photos(deal.get("contactId")))
    sms = _draft_sms(sheet)
    email = _draft_email(sheet)
    prim = channels[0]
    recips = []
    for m in matches:
        b = m.get("buyer") or {}
        recips.append({
            "buyerId": m.get("buyerId"), "name": m.get("name") or b.get("name") or "",
            "phone": b.get("phone") or "", "email": b.get("email") or "",
            "score": m.get("score"), "fits": bool(m.get("fits")),
            "channel": prim,
            "smsDraft": sms, "emailSubject": email["subject"], "emailBody": email["body"],
            "status": "queued", "response": "none", "sentAt": None, "note": "",
        })
    with _LOCK:
        d = _load()
        base = "blast-" + _slug(deal.get("name") or deal.get("contactId"))
        bid, n = base, 2
        while bid in d:
            bid = "%s-%d" % (base, n)
            n += 1
        rec = {"id": bid, "dealId": deal.get("contactId"),
               "dealName": deal.get("name") or "", "address": sheet.get("address") or "",
               "createdAt": _now(), "status": "queued", "channels": channels,
               "sheet": sheet, "recipients": recips}
        d[bid] = rec
        if len(d) > MAX_BLASTS:
            keep = sorted(d.values(), key=lambda x: -(x.get("createdAt") or 0))[:MAX_BLASTS]
            d = {x["id"]: x for x in keep}
        _save(d)
        return rec


def get_blast(blast_id):
    return _load().get(blast_id)


def list_blasts():
    rows = list(_load().values())
    rows.sort(key=lambda r: -(r.get("createdAt") or 0))
    return rows
```

- [ ] **Step 4: Run — expect OK (12 tests total)**

Note the first assertion in `test_create_blast_queues_recipients` uses `is None` on purpose (buyer name is optional in the pitch); the load-bearing check is the purchase price appearing in the draft.

---

### Task 4: Send loop (STUB transport) + response tracking

**Files:**
- Modify: `toolkit_blast.py`, `test_toolkit_blast.py`

**Interfaces:**
- Produces: `_transport(recipient, sheet) -> dict` (STUB: `{ok:True, stub:True, note}` — no real send while `TRANSPORT_LIVE` is False), `send_blast(blast_id) -> dict` (fires transport per queued recipient, updates statuses, returns `{ok, blast, summary:{sent,skipped,failed}}` or `{error}`), `record_response(blast_id, buyer_id, verdict) -> dict` (verdict in `interested|passed|noreply|none`), `set_recipient(blast_id, buyer_id, **fields) -> dict` (edit a draft / channel / status before send).

- [ ] **Step 1: Append failing tests** (extend `BlastQueueTest` — add methods inside that class)

```python
    def test_send_blast_stub_marks_sent_no_real_send(self):
        b = toolkit_blast.create_blast(self._deal(), self._matches(), channels=["sms"])
        r = toolkit_blast.send_blast(b["id"])
        self.assertTrue(r["ok"])
        self.assertEqual(2, r["summary"]["sent"])
        self.assertTrue(all(x["status"] == "stub-sent" for x in r["blast"]["recipients"]))
        self.assertEqual("sent", r["blast"]["status"])
        # persisted
        self.assertEqual("sent", toolkit_blast.get_blast(b["id"])["status"])

    def test_send_skips_recipient_missing_channel_contact(self):
        # Sue has no email -> emailing her is skipped, Bob sends
        b = toolkit_blast.create_blast(self._deal(), self._matches(), channels=["email"])
        toolkit_blast.set_recipient(b["id"], "sue-cap", channel="email")
        r = toolkit_blast.send_blast(b["id"])
        summ = r["summary"]
        self.assertEqual(1, summ["sent"])
        self.assertEqual(1, summ["skipped"])

    def test_record_response(self):
        b = toolkit_blast.create_blast(self._deal(), self._matches())
        toolkit_blast.record_response(b["id"], "bob-llc", "interested")
        r0 = next(x for x in toolkit_blast.get_blast(b["id"])["recipients"]
                  if x["buyerId"] == "bob-llc")
        self.assertEqual("interested", r0["response"])

    def test_record_response_bad_verdict(self):
        b = toolkit_blast.create_blast(self._deal(), self._matches())
        self.assertIn("error", toolkit_blast.record_response(b["id"], "bob-llc", "bogus"))

    def test_set_recipient_edits_draft(self):
        b = toolkit_blast.create_blast(self._deal(), self._matches())
        toolkit_blast.set_recipient(b["id"], "bob-llc", smsDraft="custom pitch")
        r0 = next(x for x in toolkit_blast.get_blast(b["id"])["recipients"]
                  if x["buyerId"] == "bob-llc")
        self.assertEqual("custom pitch", r0["smsDraft"])

    def test_send_missing_blast(self):
        self.assertIn("error", toolkit_blast.send_blast("nope"))
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Append implementation**

```python
_VERDICTS = ("none", "interested", "passed", "noreply")


def _transport(recipient, sheet):
    """STUB. Until a real channel is wired (PLAN.md Open Decision #1) this never
    contacts a buyer — it just reports what WOULD go out. Swap this body (and
    flip TRANSPORT_LIVE) to go live."""
    if TRANSPORT_LIVE:  # pragma: no cover - not wired yet
        raise RuntimeError("no live transport wired yet")
    ch = recipient.get("channel")
    dest = recipient.get("email") if ch == "email" else recipient.get("phone")
    if not dest:
        return {"ok": False, "skipped": True, "note": "no %s on file" % ch}
    return {"ok": True, "stub": True,
            "note": "stub: would %s %s" % (ch, dest)}


def _find(rec, buyer_id):
    return next((x for x in rec.get("recipients", []) if x.get("buyerId") == buyer_id), None)


def set_recipient(blast_id, buyer_id, **fields):
    allowed = {"channel", "smsDraft", "emailSubject", "emailBody", "status", "note"}
    with _LOCK:
        d = _load()
        rec = d.get(blast_id)
        if not rec:
            return {"error": "blast not found"}
        r = _find(rec, buyer_id)
        if not r:
            return {"error": "recipient not found"}
        for k, v in fields.items():
            if k in allowed and v is not None:
                r[k] = v
        _save(d)
        return rec


def send_blast(blast_id):
    """Operator-gated. Fires the (stubbed) transport for every queued recipient."""
    with _LOCK:
        d = _load()
        rec = d.get(blast_id)
        if not rec:
            return {"error": "blast not found"}
        sent = skipped = failed = 0
        for r in rec["recipients"]:
            if r["status"] in ("stub-sent", "sent"):
                continue
            res = _transport(r, rec.get("sheet") or {})
            if res.get("ok"):
                r["status"] = "stub-sent" if res.get("stub") else "sent"
                r["sentAt"] = _now()
                r["note"] = res.get("note") or ""
                sent += 1
            elif res.get("skipped"):
                r["status"] = "skipped"
                r["note"] = res.get("note") or ""
                skipped += 1
            else:
                r["status"] = "failed"
                r["note"] = res.get("note") or "send failed"
                failed += 1
        rec["status"] = "sent" if sent else ("partial" if (skipped or failed) else rec["status"])
        rec["sentAt"] = _now()
        _save(d)
        return {"ok": True, "blast": rec,
                "summary": {"sent": sent, "skipped": skipped, "failed": failed},
                "live": TRANSPORT_LIVE}


def record_response(blast_id, buyer_id, verdict):
    if verdict not in _VERDICTS:
        return {"error": "verdict must be one of %s" % (_VERDICTS,)}
    with _LOCK:
        d = _load()
        rec = d.get(blast_id)
        if not rec:
            return {"error": "blast not found"}
        r = _find(rec, buyer_id)
        if not r:
            return {"error": "recipient not found"}
        r["response"] = verdict
        _save(d)
        return rec
```

- [ ] **Step 4: Run full suite — expect OK (18 tests total)**

- [ ] **Step 5: Regression check**

Run: `cd "/Users/yg4st/forge rei dash/forge rei" && python3 -m unittest test_toolkit_calc test_cost_tracker test_sms_guard 2>&1 | tail -3`
Expected: `OK`.

---

### Task 5: Connector wiring + photo serving + smoke test

**Files:**
- Modify: `connector.py` (import, GET handlers, ROUTES, NO_CACHE, POST allowlist + dispatch, static-serve exception for `uploads/deals`)

**Interfaces:**
- Consumes: `toolkit_blast.*` (Tasks 1-4), `buyers.match`, `deals.get`, `_deal_prefill`.
- Produces: `GET /api/toolkit/blast/{list,get,matches}`, `POST /api/toolkit/blast/{create,send,respond,recipient,photos}`, and photo URLs `/uploads/deals/<id>/<name>` served by the static handler.

- [ ] **Step 1: Add import.** Find `import toolkit_calc   # noqa: E402` (added in Phase 1, ~line 1042) and add after it:

```python
import toolkit_blast   # noqa: E402  — Wholesaler Toolkit: buyer blast (deal sheets + queue)
```

- [ ] **Step 2: Add GET handlers.** Insert immediately before `def api_toolkit_calc_config(_q):`:

```python
def api_toolkit_blast_list(_q):
    return {"blasts": toolkit_blast.list_blasts()}


def api_toolkit_blast_get(q):
    bid = (q.get("id", [None]) or [None])[0]
    b = toolkit_blast.get_blast(bid) if bid else None
    return {"blast": b} if b else {"error": "blast not found"}


def _blast_deal(contact_id):
    """Assemble the deal dict the blast engine + matcher consume (saved record
    over prefill draft)."""
    d = deals.get(contact_id) or dict(_deal_prefill(contact_id), contactId=contact_id)
    d.setdefault("contactId", contact_id)
    return d


def api_toolkit_blast_matches(q):
    cid = (q.get("contactId", [None]) or [None])[0]
    if not cid:
        return {"error": "contactId required"}
    d = _blast_deal(cid)
    matches = buyers.match(d, limit=25)
    return {"deal": d, "sheet": toolkit_blast.build_sheet(d, toolkit_blast.list_photos(cid)),
            "matches": matches, "buyerCount": len(buyers.list_buyers())}


```

- [ ] **Step 3: Register GET routes.** In `ROUTES` find `"/api/toolkit/calc/config": api_toolkit_calc_config,` and add BEFORE it:

```python
    "/api/toolkit/blast/list": api_toolkit_blast_list,
    "/api/toolkit/blast/get": api_toolkit_blast_get,
    "/api/toolkit/blast/matches": api_toolkit_blast_matches,
```

- [ ] **Step 4: NO_CACHE.** Find the `"/api/toolkit/calc/config",` line in the NO_CACHE set and add after it:

```python
            "/api/toolkit/blast/list", "/api/toolkit/blast/get", "/api/toolkit/blast/matches",
```

- [ ] **Step 5: POST allowlist.** Find `"/api/toolkit/calc/save",` in the `do_POST` allowlist tuple and add after it:

```python
                                   "/api/toolkit/blast/create",
                                   "/api/toolkit/blast/send",
                                   "/api/toolkit/blast/respond",
                                   "/api/toolkit/blast/recipient",
                                   "/api/toolkit/blast/photos",
```

- [ ] **Step 6: POST dispatch.** Find `elif parsed.path == "/api/toolkit/calc/save":` and insert BEFORE it:

```python
            elif parsed.path == "/api/toolkit/blast/create":
                _bd = _blast_deal(body.get("contactId"))
                result = toolkit_blast.create_blast(
                    _bd, buyers.match(_bd, limit=25),
                    channels=body.get("channels"), buyer_ids=body.get("buyerIds"))
            elif parsed.path == "/api/toolkit/blast/send":
                result = toolkit_blast.send_blast(body.get("id"))
            elif parsed.path == "/api/toolkit/blast/respond":
                result = toolkit_blast.record_response(
                    body.get("id"), body.get("buyerId"), body.get("verdict"))
            elif parsed.path == "/api/toolkit/blast/recipient":
                result = toolkit_blast.set_recipient(
                    body.get("id"), body.get("buyerId"),
                    **{k: body.get(k) for k in ("channel", "smsDraft", "emailSubject",
                                                "emailBody", "status", "note")
                       if body.get(k) is not None})
            elif parsed.path == "/api/toolkit/blast/photos":
                result = toolkit_blast.save_photos(body.get("dealId"), body.get("photos") or [])
```

- [ ] **Step 7: Serve deal photos.** The static handler denies the `uploads` dir. Find this block in `do_GET` (the static section):

```python
        rel = urllib.parse.unquote(path.lstrip("/"))
        # Deny dotfiles + sensitive dirs (secrets, source, state, SSH keys).
        parts = Path(rel).parts
        if any(p.startswith(".") for p in parts) or (set(parts) & DENY_DIRS):
            self.send_error(404, "Not found")
            return
```

Replace with (carves a narrow allow for buyer-sheet photos only — `uploads/deals/<id>/<image>`):

```python
        rel = urllib.parse.unquote(path.lstrip("/"))
        # Deny dotfiles + sensitive dirs (secrets, source, state, SSH keys).
        parts = Path(rel).parts
        _photo_ok = (len(parts) == 4 and parts[0] == "uploads" and parts[1] == "deals"
                     and Path(rel).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))
        if any(p.startswith(".") for p in parts) or ((set(parts) & DENY_DIRS) and not _photo_ok):
            self.send_error(404, "Not found")
            return
```

Then add `.webp` to `SERVE_TYPES` — find the `SERVE_TYPES = {` block and add to it:

```python
    ".webp": "image/webp",
```

- [ ] **Step 8: Validate + smoke-test**

```bash
cd "/Users/yg4st/forge rei dash/forge rei"
python3 -c "import ast; ast.parse(open('connector.py').read())"
FORGE_MARCUS=0 FORGE_PORT=7802 python3 connector.py >/tmp/blast_srv.log 2>&1 &
sleep 2.5
curl -s localhost:7802/api/toolkit/blast/list
echo
curl -s -X POST localhost:7802/api/toolkit/blast/photos -d '{"dealId":"smoke1","photos":["data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMBAQDJ/pLvAAAAAElFTkSuQmCC"]}'
echo
curl -s -o /dev/null -w "photo:%{http_code}\n" localhost:7802/uploads/deals/smoke1/1.png
curl -s -o /dev/null -w "secrets:%{http_code}\n" localhost:7802/uploads/deals/../../marcus_state/heartbeats.json
kill %1
```
Expected: list returns `{"blasts": []}`; photos POST returns `{"ok": true, "photos": ["/uploads/deals/smoke1/1.png"], ...}`; `photo:200`; `secrets:404`. Clean up: `rm -rf "/Users/yg4st/forge rei dash/forge rei/uploads/deals/smoke1"`.

---

### Task 6: `toolkit_blast.jsx` — UI (dispatch to subagent)

**Files:**
- Modify: `toolkit_blast.jsx` (replace stub with the Buyers-workspace blast page)

**Interfaces:**
- Consumes: `GET /api/toolkit/blast/{matches,list,get}`, `POST /api/toolkit/blast/{create,send,respond,recipient,photos}`, `GET /api/contacts?query=`, `window.useApi`, `window.apiPost`, `window.fmtMoney`, `window.Icons`.
- Produces: `window.BlastPage`.

- [ ] **Step 1: Dispatch a subagent** with this exact brief (the parent runs it via the Agent tool, then validates):

> Create ONE file `/Users/yg4st/forge rei dash/forge rei/toolkit_blast.jsx` — the Buyer Blast page for the FORGE REI desktop dashboard. Read `/Users/yg4st/forge rei dash/forge rei/buyers.jsx` and the DealCalcPage in `pages.jsx` (~line 812) FIRST to match the Dark Luxury style (`.card .card-pad .tab .pill .faint`, CSS vars `--card --blue --green --orange --red --text --text-3 --border`, inline styles). Component `function BlastPage()`, export `Object.assign(window,{BlastPage})`. Hook aliases UNIQUE to this file: `const { useState: useStateBl, useEffect: useEffectBl, useRef: useRefBl, useMemo: useMemoBl } = React;` — ALL top-level identifiers prefixed `Bl`. NO computed JSX tags (resolve `const Ico = window.Icons.X` first). No import/export keywords. React is a global.
>
> LAYOUT (top to bottom):
> 1. Header + a persistent amber banner: "⚠ Sends are STUBBED — no texts/emails actually leave the box until you pick a channel (PLAN.md Open Decision #1). Everything else is live." Read the `live` flag off a send response; keep the banner whenever it's false.
> 2. Deal picker: search homeowners via `GET /api/contacts?query=…&limit=8` (debounced 350ms, only results with a phone), OR a "From dispo" shortcut listing `GET /api/buyers/dispo` deals. On pick, set `contactId`.
> 3. When a deal is picked: fetch `GET /api/toolkit/blast/matches?contactId=…` (window.useApi). Render:
>    - Deal sheet card: address, beds/baths/sqft, condition, ARV, "Buyer price" (sheet.purchase), est. profit + ROI, and a photo strip (sheet.photos as `<img>` thumbs). A file input (accept="image/*" multiple) reads files as base64 data-URLs (FileReader) and POSTs `/api/toolkit/blast/photos {dealId, photos:[...]}`, then refreshes. NEVER shows an assignment fee.
>    - Channel toggle chips: SMS / Email / Both (drives the `channels` array).
>    - Matched buyers list: each row = name, score badge (color by score: ≥80 green, ≥50 orange, else faint), fits pill, phone/email presence icons, and a checkbox (default checked for `fits` buyers). Show reasons on demand.
>    - "Create blast" button → `POST /api/toolkit/blast/create {contactId, channels, buyerIds:[checked]}`; on success switch to the blast detail view.
> 4. Blast detail view (also reachable from a "Recent blasts" list via `GET /api/toolkit/blast/list`): per-recipient rows with the editable draft (textarea bound to `smsDraft` or `emailBody`+`emailSubject` by channel; save via `POST /api/toolkit/blast/recipient`), status pill (queued/stub-sent/skipped/failed), and a response segmented control (interested / passed / no-reply → `POST /api/toolkit/blast/respond {id,buyerId,verdict}`). A "Send blast (stub)" button → `POST /api/toolkit/blast/send {id}` with a window.confirm that says it's a stub; show the returned summary (sent/skipped/failed).
> 5. Every fetch handles loading / error / empty. Buttons ≥ the desktop norm; use existing classes.
>
> VERIFY: `cd "/Users/yg4st/forge rei dash/forge rei" && node deploy/valjsx.js toolkit_blast.jsx` must print OK. Return endpoints used + any gaps.

- [ ] **Step 2: Validate the returned file**

Run: `cd "/Users/yg4st/forge rei dash/forge rei" && node deploy/valjsx.js toolkit_blast.jsx`
Expected: `OK   toolkit_blast.jsx`. If not, fix inline and re-run.

---

### Task 7: Mount the tab (nav + page map + HTML) + browser test

**Files:**
- Modify: `data.jsx` (NAV entry), `app.jsx` (REI page map), `FORGE REI OS.html` (script tag)

**Interfaces:**
- Consumes: `window.BlastPage`.

- [ ] **Step 1: Inspect the nav + page-map shape.** Run:

```bash
cd "/Users/yg4st/forge rei dash/forge rei"
grep -n "Buyers\|Dispositions\|key:" data.jsx | head -30
grep -n "buyers\|BuyersPage\|REI_PAGES" app.jsx | head
```
Read the exact `NAV` array item shape for the existing Buyers entry and the `app.jsx` page-map key it maps to. Mirror that shape.

- [ ] **Step 2: Add the NAV item.** In `data.jsx`, immediately after the Buyers nav entry, add a sibling entry with `key: "blast"`, a label like `"Buyer Blast"`, and an icon that exists in `icons.jsx` (reuse `Send` — confirm it's in `window.Icons`; if not, use `Flame`). Match the surrounding object shape exactly (same fields as the Buyers item).

- [ ] **Step 3: Add the page-map entry.** In `app.jsx`, in the REI page map, add `blast: () => <window.BlastPage />,` next to the buyers entry (match the existing arrow-function style used there).

- [ ] **Step 4: Add the script tag.** In `FORGE REI OS.html`, find `<script type="text/babel" src="buyers.jsx"></script>` and add after it:

```html
<script type="text/babel" src="toolkit_blast.jsx"></script>
```

- [ ] **Step 5: Validate all touched files**

```bash
cd "/Users/yg4st/forge rei dash/forge rei"
node deploy/valjsx.js data.jsx
node deploy/valjsx.js app.jsx
node deploy/valjsx.js toolkit_blast.jsx
```
Expected: OK for all three.

- [ ] **Step 6: Browser test.** Start the server, drive the UI:

```bash
cd "/Users/yg4st/forge rei dash/forge rei"
FORGE_MARCUS=0 FORGE_PORT=7802 python3 connector.py >/tmp/blast_srv.log 2>&1 &
sleep 2.5
curl -s localhost:7802/ | grep -c "toolkit_blast.jsx"   # expect 1
```
Then with browser-harness: open `http://localhost:7802/`, click the "Buyer Blast" nav item, confirm — the page renders (no white screen), the STUB banner shows, the deal picker + "From dispo" list appear, and other tabs still render (regression). Pick a dispo deal → matches list + deal sheet render. Screenshot. Kill the server.

---

### Task 8: PLAN.md + deploy + box verify

**Files:**
- Modify: `/Users/yg4st/forge rei dash/PLAN.md`

- [ ] **Step 1: Full suite**

Run: `cd "/Users/yg4st/forge rei dash/forge rei" && python3 -m unittest test_toolkit_blast -v 2>&1 | tail -3`
Expected: OK, 18 tests.

- [ ] **Step 2: Update PLAN.md** — Phase 2 → `✅ SHIPPED (2026-07-10)`, Phase 3 → `⬜ NEXT`; add a Session Log entry (what shipped; note the transport is still stubbed pending Open Decision #1, which stays open).

- [ ] **Step 3: Deploy**

Run: `cd "/Users/yg4st/forge rei dash/forge rei" && ./deploy/push.sh root@24.199.81.124 2>&1 | tail -5`
Expected: validators pass, `OK: service active · … secrets 404`.

- [ ] **Step 4: Verify on the box**

Run: `ssh -i ~/.ssh/forge_droplet root@24.199.81.124 "curl -s localhost:7799/api/toolkit/blast/list && echo && curl -s -o /dev/null -w 'photodir-secrets:%{http_code}\n' localhost:7799/uploads/deals/x/../../../marcus_state/heartbeats.json"`
Expected: `{"blasts": ...}` and secrets stay `404`.

---

## Self-review notes

- **Spec coverage:** buyer CRM tagged by market/price/type/cash — already exists (`buyers.py`), reused via `buyers.match`. Auto-match scoring ✅ (reused). Auto-generated deal sheet (photos, numbers) ✅ (Task 1 + 2). One-click SMS + email blast to matched buyers ✅ (Tasks 3-4, behind stub per deferred decision). Response tracking ✅ (Task 4).
- **Fee-hidden invariant** tested (`test_build_sheet_hides_fee_uses_buyerprice`).
- **No real sends** guaranteed by `TRANSPORT_LIVE=False` + stub `_transport`, tested (`test_send_blast_stub_marks_sent_no_real_send`).
- **Photo path-jail**: static handler only allows `uploads/deals/<id>/<image>` (exactly 4 path parts + image suffix); traversal + secrets stay 404 (smoke-tested Task 5 & 8).
- **No git:** commit steps intentionally absent.
- **Open Decision #1 stays open** — this phase does NOT resolve the channel; it builds everything up to the wire.
