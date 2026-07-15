"""higgsfield_io.py — shared Higgsfield image generation for every FORGE ad agent.

Higgsfield is ONE account with ONE API key (Bearer auth). Both Nova (daycare enrollment
ads, via daycare_ads_studio) and Eco (agency client ads, via agency_eco) generate images
through this single helper. Unlike the three GHL sub-accounts — which are separate
customer accounts that MUST stay isolated — Higgsfield is a shared creative tool, so one
key serving multiple agents is correct, not an isolation break.

Key resolution (resolve_key): env var first, then any creds dict a caller passes, then a
scan of the known *.env files. So the operator adds HIGGSFIELD_API_KEY to ONE place
(daycare.env) and every ad agent finds it — no need to duplicate the key per business.

Stdlib only. Pure: generate_image() does the HTTP and returns a dict; it never stores
state, never sends anything outward on its own, never logs the key.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
HF_BASE = "https://platform.higgsfield.ai/v1"
# Verified live 2026-07-15: the text2image "soul" endpoint is the working path. It takes
# {"params": {...}} and returns a job to poll (statuses Queued/InProgress/Completed →
# result images[0].url). The old /v1/image/generate {"model":...} shape 404'd ("Model not
# found") — that endpoint wants registered model UUIDs, not friendly names.
HF_ENDPOINT = os.environ.get("HIGGSFIELD_ENDPOINT", "/v1/text2image/soul")
DEFAULT_MODEL = os.environ.get("HIGGSFIELD_MODEL", "soul")
# width_and_height is a strict enum on Higgsfield's side; 1536x1536 is a verified value.
DEFAULT_SIZE = os.environ.get("HIGGSFIELD_SIZE", "1536x1536")
DEFAULT_QUALITY = os.environ.get("HIGGSFIELD_QUALITY", "1080p")
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")  # past Cloudflare (403 code 1010)

# Where the shared key may live (one paste in any of these works for all agents).
_ENV_CANDIDATES = [
    HERE.parent / "forge-daycare" / "config" / "daycare.env",
    HERE.parent / "forge-agency" / "config" / "agency.env",
    Path("/opt/forge/forge-daycare/config/daycare.env"),
    Path("/opt/forge/forge-agency/config/agency.env"),
]


def _scan_env_files(var: str) -> str:
    for p in _ENV_CANDIDATES:
        try:
            if not p.is_file():
                continue
            for line in p.read_text().splitlines():
                line = line.strip()
                if line.startswith(var + "=") and not line.startswith("#"):
                    v = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if v:
                        return v
        except Exception:
            continue
    return ""


def _resolve(var: str, creds: tuple) -> str:
    v = (os.environ.get(var) or "").strip()
    if v:
        return v
    for c in creds:
        if isinstance(c, dict):
            cv = (c.get(var) or "").strip()
            if cv:
                return cv
    return _scan_env_files(var)


def resolve_key(*creds: dict) -> str:
    """The API Key ID: env HIGGSFIELD_API_KEY → any passed creds dict → *.env scan."""
    return _resolve("HIGGSFIELD_API_KEY", creds)


def resolve_secret(*creds: dict) -> str:
    """The API Key Secret: env HIGGSFIELD_API_SECRET → creds dict → *.env scan."""
    return _resolve("HIGGSFIELD_API_SECRET", creds)


def ready(key: str | None = None, secret: str | None = None) -> bool:
    """True only when BOTH the key id and secret are present — Higgsfield auth is a pair.
    Never claim generation works otherwise."""
    return bool((key or resolve_key()).strip()) and bool((secret or resolve_secret()).strip())


# --- soul endpoint plumbing (submit + poll) ----------------------------------
# HF_BASE already ends in "/v1" and HF_ENDPOINT is a full-from-root path ("/v1/text2image/
# soul"), so build the submit URL from the ORIGIN to avoid a doubled "/v1".
_ORIGIN = HF_BASE.split("/v1", 1)[0] or HF_BASE           # https://platform.higgsfield.ai
_SOUL_URL = _ORIGIN + HF_ENDPOINT                          # …/v1/text2image/soul
# The submit returns a job/job-set id to poll. The exact poll path is best-effort per the
# documented spec and MUST be confirmed against the live Higgsfield API — override via env
# if it differs (e.g. HIGGSFIELD_JOB_URL="https://…/v1/job-sets/{id}").
_JOB_URL_TMPL = os.environ.get("HIGGSFIELD_JOB_URL", _ORIGIN + "/v1/job-sets/{id}")
_POLL_INTERVAL = float(os.environ.get("HIGGSFIELD_POLL_INTERVAL", "3"))
_DONE = {"completed", "complete", "succeeded", "success", "done", "finished", "ready"}
_FAILED = {"failed", "fail", "error", "errored", "canceled", "cancelled", "rejected", "nsfw"}


def _headers(key: str, secret: str) -> dict:
    # Higgsfield sits behind Cloudflare, which 403s (code 1010) the default Python-urllib
    # signature. A real browser UA gets past the bot filter. Auth is a PAIR of headers.
    return {"hf-api-key": key, "hf-secret": secret,
            "Content-Type": "application/json", "Accept": "application/json",
            "User-Agent": _UA}


def _http_json(url: str, key: str, secret: str, data: bytes | None = None,
               method: str = "GET", timeout: int = 30) -> dict:
    req = urllib.request.Request(url, data=data, method=method,
                                 headers=_headers(key, secret))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "ignore")
    return json.loads(raw) if raw.strip() else {}


def _http_err(e: urllib.error.HTTPError) -> str:
    detail = ""
    try:
        detail = e.read().decode("utf-8", "ignore")[:300]
    except Exception:
        pass
    hint = ""
    if getattr(e, "code", None) in (401, 403):
        hint = (" — auth rejected; verify the API Key ID + Secret and, if Higgsfield's docs "
                "name the headers differently, adjust hf-api-key/hf-secret")
    return f"HTTP {getattr(e, 'code', '?')}{hint}: {detail}"


def _deep_find(obj, key_hints: tuple, want_url: bool = False):
    """Iterative walk of an unknown-shape JSON body. Returns the first string value whose
    key matches a hint (for URLs, must be http…). Tolerant of the exact soul response
    nesting, which isn't documented here — so a shape tweak won't silently break us."""
    stack = [obj]
    fallback = None
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                kl = str(k).lower()
                if isinstance(v, str):
                    if want_url:
                        if v.startswith("http"):
                            if any(h in kl for h in key_hints):
                                return v
                            fallback = fallback or v
                    elif any(h in kl for h in key_hints):
                        return v
                elif isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(cur, list):
            for v in cur:
                if isinstance(v, (dict, list)):
                    stack.append(v)
    return fallback


def _find_url(data) -> str | None:
    return _deep_find(data, ("url", "image", "result", "output", "asset"), want_url=True)


def _find_status(data) -> str:
    return (_deep_find(data, ("status", "state")) or "").strip().lower()


def _find_job_id(data) -> str:
    if isinstance(data, dict):
        for k in ("id", "jobSetId", "job_set_id", "jobId", "job_id", "setId"):
            v = data.get(k)
            if isinstance(v, str) and v:
                return v
        for holder in ("jobs", "job_set", "jobSet", "results", "data"):
            arr = data.get(holder)
            if isinstance(arr, list) and arr and isinstance(arr[0], dict):
                for k in ("id", "jobId", "job_id"):
                    v = arr[0].get(k)
                    if isinstance(v, str) and v:
                        return v
    return ""


def _soul_params(prompt: str, model: str, extra: dict | None) -> dict:
    """Build the soul-native params. Callers still pass legacy hints
    ({"quality":"high","resolution":"2k"}) — sanitize so the strict soul enums
    (width_and_height, quality like "1080p") aren't broken by them."""
    params = {"prompt": prompt, "width_and_height": DEFAULT_SIZE, "quality": DEFAULT_QUALITY}
    if model and model != DEFAULT_MODEL:
        params["model"] = model
    if isinstance(extra, dict):
        for k, v in extra.items():
            if k == "resolution":
                continue  # legacy; soul sizes via the width_and_height enum
            if k == "quality" and not (isinstance(v, str) and v.endswith("p")):
                continue  # soul quality is an enum ("1080p"); drop "high"/"2k"
            params[k] = v
    return params


def generate_image(prompt: str, key: str | None = None, secret: str | None = None,
                   model: str | None = None, timeout: int = 120,
                   extra: dict | None = None) -> dict:
    """Generate one image via the Higgsfield **soul** text2image endpoint. Returns
    {ok:True, imageUrl, model} or {ok:False, error, model}.

    Flow: POST {HF_ENDPOINT} with {"params": {...}} → the API returns a job to poll →
    poll until Completed (or timeout) → read the result image URL. Auth is a PAIR — the
    API Key ID in `hf-api-key`, the Secret in `hf-secret`. `extra` carries optional soul
    params (legacy {"quality","resolution"} hints are sanitized). Does NOT raise — every
    failure comes back as an error dict so callers degrade gracefully (show the prompt,
    don't fake it)."""
    key = (key or resolve_key()).strip()
    secret = (secret or resolve_secret()).strip()
    model = model or DEFAULT_MODEL
    prompt = str(prompt or "").strip()
    if not key or not secret:
        missing = "HIGGSFIELD_API_KEY" if not key else "HIGGSFIELD_API_SECRET"
        return {"ok": False, "error": f"no {missing} wired (Higgsfield needs both id + secret)",
                "model": model}
    if not prompt:
        return {"ok": False, "error": "empty prompt", "model": model}

    body = json.dumps({"params": _soul_params(prompt, model, extra)}).encode()

    # 1) Submit the generation job.
    try:
        data = _http_json(_SOUL_URL, key, secret, data=body, method="POST",
                          timeout=min(timeout, 60))
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": _http_err(e), "model": model}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "model": model}

    # 2) Some responses come back already-complete (sync). Use it if so.
    status = _find_status(data)
    url = _find_url(data)
    if status in _FAILED:
        return {"ok": False, "error": f"generation {status}: {str(data)[:200]}", "model": model}
    if url and status in _DONE or (url and not status):
        return {"ok": True, "imageUrl": url, "model": model}

    # 3) Otherwise poll the returned job/job-set until Completed or timeout.
    job_id = _find_job_id(data)
    if not job_id:
        return {"ok": False,
                "error": f"no image url or job id in soul response: {str(data)[:200]}",
                "model": model}
    poll_url = _JOB_URL_TMPL.format(id=job_id)
    deadline = time.monotonic() + max(10, timeout)
    while time.monotonic() < deadline:
        time.sleep(_POLL_INTERVAL)
        try:
            jd = _http_json(poll_url, key, secret, method="GET", timeout=min(timeout, 30))
        except urllib.error.HTTPError as e:
            return {"ok": False, "error": _http_err(e), "model": model}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"poll {type(e).__name__}: {e}", "model": model}
        st = _find_status(jd)
        u = _find_url(jd)
        if st in _FAILED:
            return {"ok": False, "error": f"generation {st}: {str(jd)[:200]}", "model": model}
        if u and (st in _DONE or not st):
            return {"ok": True, "imageUrl": u, "model": model}
        # else Queued / InProgress — keep polling until the deadline.
    return {"ok": False,
            "error": f"timed out after {timeout}s waiting for Higgsfield job {job_id}",
            "model": model}
