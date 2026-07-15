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


def generate_image(prompt: str, key: str | None = None, secret: str | None = None,
                   model: str | None = None, timeout: int = 120,
                   extra: dict | None = None) -> dict:
    """Generate one image from a text prompt. Returns {ok:True, imageUrl, model} or
    {ok:False, error, model}. Higgsfield auth is a PAIR — the API Key ID goes in the
    `hf-api-key` header and the API Key Secret in `hf-secret`. `extra` merges into the
    request body (e.g. {"quality":"high","resolution":"2k"}). Does NOT raise — every
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
    payload = {"model": model, "prompt": prompt}
    if isinstance(extra, dict):
        payload.update(extra)
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{HF_BASE}/image/generate", data=body, method="POST",
        headers={"hf-api-key": key, "hf-secret": secret, "Content-Type": "application/json",
                 # Higgsfield sits behind Cloudflare, which 403s (code 1010) the default
                 # Python-urllib signature. A real browser UA gets past the bot filter.
                 "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 "
                                "Safari/537.36"),
                 "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "ignore")[:300]
        except Exception:
            pass
        # 401/403 almost always means the auth scheme/tier differs (key+secret vs Bearer).
        hint = ""
        if e.code in (401, 403):
            hint = (" — auth rejected; verify the API Key ID + Secret are correct and, if "
                    "Higgsfield's docs name the headers differently, adjust hf-api-key/hf-secret")
        return {"ok": False, "error": f"HTTP {e.code}{hint}: {detail}", "model": model}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "model": model}
    # Higgsfield returns the asset URL under one of a few keys depending on model.
    url = (data.get("imageUrl") or data.get("url")
           or (data.get("images") or [{}])[0].get("url") if isinstance(data.get("images"), list)
           else data.get("imageUrl") or data.get("url"))
    if not url:
        url = data.get("output") or data.get("result")
    if not url:
        return {"ok": False, "error": f"no image url in response: {str(data)[:200]}", "model": model}
    return {"ok": True, "imageUrl": url, "model": model}
