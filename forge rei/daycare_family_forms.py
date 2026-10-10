"""Family Contact Form PDFs — dashboard read side.

The form project (``daycare-fillout-form`` on Vercel) renders one PDF per submission
into a PRIVATE Blob store and exposes a bearer-key read endpoint
(``/api/family-forms``). This box can't read Blob itself, so it reads through that
endpoint: ``view()`` lists, ``fetch_pdf()`` streams one file.

Config (``forge-daycare/config/daycare.env`` — never committed, never logged):
    FAMILY_FORMS_READ_KEY   shared bearer key (same value as the Vercel env var)
    FAMILY_FORMS_URL        optional override of the endpoint below

Stdlib only. Nothing is stored here; the Blob store is the system of record.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_URL = "https://daycare-fillout-form.vercel.app/api/family-forms"
CACHE_SECONDS = 30
TIMEOUT = 20
MAX_PDF_BYTES = 15 * 1024 * 1024

# Same shape submit.js writes (api/_pdf.js PATH_RE). Anything else is refused before
# it ever reaches the network.
PATH_RE = re.compile(
    r"^family-forms/(atob|amt)/\d{4}-\d{2}/\d{8}T\d{6}Z__[A-Za-z0-9]+__[A-Za-z0-9_]+__[A-Za-z0-9_]+\.pdf$"
)
BRAND_LABEL = {"atob": "A Touch of Blessings", "amt": "A Mother's Touch"}

_LOCK = threading.Lock()
_cache: dict = {"at": 0.0, "forms": None}


class FormsError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _cfg(env: dict) -> tuple[str, str]:
    return (env.get("FAMILY_FORMS_URL") or DEFAULT_URL).rstrip("/"), (env.get("FAMILY_FORMS_READ_KEY") or "").strip()


def _get(url: str, key: str, limit: int) -> bytes:
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {key}", "Accept": "*/*", "User-Agent": "forge-reios/family-forms"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read(limit + 1)
    except urllib.error.HTTPError as e:
        raise FormsError(404 if e.code == 404 else 502, "Form not found" if e.code == 404 else "Forms store unavailable") from None
    except Exception:  # noqa: BLE001 — never leak the URL, key, or upstream body
        raise FormsError(502, "Forms store unavailable") from None
    if len(body) > limit:
        raise FormsError(502, "Form too large")
    return body


def view(env: dict, now: float | None = None) -> dict:
    """List of submitted forms, newest first. Cached 30s; serves the last good list
    (flagged stale) when the store is briefly unreachable."""
    now = now or time.time()
    url, key = _cfg(env)
    if not key:
        return {"ok": True, "configured": False, "forms": [],
                "hint": "Add FAMILY_FORMS_READ_KEY to forge-daycare/config/daycare.env on the box."}
    with _LOCK:
        if _cache["forms"] is not None and now - _cache["at"] < CACHE_SECONDS:
            return {"ok": True, "configured": True, "forms": _cache["forms"]}
    try:
        data = json.loads(_get(url, key, 4 * 1024 * 1024).decode("utf-8"))
        forms = [f for f in (data.get("forms") or []) if isinstance(f, dict) and PATH_RE.match(str(f.get("path") or ""))]
        for f in forms:
            f["brand_label"] = BRAND_LABEL.get(f.get("brand"), "")
    except (FormsError, ValueError) as e:
        with _LOCK:
            stale = _cache["forms"]
        if stale is not None:
            return {"ok": True, "configured": True, "forms": stale, "stale": True}
        return {"ok": True, "configured": True, "forms": [], "error": getattr(e, "message", "Forms store unavailable")}
    with _LOCK:
        _cache.update(at=now, forms=forms)
    return {"ok": True, "configured": True, "forms": forms}


def fetch_pdf(env: dict, path: str) -> bytes:
    url, key = _cfg(env)
    if not key:
        raise FormsError(503, "Family Forms is not configured")
    if not PATH_RE.match(str(path or "")):
        raise FormsError(404, "Form not found")
    body = _get(f"{url}?{urllib.parse.urlencode({'path': path})}", key, MAX_PDF_BYTES)
    if not body.startswith(b"%PDF-"):
        raise FormsError(502, "Forms store returned an unexpected file")
    return body


def download_name(path: str) -> str:
    """ATOB-Family-Form_Maria_Lopez_2026-10-09.pdf — ASCII, safe in a header."""
    m = re.match(r"^family-forms/(atob|amt)/\d{4}-\d{2}/(\d{4})(\d{2})(\d{2})T\d{6}Z__[A-Za-z0-9]+__([A-Za-z0-9_]+)__", path or "")
    if not m:
        return "Family-Form.pdf"
    brand, y, mo, d, child = m.groups()
    return f"{brand.upper()}-Family-Form_{child}_{y}-{mo}-{d}.pdf"
