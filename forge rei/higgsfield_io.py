"""higgsfield_io.py — shared Higgsfield image generation for every FORGE ad agent.

Higgsfield is ONE account with ONE API key (Bearer auth). Both Nova (daycare enrollment
ads, via daycare_ads_studio) and Eco (agency client ads, via agency_eco) generate images
through this single helper. Unlike the three GHL sub-accounts — which are separate
customer accounts that MUST stay isolated — Higgsfield is a shared creative tool, so one
key serving multiple agents is correct, not an isolation break.

Key resolution (resolve_key): env var first, then any creds dict a caller passes, then a
scan of the known *.env files. So the operator adds HIGGSFIELD_API_KEY to ONE place
(daycare.env) and every ad agent finds it — no need to duplicate the key per business.

Stdlib only. generate_image() does the REST HTTP and returns a dict; it never sends
anything outward on its own and never logs the key. Its only state is the REST pool's
last answer (ok / empty) in marcus_state/higgsfield_ledger.json.

2026-10-17: engine selection (REST pool vs the CLI on the owner's app credits), a credit
quote, a daily credit cap + ledger, and generate() — see the block at the bottom.
Read-only shape check after a CLI login: `python3 higgsfield_io.py --probe`.
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
    HERE.parent / "forge-dropship" / "config" / "dropship.env",
    Path("/opt/forge/forge-daycare/config/daycare.env"),
    Path("/opt/forge/forge-agency/config/agency.env"),
    Path("/opt/forge/forge-dropship/config/dropship.env"),
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
    code = getattr(e, "code", None)
    low = (detail or "").lower()
    # Higgsfield answers 403 for BOTH a bad key and an empty balance. Reading the
    # body first stops "not enough credits" being reported as an auth failure and
    # sending someone off to re-check keys that were never the problem.
    if "credit" in low or "insufficient" in low or "balance" in low:
        hint = (" — the KEY IS FINE; the Higgsfield API credit pool is empty (it is separate "
                "from your app/web credits). Top up at higgsfield.ai; no key change needed")
        mark_rest("empty", f"HTTP {code}: {detail[:160]}")
    elif "nsfw" in low or "moderation" in low or "safety" in low:
        hint = " — prompt was refused by Higgsfield's content filter; rewrite it"
    elif "rate" in low and "limit" in low:
        hint = " — rate limited by Higgsfield; retry shortly"
    elif code in (401, 403):
        hint = (" — auth rejected; verify the API Key ID + Secret and, if Higgsfield's docs "
                "name the headers differently, adjust hf-api-key/hf-secret")
    return f"HTTP {code if code is not None else '?'}{hint}: {detail}"


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
        err = _http_err(e)
        return {"ok": False, "error": err, "model": model,
                "outOfCredits": "credit pool is empty" in err}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "model": model}

    # 2) Some responses come back already-complete (sync). Use it if so.
    status = _find_status(data)
    url = _find_url(data)
    if status in _FAILED:
        return {"ok": False, "error": f"generation {status}: {str(data)[:200]}", "model": model}
    if url and status in _DONE or (url and not status):
        mark_rest("ok")
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
            mark_rest("ok")
            return {"ok": True, "imageUrl": u, "model": model}
        # else Queued / InProgress — keep polling until the deadline.
    return {"ok": False,
            "error": f"timed out after {timeout}s waiting for Higgsfield job {job_id}",
            "model": model}


# ══ Engine selection + guarded generation (2026-10-17) ══════════════════════════════════════
# Two credit pools, verified 2026-10-17: the REST API key+secret authenticate but its pool was
# EMPTY (403 "Not enough credits"), while the owner's Plus web/app account held 910 credits.
# Those app credits are reachable from a server only through the official CLI
# (`@higgsfield/cli`, browser OAuth login, then `workspace set`). The Higgsfield MCP is for
# Claude sessions only (interactive OAuth) — never wire the dashboard to it.
#
#   engine()   "rest" when the key pair is present and the pool is not known-empty,
#              else "cli" when a logged-in CLI with a workspace answers, else "none".
#   generate() ONE image after the owner's tap: quote → daily cap → REST → (out of credits)
#              → CLI fallback → ledger. Unknown cost is refused unless confirm_unknown=True.
#   status()   plain-language state + the exact next step for the UI and the agents.
import re as _re
import shutil
import subprocess
import threading
from datetime import datetime

# Measured 2026-10-17 with `generate cost` (quote == actual charge): gpt_image_2_5 low 0.25 /
# medium 0.5 / high 1.5 credits; gpt_image_2 6.5 (the higher-quality text option);
# flux_3_image 2; text2image_soul_v2 0.12. Params are underscored flags (`--aspect_ratio=9:16`).
CLI_IMAGE_MODEL = os.environ.get("HIGGSFIELD_CLI_IMAGE_MODEL", "gpt_image_2_5")
CLI_QUALITY = os.environ.get("HIGGSFIELD_CLI_QUALITY", "medium")
CLI_RESOLUTION = os.environ.get("HIGGSFIELD_CLI_RESOLUTION", "")      # "" = the model's default (1k)
CLI_PARAMS = os.environ.get("HIGGSFIELD_CLI_PARAMS", "")              # extra k=v,k=v (model-specific)
CLI_ASPECT_FLAG = os.environ.get("HIGGSFIELD_CLI_ASPECT_FLAG", "aspect_ratio")
CLI_WAIT = os.environ.get("HIGGSFIELD_CLI_WAIT", "5m")
CLI_STATUS_TTL = 60
REST_EMPTY_TTL = float(os.environ.get("HIGGSFIELD_REST_EMPTY_TTL", "1800"))
FORMATS = ("1:1", "9:16")
# soul's width_and_height is a strict enum: 1536x1536 is verified; the 9:16 value is NOT.
REST_SIZES = {"1:1": DEFAULT_SIZE,
              "9:16": os.environ.get("HIGGSFIELD_REST_SIZE_9_16", "1152x2048")}
try:
    import forge_atomic as _fa
    LEDGER = _fa.guard_state_path(HERE / "marcus_state" / "higgsfield_ledger.json")
except Exception:  # noqa: BLE001
    _fa = None
    LEDGER = HERE / "marcus_state" / "higgsfield_ledger.json"
_LLOCK = threading.Lock()
_GEN_LOCK = threading.Lock()
_CLI_CACHE = {"at": 0.0, "val": None}


def daily_cap() -> float:
    try:
        return float(os.environ.get("HIGGSFIELD_DAILY_CREDITS", "100"))
    except ValueError:
        return 100.0


def rest_model() -> str:
    return os.environ.get("HIGGSFIELD_REST_MODEL") or DEFAULT_MODEL


def _rest_credits_per_image():
    """REST has no cost endpoint here — Unknown unless the owner states it in env."""
    try:
        v = os.environ.get("HIGGSFIELD_REST_CREDITS_PER_IMAGE", "").strip()
        return float(v) if v else None
    except ValueError:
        return None


# ── ledger (marcus_state/higgsfield_ledger.json) ───────────────────────────────────────────
def _ledger_load() -> dict:
    try:
        return json.loads(Path(LEDGER).read_text()) or {}
    except Exception:  # noqa: BLE001
        return {}


def _ledger_save(d: dict) -> None:
    Path(LEDGER).parent.mkdir(parents=True, exist_ok=True)
    if _fa is not None:
        _fa.atomic_write_json(LEDGER, d)
    else:
        tmp = Path(str(LEDGER) + ".tmp")
        tmp.write_text(json.dumps(d, indent=2))
        os.replace(tmp, LEDGER)


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")      # the connector host's local day


def spent_today() -> tuple:
    """(credits counted today, generations whose cost stayed Unknown)."""
    day = (_ledger_load().get("days") or {}).get(_today()) or {}
    return float(day.get("credits") or 0), int(day.get("unknown") or 0)


def _ledger_add(entry: dict) -> None:
    with _LLOCK:
        d = _ledger_load()
        days = d.setdefault("days", {})
        day = days.setdefault(_today(), {"credits": 0, "unknown": 0, "entries": []})
        if entry.get("credits") is None:
            day["unknown"] = int(day.get("unknown") or 0) + 1
        else:
            day["credits"] = float(day.get("credits") or 0) + float(entry["credits"])
        day["entries"] = (day.get("entries") or [])[-49:] + [entry]
        for k in sorted(days)[:-14]:
            days.pop(k, None)
        _ledger_save(d)


def mark_rest(outcome: str, error: str = "") -> None:
    """Remember the REST pool's last answer ("ok" | "empty"). Never raises."""
    try:
        with _LLOCK:
            d = _ledger_load()
            d["rest"] = {"outcome": outcome, "at": time.time(), "error": str(error)[:200]}
            _ledger_save(d)
    except Exception:  # noqa: BLE001
        pass


def cap_check(credits, confirm_unknown: bool = False) -> tuple:
    """(ok, why). Fail closed: an Unknown cost needs the owner's explicit confirm tap."""
    cap = daily_cap()
    spent, unk = spent_today()
    if credits is None:
        if not confirm_unknown:
            return False, ("cost Unknown — the engine gave no credit estimate. Tap again to "
                           "confirm generating anyway (it still counts against today's cap).")
        if spent >= cap:
            return False, f"daily cap reached: {spent:g} of {cap:g} credits used today (HIGGSFIELD_DAILY_CREDITS)"
        # ponytail: unknown-cost images can't be summed; a flat count stops runaway taps.
        if unk >= int(os.environ.get("HIGGSFIELD_DAILY_UNKNOWN", "5") or 5):
            return False, f"{unk} unknown-cost images already today — the cap can't count them, so no more today"
        return True, ""
    if spent + float(credits) > cap:
        return False, (f"would exceed the daily cap: {spent:g} used + {float(credits):g} for this image "
                       f"> {cap:g} credits (HIGGSFIELD_DAILY_CREDITS)")
    return True, ""


# ── CLI plumbing ───────────────────────────────────────────────────────────────────────────
def cli_bin() -> str:
    """HIGGSFIELD_CLI_BIN → `higgsfield` → `hf` on PATH. ("" = not installed.)"""
    p = (os.environ.get("HIGGSFIELD_CLI_BIN") or "").strip()
    if p:
        return p if os.path.isfile(p) and os.access(p, os.X_OK) else ""
    return shutil.which("higgsfield") or shutil.which("hf") or ""


def _run_cli(args: list, timeout: float = 30) -> tuple:
    """(rc, stdout, stderr). No shell, stdin closed (a login prompt can never hang us)."""
    b = cli_bin()
    if not b:
        return 127, "", "Higgsfield CLI not installed"
    try:
        p = subprocess.run([b, *args], capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL, env={**os.environ, "NO_COLOR": "1"})
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {int(timeout)}s"
    except Exception as e:  # noqa: BLE001
        return 126, "", f"{type(e).__name__}: {e}"


def _json_docs(text: str) -> list:
    text = (text or "").strip()
    if not text:
        return []
    try:
        return [json.loads(text)]
    except ValueError:
        pass
    docs = []
    for line in text.splitlines():
        line = line.strip()
        if line[:1] in "{[":
            try:
                docs.append(json.loads(line))
            except ValueError:
                continue
    return docs


def _num_find(obj, keys: tuple):
    """First numeric value (not bool) under a key whose lower name is in `keys`."""
    stack = [obj]
    while stack:
        cur = stack.pop(0)
        if isinstance(cur, dict):
            for k, v in cur.items():
                if str(k).lower() in keys and not isinstance(v, bool):
                    if isinstance(v, (int, float)):
                        return float(v)
                    if isinstance(v, str) and _re.fullmatch(r"\s*\d+(\.\d+)?\s*", v):
                        return float(v)
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(cur, list):
            stack.extend(x for x in cur if isinstance(x, (dict, list)))
    return None


# THE one place CLI output is interpreted. UNVERIFIED against a logged-in CLI (2026-10-17 the
# CLI here had never logged in) — after `higgsfield auth login`, run
# `python3 higgsfield_io.py --probe` and adjust ONLY these hint tuples / this function.
_BAL_KEYS = ("credits", "balance", "available_credits", "availablecredits", "credit_balance",
             "creditbalance", "remaining", "available", "total_credits")
_COST_KEYS = ("credits", "cost", "credit_cost", "creditcost", "total_cost", "totalcost",
              "estimated_credits", "estimate", "price_credits", "total")
_IMG_URL = _re.compile(r"https://[^\s\"'<>]+?\.(?:png|jpe?g|webp)(?:\?[^\s\"'<>]*)?", _re.I)


def parse_cli(kind: str, stdout: str):
    """kind "account" → credits balance | None · "cost" → credits | None ·
    "workspace" → id/name | None · "result" → {url, status, credits, jobId}.
    Unparseable → None / empty fields, so callers say Unknown (fail closed)."""
    docs = _json_docs(stdout)
    if kind == "account":
        return _num_find(docs, _BAL_KEYS)
    if kind == "cost":
        v = _num_find(docs, _COST_KEYS)
        if v is None and not docs:
            m = _re.search(r"(\d+(?:\.\d+)?)\s*credits?\b", stdout or "", _re.I)
            v = float(m.group(1)) if m else None
        return v
    if kind == "workspace":
        if "no workspace" in (stdout or "").lower():
            return None
        for d in docs:
            if isinstance(d, dict):
                for k in ("id", "workspace_id", "workspaceId", "name"):
                    if isinstance(d.get(k), str) and d[k]:
                        return d[k][:80]
        line = (stdout or "").strip().splitlines()
        return line[0][:80] if line else None
    if kind == "result":
        # Verified 2026-10-17: `generate create … --wait --json` prints a JSON ARRAY of jobs
        # [{id, job_type, status:"completed", result_url, min_result_url (a webp thumbnail), …}].
        jobs = [j for d in docs for j in (d if isinstance(d, list) else [d]) if isinstance(j, dict)]
        for j in jobs:
            u = j.get("result_url")
            if isinstance(u, str) and u.startswith("https://"):
                return {"url": u, "status": str(j.get("status") or "").lower(),
                        "credits": _num_find(j, _COST_KEYS), "jobId": str(j.get("id") or "")}
        if jobs and all(str(j.get("status") or "").lower() in _FAILED for j in jobs):
            return {"url": None, "status": str(jobs[0].get("status")).lower(), "credits": None,
                    "jobId": str(jobs[0].get("id") or "")}
        m = _IMG_URL.search(stdout or "")
        url = m.group(0) if m else None
        return {"url": url, "status": _find_status(docs) if docs else "",
                "credits": _num_find(docs, _COST_KEYS),
                "jobId": _find_job_id(jobs[0]) if jobs else ""}
    return None


def _cli_params(fmt: str, params: str | None = None) -> list:
    base = ",".join(x for x in (f"quality={CLI_QUALITY}" if CLI_QUALITY else "",
                                f"resolution={CLI_RESOLUTION}" if CLI_RESOLUTION else "", CLI_PARAMS) if x)
    out = [f"--{CLI_ASPECT_FLAG}={fmt}"]
    for pair in (base if params is None else params).split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            if k.strip() and v.strip():
                out.append(f"--{k.strip()}={v.strip()}")
    return out


def _seconds(dur: str) -> float:
    m = _re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([smh]?)\s*", dur or "")
    if not m:
        return 300.0
    return float(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600}[m.group(2)]


def cli_status(fresh: bool = False) -> dict:
    """Installed? logged in? workspace? credits? Cached 60 s (it shells out)."""
    if not fresh and _CLI_CACHE["val"] is not None and time.time() - _CLI_CACHE["at"] < CLI_STATUS_TTL:
        return dict(_CLI_CACHE["val"])
    b = cli_bin()
    out = {"installed": False, "bin": b or None, "loggedIn": None, "workspace": None,
           "needsWorkspace": False, "credits": None, "ready": False, "error": ""}
    if not b:
        out["error"] = "Higgsfield CLI not installed"
    else:
        rc, so, se = _run_cli(["version"], 15)
        if rc != 0 or "higgsfield" not in (so + se).lower():
            out["error"] = f"{os.path.basename(b)} is not the Higgsfield CLI (version check failed)"
        else:
            out["installed"] = True
            rc, so, se = _run_cli(["account", "status", "--json"], 30)
            if rc == 0:
                out.update(loggedIn=True, ready=True, credits=parse_cli("account", so))
                rc2, so2, _se2 = _run_cli(["workspace", "status", "--json"], 15)
                out["workspace"] = parse_cli("workspace", so2) if rc2 == 0 else None
            else:
                full = (se or so).strip()
                msg = (full.splitlines() or [""])[0][:200]
                low = full.lower()
                # Verified: not logged in → "request failed (no response received)" + "Hint: Run:
                # hf auth login"; no workspace → "No workspace selected" (checked before the login,
                # so login state stays Unknown there).
                if any(w in low for w in ("auth login", "log in", "unauthor", "expired", "401")):
                    out["loggedIn"] = False
                elif "workspace" in low:
                    out["needsWorkspace"] = True
                out["error"] = msg or f"account status exited {rc}"
    _CLI_CACHE.update(at=time.time(), val=out)
    return dict(out)


def rest_status(model: str | None = None, key: str | None = None, secret: str | None = None) -> dict:
    st = _ledger_load().get("rest") or {}
    outcome = st.get("outcome")
    return {"keyed": ready(key, secret),
            "funded": True if outcome == "ok" else False if outcome == "empty" else None,
            "checkedAt": st.get("at"), "error": st.get("error") if outcome == "empty" else "",
            "retryDue": outcome == "empty" and time.time() - float(st.get("at") or 0) > REST_EMPTY_TTL,
            "model": model or rest_model(), "creditsPerImage": _rest_credits_per_image()}


def _pick(r: dict, c: dict) -> str:
    if r["keyed"] and r["funded"] is not False:
        return "rest"
    return "cli" if c.get("ready") else "none"


def engine(fresh: bool = False) -> str:
    """"rest" | "cli" | "none" — what a generation would use right now."""
    return _pick(rest_status(), cli_status(fresh))


def _next_step(eng: str, r: dict, c: dict) -> str:
    if eng == "cli":
        return "Ready — images use your Higgsfield app credits through the CLI."
    if eng == "rest":
        if r["funded"] is None:
            return ("Ready on the API key — its credit balance is Unknown until the first image "
                    "(the API pool is separate from your app credits).")
        return "Ready — images use the Higgsfield API credits."
    steps = []
    if not c.get("installed"):
        steps.append("Install the Higgsfield CLI on the dashboard machine (`npm i -g @higgsfield/cli`), "
                     "then run `higgsfield auth login` and `higgsfield workspace set <id>`")
    elif c.get("needsWorkspace") or c.get("loggedIn") is not True:
        steps.append("Run `higgsfield auth login` on the dashboard machine, then `higgsfield workspace list` "
                     "and `higgsfield workspace set <id>` (uses your app credits)")
    else:
        steps.append("The Higgsfield CLI didn't answer — run `higgsfield account status` to see why")
    if r["keyed"] and r["funded"] is False:
        steps.append("or top up the Higgsfield API credits at higgsfield.ai (the API pool is separate "
                     "from your app credits; the next Generate re-checks it automatically)")
    elif not r["keyed"]:
        steps.append("or add HIGGSFIELD_API_KEY + HIGGSFIELD_API_SECRET to daycare.env with funded API credits")
    return "; ".join(steps) + "."


def status(fresh: bool = False, rest_model_name: str | None = None) -> dict:
    """The honest state for the UI + agents. Never raises."""
    try:
        r, c = rest_status(rest_model_name), cli_status(fresh)
        eng = _pick(r, c)
        spent, unk = spent_today()
        cap = daily_cap()
        return {"engine": eng, "ready": eng != "none", "rest": r,
                "cli": {**c, "model": CLI_IMAGE_MODEL, "quality": CLI_QUALITY,
                        "params": ",".join(_cli_params("1:1")[1:])},
                "cap": {"daily": cap, "spentToday": spent, "unknownToday": unk,
                        "remaining": max(0.0, cap - spent)},
                "formats": list(FORMATS), "nextStep": _next_step(eng, r, c)}
    except Exception as e:  # noqa: BLE001
        return {"engine": "none", "ready": False, "error": f"{type(e).__name__}: {e}",
                "nextStep": "Image engine status Unknown — see the server log."}


def _quote(eng: str, prompt: str, fmt: str, model: str, params: str | None = None) -> dict:
    if eng == "rest":
        cr = _rest_credits_per_image()
        return {"engine": "rest", "model": model, "credits": cr, "unknown": cr is None,
                "note": "" if cr is not None else "the REST API has no cost estimate — set "
                                                  "HIGGSFIELD_REST_CREDITS_PER_IMAGE to make it known"}
    rc, so, se = _run_cli(["generate", "cost", model, f"--prompt={prompt}", *_cli_params(fmt, params), "--json"], 45)
    cr = parse_cli("cost", so) if rc == 0 else None
    return {"engine": "cli", "model": model, "credits": cr, "unknown": cr is None,
            "note": "" if cr is not None else ((se or so).strip()[:200] or "cost output not understood")}


def quote(prompt: str, model: str | None = None, params: dict | None = None, fmt: str = "1:1",
          rest_model_name: str | None = None) -> dict:
    """Credit estimate WITHOUT creating a job (CLI `generate cost`). REST → Unknown.
    `params` (optional) overrides HIGGSFIELD_CLI_PARAMS for this one estimate."""
    fmt = fmt if fmt in FORMATS else "1:1"
    eng = engine()
    if eng == "none":
        return {"engine": "none", "credits": None, "unknown": True,
                "note": status()["nextStep"]}
    model = model or (CLI_IMAGE_MODEL if eng == "cli" else (rest_model_name or rest_model()))
    ps = ",".join(f"{k}={v}" for k, v in params.items()) if params else None
    return _quote(eng, str(prompt or "").strip(), fmt, model, ps)


def _cli_generate(prompt: str, fmt: str, model: str) -> dict:
    before = cli_status(fresh=True).get("credits")
    wait = _seconds(CLI_WAIT)
    rc, so, se = _run_cli(["generate", "create", model, f"--prompt={prompt}", *_cli_params(fmt),
                           "--wait", f"--wait-timeout={CLI_WAIT}", "--wait-interval=5s", "--json"],
                          timeout=wait + 60)
    if rc != 0:
        return {"ok": False, "error": f"CLI exited {rc}: {(se or so).strip()[:240]}", "model": model}
    res = parse_cli("result", so)
    if res["status"] in _FAILED:
        return {"ok": False, "error": f"generation {res['status']}", "model": model, "jobId": res["jobId"]}
    if not res["url"]:
        return {"ok": False, "model": model, "jobId": res["jobId"],
                "error": "CLI finished but no image URL was found in its output — run --probe and "
                         "adjust parse_cli('result')"}
    credits = res["credits"]
    after = cli_status(fresh=True).get("credits")
    if credits is None and before is not None and after is not None and before > after:
        credits = round(before - after, 2)
    return {"ok": True, "imageUrl": res["url"], "model": model, "credits": credits, "jobId": res["jobId"]}


def generate(prompt: str, fmt: str = "1:1", *, rest_model_name: str | None = None,
             cli_model: str | None = None, confirm_unknown: bool = False, ref: str = "",
             key: str | None = None, secret: str | None = None, timeout: int = 180) -> dict:
    """ONE guarded image (call only after the owner's tap, or from the autopilot's capped
    cycle). → {ok, imageUrl, model, engine, credits, format} or {ok:False, error, …}.
    Never raises. One generation at a time per process."""
    fmt = fmt if fmt in FORMATS else "1:1"
    prompt = str(prompt or "").strip()
    if not prompt:
        return {"ok": False, "error": "empty prompt"}
    if not _GEN_LOCK.acquire(blocking=False):
        return {"ok": False, "busy": True, "error": "another image is generating — wait for it to finish"}
    try:
        r = rest_status(rest_model_name, key, secret)
        c = cli_status()
        plan = []
        if r["keyed"] and (r["funded"] is not False or r["retryDue"]):
            plan.append(("rest", r["model"]))
        if c.get("ready"):
            plan.append(("cli", cli_model or CLI_IMAGE_MODEL))
        if not plan:
            return {"ok": False, "engine": "none", "needsSetup": True, "format": fmt,
                    "error": "No image engine is ready — " + _next_step("none", r, c)}
        refusal, last = None, None
        for eng, model in plan:
            q = _quote(eng, prompt, fmt, model)
            ok, why = cap_check(q["credits"], confirm_unknown)
            if not ok:
                refusal = refusal or {"ok": False, "engine": eng, "model": model, "format": fmt,
                                      "credits": q["credits"], "error": why,
                                      "needsConfirm": q["credits"] is None and not confirm_unknown,
                                      "capped": not (q["credits"] is None and not confirm_unknown)}
                continue
            if eng == "rest":
                res = generate_image(prompt, key=key, secret=secret, model=model, timeout=timeout,
                                     extra={"width_and_height": REST_SIZES[fmt]})
            else:
                res = _cli_generate(prompt, fmt, model)
            if res.get("ok"):
                credits = res.get("credits") if res.get("credits") is not None else q["credits"]
                _ledger_add({"ts": int(time.time() * 1000), "engine": eng, "model": model, "format": fmt,
                             "credits": credits, "ref": str(ref)[:80]})
                return {"ok": True, "imageUrl": res["imageUrl"], "model": model, "engine": eng,
                        "credits": credits, "format": fmt}
            last = {**res, "engine": eng, "format": fmt}
            if eng == "rest" and res.get("outOfCredits"):
                continue                      # API pool empty → the CLI (app credits) if ready
            break
        return last or refusal
    finally:
        _GEN_LOCK.release()


def _probe() -> None:
    """READ-ONLY. Prints the raw CLI shapes so parse_cli can be checked after login.
    Never runs `generate create`, `auth login` or `auth token`."""
    b = cli_bin()
    print("bin:", b or "NOT FOUND (set HIGGSFIELD_CLI_BIN or put higgsfield on PATH)")
    if not b:
        return
    model = CLI_IMAGE_MODEL
    for args in (["version"], ["workspace", "status", "--json"], ["workspace", "list", "--json"],
                 ["account", "status", "--json"],
                 ["model", "list", "--image", "--json"], ["model", "get", model, "--json"],
                 ["generate", "cost", model, "--prompt=probe: warm sunlit classroom reading corner",
                  *_cli_params("1:1"), "--json"]):
        rc, so, se = _run_cli(args, 60)
        print(f"\n$ higgsfield {' '.join(args)}\n  rc={rc}\n  stdout:\n{so[:3000]}\n  stderr: {se[:600]}")
        if args[:2] == ["account", "status"]:
            print("  → parse_cli('account') =", parse_cli("account", so))
        if args[:2] == ["generate", "cost"]:
            print("  → parse_cli('cost') =", parse_cli("cost", so))
    print("\nstatus():", json.dumps(status(fresh=True), indent=2, default=str))


if __name__ == "__main__":
    import sys
    if "--probe" in sys.argv:
        _probe()
    else:
        print("usage: python3 higgsfield_io.py --probe   (read-only CLI shape check)")
