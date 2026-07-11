"""DocuSign eSignature — draft + send wholesale contracts for e-signature straight from a deal.

Server-to-server **JWT Grant** auth: one-time consent, then it sends forever with no login per
contract — exactly what a 24/7 box needs. The JWT is signed RS256 via the system `openssl`, so
there are no extra Python dependencies.

INERT until configured. Drop these in forge-docusign/config/docusign.env (git-ignored, OUTSIDE
the web root, must 404 over HTTP):

  DOCUSIGN_INTEGRATION_KEY=<Client ID from DocuSign Admin > Apps & Keys>
  DOCUSIGN_USER_ID=<API Username GUID of the user to impersonate (your DocuSign login)>
  DOCUSIGN_ACCOUNT_ID=<API Account ID>
  DOCUSIGN_PRIVATE_KEY_FILE=<abs path to the RSA private key .pem paired with the integration key>
  DOCUSIGN_TEMPLATE_ID=<the Purchase Agreement template to send>
  DOCUSIGN_BASE=https://demo.docusign.net          # sandbox; https://www.docusign.net for prod
  DOCUSIGN_OAUTH=account-d.docusign.com            # sandbox; account.docusign.com for prod

One-time consent (per integration key + user), open once in a browser:
  https://account-d.docusign.com/oauth/auth?response_type=code&scope=signature%20impersonation&client_id=<KEY>&redirect_uri=https://www.docusign.com
"""
import base64
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
_CONF = HERE.parent / "forge-docusign" / "config" / "docusign.env"


def _load_env():
    """Load docusign.env without overriding anything already in the environment."""
    try:
        for line in _CONF.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    except Exception:
        pass


_load_env()


def _cfg(key, default=""):
    return os.environ.get(key, default).strip()


_OAUTH = lambda: _cfg("DOCUSIGN_OAUTH", "account-d.docusign.com")          # noqa: E731
_BASE = lambda: _cfg("DOCUSIGN_BASE", "https://demo.docusign.net")         # noqa: E731

_REQUIRED = ["DOCUSIGN_INTEGRATION_KEY", "DOCUSIGN_USER_ID", "DOCUSIGN_ACCOUNT_ID",
             "DOCUSIGN_PRIVATE_KEY_FILE", "DOCUSIGN_TEMPLATE_ID"]

_token = {"access": None, "exp": 0}


def _http_error_detail(e, limit=500):
    try:
        raw = e.read().decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        raw = ""
    detail = raw.strip()
    try:
        parsed = json.loads(detail)
        if isinstance(parsed, dict):
            detail = (parsed.get("message") or parsed.get("error_description")
                      or parsed.get("error") or detail)
            if isinstance(detail, (dict, list)):
                detail = json.dumps(detail)
    except Exception:  # noqa: BLE001
        pass
    return str(detail or getattr(e, "reason", "") or "")[:limit]


def configured():
    if not all(_cfg(k) for k in _REQUIRED):
        return False
    return Path(_cfg("DOCUSIGN_PRIVATE_KEY_FILE")).is_file()


def config_status():
    """What's set / missing — drives the 'connect DocuSign' UI hint (no secrets leaked)."""
    missing = [k for k in _REQUIRED if not _cfg(k)]
    key_file = _cfg("DOCUSIGN_PRIVATE_KEY_FILE")
    key_ok = bool(key_file) and Path(key_file).is_file()
    if key_file and not key_ok:
        missing.append("DOCUSIGN_PRIVATE_KEY_FILE (path not found)")
    return {
        "configured": configured(),
        "missing": missing,
        "env": "production" if "demo" not in _BASE() else "sandbox",
        "sandbox": is_sandbox(),
        "templateSet": bool(_cfg("DOCUSIGN_TEMPLATE_ID")),
    }


def is_sandbox():
    """True only for the DocuSign demo environment used by the toolkit v1."""
    return ("demo.docusign.net" in _BASE().lower()
            and _OAUTH().lower().startswith("account-d."))


def template_map():
    """Configured DocuSign template IDs by locked toolkit deal type.

    The legacy ``DOCUSIGN_TEMPLATE_ID`` remains the SFR fallback so existing
    Purchase Agreement sends keep working. The values are opaque IDs, not keys.
    """
    return {
        "sfr": _cfg("DOCUSIGN_TEMPLATE_SFR") or _cfg("DOCUSIGN_TEMPLATE_ID"),
        "multi": _cfg("DOCUSIGN_TEMPLATE_MULTI"),
        "land": _cfg("DOCUSIGN_TEMPLATE_LAND"),
        "assignment": _cfg("DOCUSIGN_TEMPLATE_ASSIGNMENT"),
    }


# -- JWT (RS256 via openssl) ------------------------------------------------
def _b64url(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _make_assertion():
    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {
        "iss": _cfg("DOCUSIGN_INTEGRATION_KEY"),
        "sub": _cfg("DOCUSIGN_USER_ID"),
        "aud": _OAUTH(),
        "iat": now,
        "exp": now + 3600,
        "scope": "signature impersonation",
    }
    signing_input = (_b64url(json.dumps(header).encode()) + "."
                     + _b64url(json.dumps(claims).encode())).encode("ascii")
    key_file = _cfg("DOCUSIGN_PRIVATE_KEY_FILE")
    proc = subprocess.run(["openssl", "dgst", "-binary", "-sha256", "-sign", key_file],
                          input=signing_input, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"openssl sign failed: {proc.stderr.decode('utf-8', 'ignore')[:200]}")
    return signing_input.decode("ascii") + "." + _b64url(proc.stdout)


def _access_token():
    if _token["access"] and time.time() < _token["exp"] - 60:
        return _token["access"]
    body = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": _make_assertion(),
    }).encode()
    req = urllib.request.Request(f"https://{_OAUTH()}/oauth/token", data=body,
                                 method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            d = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"DocuSign OAuth {e.code}: {_http_error_detail(e)}")
    _token["access"] = d["access_token"]
    _token["exp"] = time.time() + int(d.get("expires_in", 3600))
    return _token["access"]


def _api(method, path, body=None):
    url = f"{_BASE()}/restapi/v2.1/accounts/{_cfg('DOCUSIGN_ACCOUNT_ID')}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {_access_token()}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"DocuSign API {e.code}: {_http_error_detail(e)}")


# -- public: send + status --------------------------------------------------
def send_contract(signer_email, signer_name, tabs=None, role_name=None,
                  email_subject=None, template_id=None):
    """Send the configured Purchase Agreement template to a seller for e-signature.

    tabs: {tabLabel: value} prefilled into the template's text fields (e.g.
          {"property_address": "...", "purchase_price": "45000", "close_date": "..."}).
    role_name: the template's signer role (defaults to DOCUSIGN_ROLE or 'Seller').
    Returns {ok, envelopeId, status} or {error}.
    """
    if not configured():
        return {"error": "DocuSign not configured", "config": config_status()}
    if not signer_email:
        return {"error": "signer email required (DocuSign signs via email)"}
    role = role_name or _cfg("DOCUSIGN_ROLE", "Seller")
    text_tabs = [{"tabLabel": k, "value": "" if v is None else str(v)}
                 for k, v in (tabs or {}).items()]
    envelope = {
        "templateId": template_id or _cfg("DOCUSIGN_TEMPLATE_ID"),
        "status": "sent",
        "emailSubject": email_subject or "Your cash offer — purchase agreement to sign",
        "templateRoles": [{
            "email": signer_email,
            "name": signer_name or signer_email,
            "roleName": role,
            "tabs": {"textTabs": text_tabs} if text_tabs else {},
        }],
    }
    try:
        res = _api("POST", "/envelopes", envelope)
    except Exception as e:  # noqa: BLE001
        return {"error": f"DocuSign send failed: {e}"}
    envelope_id = res.get("envelopeId")
    if not envelope_id:
        return {"error": "DocuSign send returned no envelope id"}
    return {"ok": True, "envelopeId": envelope_id, "status": res.get("status")}


def send_document(signer_email, signer_name, doc_b64, doc_name, ext="pdf",
                  email_subject=None, email_blurb=None):
    """Send an operator-uploaded contract file for e-signature (no template).

    The uploaded document itself becomes the envelope. The signer is added with
    no pre-placed tabs, so DocuSign gives them free-form signing — they drop
    their own signature/date on the document. That works for ANY contract the
    operator uploads, without mapping fields per template.
    Returns {ok, envelopeId, status} or {error}.
    """
    if not configured():
        return {"error": "DocuSign not configured", "config": config_status()}
    if not signer_email:
        return {"error": "signer email required (DocuSign signs via email)"}
    if not doc_b64:
        return {"error": "contract document required"}
    envelope = {
        "status": "sent",
        "emailSubject": (email_subject or "Purchase agreement to sign")[:100],
        "documents": [{
            "documentBase64": doc_b64,
            "name": (doc_name or "Contract")[:100],
            "fileExtension": (ext or "pdf").lstrip("."),
            "documentId": "1",
        }],
        "recipients": {"signers": [{
            "email": signer_email,
            "name": signer_name or signer_email,
            "recipientId": "1",
            "routingOrder": "1",
        }]},
    }
    if email_blurb:
        envelope["emailBlurb"] = str(email_blurb)[:1000]
    try:
        res = _api("POST", "/envelopes", envelope)
    except Exception as e:  # noqa: BLE001
        return {"error": f"DocuSign send failed: {e}"}
    envelope_id = res.get("envelopeId")
    if not envelope_id:
        return {"error": "DocuSign send returned no envelope id"}
    return {"ok": True, "envelopeId": envelope_id, "status": res.get("status")}


def envelope_status(envelope_id):
    if not configured():
        return {"error": "DocuSign not configured"}
    if not envelope_id:
        return {"error": "envelopeId required"}
    try:
        res = _api("GET", f"/envelopes/{envelope_id}")
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    return {"ok": True, "envelopeId": envelope_id, "status": res.get("status"),
            "sentDateTime": res.get("sentDateTime"), "completedDateTime": res.get("completedDateTime")}


def list_templates():
    """Load existing templates from DocuSign; it never creates or edits one."""
    if not configured():
        return []
    try:
        res = _api("GET", "/templates?count=100")
    except Exception:
        return []
    return [
        {"id": row.get("templateId") or row.get("id"), "name": row.get("name") or "Untitled template"}
        for row in (res.get("envelopeTemplates") or [])
        if row.get("templateId") or row.get("id")
    ]


def void_envelope(envelope_id, reason=""):
    """Void an envelope only after the operator approves it in the toolkit UI."""
    if not configured():
        return {"error": "DocuSign not configured"}
    if not envelope_id:
        return {"error": "envelopeId required"}
    try:
        res = _api("PUT", f"/envelopes/{envelope_id}", {
            "status": "voided", "voidedReason": reason or "Voided by operator",
        })
    except Exception as exc:  # noqa: BLE001
        return {"error": f"DocuSign void failed: {exc}"}
    return {"ok": True, "envelopeId": envelope_id, "status": res.get("status") or "voided"}
