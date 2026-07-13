#!/usr/bin/env python3
"""Secure Supabase bridge for the FORGE Daycare management workspace.

The browser never receives a Supabase token.  A successful Login ID/PIN exchange
creates an opaque, in-memory FORGE session; every database request then runs with
the manager's own JWT so Supabase RLS remains the final authorization boundary.

Stdlib only.  Secrets are loaded from the sibling ``forge-daycare`` folder,
which is outside the dashboard web root and is shipped separately by push.sh.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
COOKIE_NAME = "forge_daycare_session"
SESSION_ABSOLUTE_SECONDS = 12 * 60 * 60
SESSION_IDLE_SECONDS = 60 * 60
PROFILE_RECHECK_SECONDS = 5 * 60
TOKEN_REFRESH_LEEWAY_SECONDS = 90
MAX_BODY_BYTES = 1_000_000
MANAGEMENT_ROLES = {"manager", "admin"}
UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
LOGIN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{2,63}$")
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$")

ENV_CANDIDATES = (
    HERE.parent / "forge-daycare" / "config" / "daycare.env",
    Path.home() / "Desktop" / "forge-daycare" / "config" / "daycare.env",
    Path("/opt/forge/forge-daycare/config/daycare.env"),
)


class DaycareError(Exception):
    """Expected API failure with an HTTP status and browser-safe message."""

    def __init__(self, status: int, message: str, code: str = "daycare_error"):
        super().__init__(message)
        self.status = int(status)
        self.message = message
        self.code = code

    def payload(self) -> dict[str, Any]:
        return {"ok": False, "error": self.message, "code": self.code}


def _read_env(paths=ENV_CANDIDATES) -> dict[str, str]:
    for path in paths:
        try:
            if not path.is_file():
                continue
            result: dict[str, str] = {}
            for raw in path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                result[key.strip()] = value.strip().strip('"').strip("'")
            return result
        except OSError:
            continue
    return {}


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class DaycareConfig:
    url: str
    publishable_key: str
    location_id: str
    login_domain: str
    live: bool
    writes_enabled: bool
    allow_http: bool
    allowed_origins: tuple[str, ...]

    @property
    def configured(self) -> bool:
        return bool(
            self.url.startswith("https://")
            and self.publishable_key
            and is_uuid(self.location_id)
            and self.login_domain
        )


def load_config() -> DaycareConfig:
    values = _read_env()

    def pick(*names: str, default: str = "") -> str:
        for name in names:
            value = os.environ.get(name) or values.get(name)
            if value:
                return value.strip()
        return default

    origins = pick("FORGE_DAYCARE_ALLOWED_ORIGINS", "DAYCARE_ALLOWED_ORIGINS")
    allowed = tuple(
        origin.strip().rstrip("/") for origin in origins.split(",") if origin.strip()
    ) or (
        "https://forge-reios.tail0a2dda.ts.net",
        "http://localhost:7799",
        "http://127.0.0.1:7799",
    )
    return DaycareConfig(
        url=pick(
            "DAYCARE_SUPABASE_URL", "SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL"
        ).rstrip("/"),
        publishable_key=pick(
            "DAYCARE_SUPABASE_PUBLISHABLE_KEY",
            "SUPABASE_PUBLISHABLE_KEY",
            "SUPABASE_ANON_KEY",
            "NEXT_PUBLIC_SUPABASE_ANON_KEY",
        ),
        location_id=pick("DAYCARE_SUPABASE_LOCATION_ID", "SUPABASE_LOCATION_ID"),
        login_domain=pick(
            "DAYCARE_SUPABASE_LOGIN_DOMAIN",
            "SUPABASE_LOGIN_DOMAIN",
            default="login.blessings.app",
        ).lower(),
        live=_truthy(pick("FORGE_DAYCARE_LIVE", default="0")),
        writes_enabled=_truthy(pick("FORGE_DAYCARE_WRITES", default="0")),
        allow_http=_truthy(pick("FORGE_DAYCARE_ALLOW_HTTP", default="0")),
        allowed_origins=allowed,
    )


CONFIG = load_config()


def reload_config() -> DaycareConfig:
    """Reload after tests or a controlled process-level configuration change."""
    global CONFIG
    CONFIG = load_config()
    return CONFIG


def is_uuid(value: Any) -> bool:
    if not isinstance(value, str) or not UUID_RE.match(value):
        return False
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


def require_uuid(value: Any, field: str = "id", *, optional: bool = False) -> str | None:
    if optional and (value is None or value == ""):
        return None
    if not is_uuid(value):
        raise DaycareError(400, f"{field} must be a valid ID", "validation_error")
    return str(value)


def require_text(
    value: Any,
    field: str,
    *,
    minimum: int = 1,
    maximum: int = 4000,
    optional: bool = False,
) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise DaycareError(400, f"{field} is required", "validation_error")
    cleaned = value.strip()
    if optional and not cleaned:
        return None
    if len(cleaned) < minimum or len(cleaned) > maximum:
        raise DaycareError(
            400,
            f"{field} must be {minimum}-{maximum} characters",
            "validation_error",
        )
    return cleaned


def require_date(value: Any, field: str, *, optional: bool = False) -> str | None:
    if optional and (value is None or value == ""):
        return None
    try:
        parsed = date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise DaycareError(400, f"{field} must use YYYY-MM-DD", "validation_error") from None
    return parsed.isoformat()


def require_timestamp(value: Any, field: str, *, optional: bool = False) -> str | None:
    if optional and (value is None or value == ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        raise DaycareError(400, f"{field} must be an ISO timestamp", "validation_error") from None
    return parsed.isoformat()


def require_time(value: Any, field: str) -> str:
    if not isinstance(value, str) or not TIME_RE.match(value.strip()):
        raise DaycareError(400, f"{field} must use HH:MM", "validation_error")
    return value.strip()


def require_number(
    value: Any,
    field: str,
    *,
    minimum: Decimal = Decimal("0"),
    maximum: Decimal = Decimal("10000000"),
    optional: bool = False,
) -> float | None:
    if optional and (value is None or value == ""):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise DaycareError(400, f"{field} must be a number", "validation_error") from None
    if not number.is_finite() or number < minimum or number > maximum:
        raise DaycareError(400, f"{field} is out of range", "validation_error")
    return float(number)


def require_int(value: Any, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise DaycareError(400, f"{field} must be a whole number", "validation_error")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise DaycareError(400, f"{field} must be a whole number", "validation_error") from None
    if str(value).strip() not in {str(number), f"{number}.0"} or not minimum <= number <= maximum:
        raise DaycareError(400, f"{field} is out of range", "validation_error")
    return number


def enum_value(value: Any, field: str, allowed: set[str]) -> str:
    candidate = str(value or "").strip().lower()
    if candidate not in allowed:
        raise DaycareError(400, f"{field} is invalid", "validation_error")
    return candidate


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _body_value(body: dict[str, Any], snake: str, camel: str | None = None, default=None):
    if snake in body:
        return body[snake]
    if camel and camel in body:
        return body[camel]
    return default


@dataclass
class Session:
    sid: str
    access_token: str
    refresh_token: str
    token_expires_at: float
    created_at: float
    absolute_expires_at: float
    idle_expires_at: float
    profile_checked_at: float
    profile: dict[str, Any]


_SESSIONS: dict[str, Session] = {}
_SESSION_LOCK = threading.RLock()


def clear_sessions() -> None:
    """Process-local invalidation (also used by focused tests)."""
    with _SESSION_LOCK:
        _SESSIONS.clear()


def session_id_from_cookie(cookie_header: str | None) -> str | None:
    if not cookie_header:
        return None
    try:
        parsed = SimpleCookie()
        parsed.load(cookie_header)
        morsel = parsed.get(COOKIE_NAME)
        value = morsel.value if morsel else ""
    except Exception:  # malformed cookies are simply unauthenticated
        return None
    return value if re.fullmatch(r"[A-Za-z0-9_-]{32,160}", value or "") else None


def session_cookie(sid: str) -> str:
    return (
        f"{COOKIE_NAME}={sid}; Path=/api/daycare; Max-Age={SESSION_ABSOLUTE_SECONDS}; "
        "Secure; HttpOnly; SameSite=Strict"
    )


def expired_session_cookie() -> str:
    return (
        f"{COOKIE_NAME}=; Path=/api/daycare; Max-Age=0; "
        "Secure; HttpOnly; SameSite=Strict"
    )


def request_is_secure(headers: Any, client_ip: str | None = None, *, is_tls: bool = False) -> bool:
    if CONFIG.allow_http:
        return True
    if is_tls:
        return True
    forwarded = str(headers.get("X-Forwarded-Proto", "")).split(",", 1)[0].strip().lower()
    # X-Forwarded-Proto is trusted only from the local Tailscale Serve reverse
    # proxy.  A tailnet client hitting :7799 directly can forge this header.
    return forwarded == "https" and client_ip in {"127.0.0.1", "::1"}


def validate_write_request(headers: Any, client_ip: str | None = None, *, is_tls: bool = False) -> None:
    if not request_is_secure(headers, client_ip, is_tls=is_tls):
        raise DaycareError(403, "Daycare writes require HTTPS", "https_required")
    origin = str(headers.get("Origin", "")).strip().rstrip("/")
    if not origin or origin not in CONFIG.allowed_origins:
        raise DaycareError(403, "Request origin is not allowed", "origin_rejected")


class SupabaseBridge:
    def __init__(self, config: DaycareConfig | None = None):
        self.config = config or CONFIG

    def require_available(self, *, write: bool = False) -> None:
        if not self.config.configured:
            raise DaycareError(502, "Daycare integration is not configured", "not_configured")
        if not self.config.live:
            raise DaycareError(503, "Daycare live operations are disabled", "live_disabled")
        if write and not self.config.writes_enabled:
            raise DaycareError(
                503,
                "Daycare writes are disabled until the security rollout is approved",
                "writes_disabled",
            )

    def _urlopen_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: Any = None,
        expected_empty: bool = False,
    ) -> Any:
        data = json.dumps(body, separators=(",", ":")).encode("utf-8") if body is not None else None
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                if not raw.strip() or expected_empty:
                    return None
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError):
            raise DaycareError(502, "Daycare database is temporarily unavailable", "upstream_unavailable") from None

    def _base_headers(self, access_token: str | None = None, prefer: str | None = None) -> dict[str, str]:
        headers = {
            "apikey": self.config.publishable_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "FORGE-Daycare/1.0",
        }
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def _refresh(self, session: Session) -> None:
        url = f"{self.config.url}/auth/v1/token?grant_type=refresh_token"
        try:
            payload = self._urlopen_json(
                "POST",
                url,
                headers=self._base_headers(),
                body={"refresh_token": session.refresh_token},
            )
        except urllib.error.HTTPError:
            self.logout(session.sid)
            raise DaycareError(401, "Daycare session expired", "session_expired") from None
        access = payload.get("access_token") if isinstance(payload, dict) else None
        refresh = payload.get("refresh_token") if isinstance(payload, dict) else None
        if not access or not refresh:
            self.logout(session.sid)
            raise DaycareError(401, "Daycare session expired", "session_expired")
        with _SESSION_LOCK:
            if session.sid not in _SESSIONS:
                raise DaycareError(401, "Daycare session expired", "session_expired")
            session.access_token = access
            session.refresh_token = refresh
            session.token_expires_at = time.time() + int(payload.get("expires_in") or 3600)

    def _upstream_error(self, error: urllib.error.HTTPError, *, auth: bool = False) -> DaycareError:
        try:
            raw = error.read().decode("utf-8", "ignore")[:2000]
            payload = json.loads(raw) if raw else {}
        except Exception:
            payload = {}
        upstream_code = str(payload.get("code") or "") if isinstance(payload, dict) else ""
        if auth and error.code in {400, 401}:
            return DaycareError(401, "Invalid Login ID or PIN", "invalid_credentials")
        if error.code == 401:
            return DaycareError(401, "Invalid Login ID or PIN", "invalid_credentials")
        if error.code == 403:
            return DaycareError(403, "You do not have permission for that action", "forbidden")
        if error.code == 404 or upstream_code == "PGRST116":
            return DaycareError(404, "The requested daycare record was not found", "not_found")
        if error.code == 409 or upstream_code in {"23505", "23P01"}:
            return DaycareError(409, "That daycare record conflicts with an existing record", "conflict")
        if error.code in {400, 422}:
            return DaycareError(400, "The daycare request was not accepted", "validation_error")
        return DaycareError(502, "Daycare database request failed", "upstream_error")

    def rest(
        self,
        session: Session,
        method: str,
        resource: str,
        *,
        query: dict[str, Any] | None = None,
        body: Any = None,
        prefer: str | None = None,
        retry_auth: bool = True,
    ) -> Any:
        if not re.fullmatch(r"[a-z_]+", resource):
            raise DaycareError(500, "Invalid internal daycare resource", "internal_error")
        self.require_available(write=method.upper() != "GET")
        if session.token_expires_at <= time.time() + TOKEN_REFRESH_LEEWAY_SECONDS:
            self._refresh(session)
        encoded = urllib.parse.urlencode(query or {}, doseq=True, safe="(),.*!:")
        url = f"{self.config.url}/rest/v1/{resource}"
        if encoded:
            url += "?" + encoded
        try:
            return self._urlopen_json(
                method.upper(),
                url,
                headers=self._base_headers(session.access_token, prefer),
                body=body,
            )
        except urllib.error.HTTPError as error:
            if error.code == 401 and retry_auth:
                self._refresh(session)
                return self.rest(
                    session,
                    method,
                    resource,
                    query=query,
                    body=body,
                    prefer=prefer,
                    retry_auth=False,
                )
            raise self._upstream_error(error) from None

    def rpc(self, session: Session, name: str, body: dict[str, Any]) -> Any:
        if not re.fullmatch(r"[a-z_]+", name):
            raise DaycareError(500, "Invalid internal daycare operation", "internal_error")
        self.require_available(write=True)
        if session.token_expires_at <= time.time() + TOKEN_REFRESH_LEEWAY_SECONDS:
            self._refresh(session)
        url = f"{self.config.url}/rest/v1/rpc/{name}"
        try:
            return self._urlopen_json(
                "POST",
                url,
                headers=self._base_headers(session.access_token, "return=representation"),
                body=body,
            )
        except urllib.error.HTTPError as error:
            if error.code == 401:
                self._refresh(session)
                try:
                    return self._urlopen_json(
                        "POST",
                        url,
                        headers=self._base_headers(session.access_token, "return=representation"),
                        body=body,
                    )
                except urllib.error.HTTPError as retry_error:
                    raise self._upstream_error(retry_error) from None
            raise self._upstream_error(error) from None

    def edge_function(self, session: Session, name: str, body: dict[str, Any]) -> Any:
        if not re.fullmatch(r"[a-z0-9-]+", name):
            raise DaycareError(500, "Invalid internal daycare operation", "internal_error")
        self.require_available(write=True)
        if session.token_expires_at <= time.time() + TOKEN_REFRESH_LEEWAY_SECONDS:
            self._refresh(session)
        url = f"{self.config.url}/functions/v1/{name}"
        try:
            result = self._urlopen_json(
                "POST",
                url,
                headers=self._base_headers(session.access_token),
                body=body,
            )
        except urllib.error.HTTPError as error:
            if error.code == 401:
                self._refresh(session)
                try:
                    result = self._urlopen_json(
                        "POST", url, headers=self._base_headers(session.access_token), body=body
                    )
                except urllib.error.HTTPError as retry_error:
                    raise self._upstream_error(retry_error) from None
            else:
                raise self._upstream_error(error) from None
        if not isinstance(result, dict) or result.get("error"):
            raise DaycareError(502, "Daycare account provisioning failed", "provision_failed")
        return result

    def storage_sign(self, session: Session, bucket: str, path: str, *, upload: bool) -> dict[str, Any]:
        if bucket not in {"child-photos", "message-attachments", "avatars"}:
            raise DaycareError(400, "Unsupported media bucket", "validation_error")
        safe_path = validate_storage_path(path)
        endpoint = "object/upload/sign" if upload else "object/sign"
        url = (
            f"{self.config.url}/storage/v1/{endpoint}/"
            f"{urllib.parse.quote(bucket, safe='')}/{urllib.parse.quote(safe_path, safe='/')}"
        )
        if upload:
            self.require_available(write=True)
            body: dict[str, Any] = {}
        else:
            self.require_available()
            body = {"expiresIn": 900}
        if session.token_expires_at <= time.time() + TOKEN_REFRESH_LEEWAY_SECONDS:
            self._refresh(session)
        try:
            result = self._urlopen_json(
                "POST",
                url,
                headers=self._base_headers(session.access_token),
                body=body,
            )
        except urllib.error.HTTPError as error:
            if error.code == 401:
                self._refresh(session)
                try:
                    result = self._urlopen_json(
                        "POST", url, headers=self._base_headers(session.access_token), body=body
                    )
                except urllib.error.HTTPError as retry_error:
                    raise self._upstream_error(retry_error) from None
            else:
                raise self._upstream_error(error) from None
        if not isinstance(result, dict):
            raise DaycareError(502, "Unable to create a media link", "upstream_error")
        signed = result.get("signedURL") or result.get("signedUrl")
        if signed and signed.startswith("/"):
            signed = self.config.url + "/storage/v1" + signed
        return {"bucket": bucket, "path": safe_path, "signedUrl": signed, "token": result.get("token")}

    def login(self, login_id: Any, pin: Any) -> tuple[Session, dict[str, Any]]:
        self.require_available()
        login = str(login_id or "").strip().lower()
        secret = str(pin or "")
        if not LOGIN_ID_RE.fullmatch(login) or not 6 <= len(secret) <= 72:
            raise DaycareError(400, "Login ID and a valid PIN are required", "validation_error")
        url = f"{self.config.url}/auth/v1/token?grant_type=password"
        try:
            payload = self._urlopen_json(
                "POST",
                url,
                headers=self._base_headers(),
                body={"email": f"{login}@{self.config.login_domain}", "password": secret},
            )
        except urllib.error.HTTPError as error:
            raise self._upstream_error(error, auth=True) from None
        access = payload.get("access_token") if isinstance(payload, dict) else None
        refresh = payload.get("refresh_token") if isinstance(payload, dict) else None
        user = payload.get("user") if isinstance(payload, dict) else None
        user_id = user.get("id") if isinstance(user, dict) else None
        if not access or not refresh or not is_uuid(user_id):
            raise DaycareError(502, "Daycare authentication returned an invalid response", "upstream_error")
        temporary = Session(
            sid="pending",
            access_token=access,
            refresh_token=refresh,
            token_expires_at=time.time() + int(payload.get("expires_in") or 3600),
            created_at=time.time(),
            absolute_expires_at=time.time() + SESSION_ABSOLUTE_SECONDS,
            idle_expires_at=time.time() + SESSION_IDLE_SECONDS,
            profile_checked_at=0,
            profile={},
        )
        profile = self._fetch_profile(temporary, user_id)
        self._authorize_profile(profile)
        now = time.time()
        temporary.sid = secrets.token_urlsafe(48)
        temporary.created_at = now
        temporary.absolute_expires_at = now + SESSION_ABSOLUTE_SECONDS
        temporary.idle_expires_at = now + SESSION_IDLE_SECONDS
        temporary.profile_checked_at = now
        temporary.profile = profile
        with _SESSION_LOCK:
            self._cleanup_locked(now)
            _SESSIONS[temporary.sid] = temporary
        return temporary, public_profile(profile)

    def _fetch_profile(self, session: Session, profile_id: str) -> dict[str, Any]:
        rows = self.rest(
            session,
            "GET",
            "profiles",
            query={
                "id": f"eq.{profile_id}",
                "select": (
                    "id,location_id,role,first_name,last_name,display_name,avatar_path,"
                    "login_id,auth_email,phone,active,permissions"
                ),
                "limit": "1",
            },
        )
        if not isinstance(rows, list) or not rows:
            raise DaycareError(403, "This account has no daycare profile", "profile_missing")
        return rows[0]

    def _authorize_profile(self, profile: dict[str, Any]) -> None:
        if not profile.get("active"):
            raise DaycareError(403, "This daycare account is inactive", "inactive_account")
        if profile.get("role") not in MANAGEMENT_ROLES:
            raise DaycareError(403, "Management or admin access is required", "management_required")
        if profile.get("location_id") != self.config.location_id:
            raise DaycareError(403, "This account belongs to another daycare location", "location_mismatch")

    def _cleanup_locked(self, now: float) -> None:
        expired = [
            sid for sid, session in _SESSIONS.items()
            if now >= session.absolute_expires_at or now >= session.idle_expires_at
        ]
        for sid in expired:
            _SESSIONS.pop(sid, None)

    def require_session(self, sid: str | None) -> Session:
        self.require_available()
        now = time.time()
        with _SESSION_LOCK:
            self._cleanup_locked(now)
            session = _SESSIONS.get(sid or "")
            if not session:
                raise DaycareError(401, "Daycare login is required", "authentication_required")
            session.idle_expires_at = min(now + SESSION_IDLE_SECONDS, session.absolute_expires_at)
            should_check = now - session.profile_checked_at >= PROFILE_RECHECK_SECONDS
        if session.token_expires_at <= now + TOKEN_REFRESH_LEEWAY_SECONDS:
            self._refresh(session)
        if should_check:
            profile = self._fetch_profile(session, str(session.profile.get("id") or ""))
            try:
                self._authorize_profile(profile)
            except DaycareError:
                self.logout(session.sid)
                raise
            with _SESSION_LOCK:
                if session.sid in _SESSIONS:
                    session.profile = profile
                    session.profile_checked_at = time.time()
        return session

    def logout(self, sid: str | None) -> None:
        if not sid:
            return
        with _SESSION_LOCK:
            _SESSIONS.pop(sid, None)

    def auth_status(self, sid: str | None) -> dict[str, Any]:
        base = {
            "ok": True,
            "configured": self.config.configured,
            "live": self.config.live,
            "writesEnabled": self.config.writes_enabled,
            "authenticated": False,
        }
        if not self.config.configured or not self.config.live or not sid:
            return base
        try:
            session = self.require_session(sid)
        except DaycareError:
            return base
        base.update({"authenticated": True, "profile": public_profile(session.profile)})
        return base


def public_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Never copy auth/token fields into browser responses."""
    allowed = {
        "id", "location_id", "role", "first_name", "last_name", "display_name",
        "avatar_path", "login_id", "auth_email", "phone", "active", "permissions",
    }
    return {key: value for key, value in profile.items() if key in allowed}


def validate_storage_path(path: Any) -> str:
    value = require_text(path, "path", maximum=500)
    assert value is not None
    parts = value.split("/")
    if (
        value.startswith("/")
        or ".." in parts
        or any(not part or part.startswith(".") for part in parts)
        or any("\\" in part for part in parts)
    ):
        raise DaycareError(400, "Invalid media path", "validation_error")
    return value


BRIDGE = SupabaseBridge()


def refresh_bridge() -> SupabaseBridge:
    global BRIDGE
    BRIDGE = SupabaseBridge(reload_config())
    return BRIDGE


def _rows(result: Any) -> list[dict[str, Any]]:
    return result if isinstance(result, list) else []


def _single(result: Any, resource: str) -> dict[str, Any]:
    rows = _rows(result)
    if not rows:
        raise DaycareError(404, f"{resource} was not found", "not_found")
    return rows[0]


def _ensure_location_record(session: Session, table: str, record_id: Any) -> dict[str, Any]:
    rid = require_uuid(record_id, f"{table} id")
    rows = BRIDGE.rest(
        session,
        "GET",
        table,
        query={"id": f"eq.{rid}", "location_id": f"eq.{CONFIG.location_id}", "select": "*", "limit": "1"},
    )
    return _single(rows, table.replace("_", " ").rstrip("s").title())


def _child_ids(session: Session) -> list[str]:
    rows = BRIDGE.rest(
        session,
        "GET",
        "children",
        query={"location_id": f"eq.{CONFIG.location_id}", "select": "id"},
    )
    return [str(row.get("id")) for row in _rows(rows) if is_uuid(row.get("id"))]


def _staff_ids(session: Session) -> list[str]:
    rows = BRIDGE.rest(
        session,
        "GET",
        "staff_members",
        query={"location_id": f"eq.{CONFIG.location_id}", "select": "id"},
    )
    return [str(row.get("id")) for row in _rows(rows) if is_uuid(row.get("id"))]


def get_status(session: Session | None = None) -> dict[str, Any]:
    response: dict[str, Any] = {
        "ok": True,
        "configured": CONFIG.configured,
        "live": CONFIG.live,
        "writesEnabled": CONFIG.writes_enabled,
        "healthy": False,
        "locationId": CONFIG.location_id if CONFIG.configured else None,
        "location_id": CONFIG.location_id if CONFIG.configured else None,
    }
    if not session:
        response["message"] = "Login required for live health verification"
        return response
    try:
        location = _single(
            BRIDGE.rest(
                session,
                "GET",
                "locations",
                query={
                    "id": f"eq.{CONFIG.location_id}",
                    "select": "id,name,address,timezone,phone,opens_at,closes_at",
                    "limit": "1",
                },
            ),
            "Daycare location",
        )
        location["opening_time"] = location.get("opens_at")
        location["closing_time"] = location.get("closes_at")
        response.update({
            "healthy": True,
            "location": location,
            "center": location,
            "location_name": location.get("name"),
            "checked_at": now_iso(),
            "message": "Supabase connected",
        })
    except DaycareError as error:
        response["message"] = error.message
    return response


def get_settings(session: Session) -> dict[str, Any]:
    location = _single(
        BRIDGE.rest(
            session,
            "GET",
            "locations",
            query={
                "id": f"eq.{CONFIG.location_id}",
                "select": "id,name,address,timezone,phone,opens_at,closes_at",
                "limit": "1",
            },
        ),
        "Daycare location",
    )
    return {"ok": True, "settings": location}


def get_children(session: Session) -> dict[str, Any]:
    rows = BRIDGE.rest(
        session,
        "GET",
        "children",
        query={
            "location_id": f"eq.{CONFIG.location_id}",
            "select": "*,classrooms(id,name,age_group,color),profiles!children_guardian_profile_id_fkey(id,display_name,first_name,last_name,phone,auth_email,login_id)",
            "order": "active.desc,first_name.asc,last_name.asc",
        },
    )
    children = _rows(rows)
    for child in children:
        guardian = child.get("profiles")
        if guardian:
            child["guardian_profile"] = guardian
            child["guardian"] = guardian
            child["guardian_name"] = guardian.get("display_name") or " ".join(
                value for value in (guardian.get("first_name"), guardian.get("last_name")) if value)
    return {"ok": True, "children": children}


def get_classrooms(session: Session) -> dict[str, Any]:
    rows = _rows(BRIDGE.rest(
        session,
        "GET",
        "classrooms",
        query={"location_id": f"eq.{CONFIG.location_id}", "select": "*", "order": "active.desc,name.asc"},
    ))
    children = _rows(BRIDGE.rest(
        session,
        "GET",
        "children",
        query={"location_id": f"eq.{CONFIG.location_id}", "active": "eq.true", "select": "id,classroom_id"},
    ))
    counts: dict[str, int] = {}
    for child in children:
        classroom_id = child.get("classroom_id")
        if classroom_id:
            counts[classroom_id] = counts.get(classroom_id, 0) + 1
    for room in rows:
        room["enrolled"] = counts.get(str(room.get("id")), 0)
        room["enrolled_count"] = room["enrolled"]
    return {"ok": True, "classrooms": rows}


def get_staff(session: Session) -> dict[str, Any]:
    rows = BRIDGE.rest(
        session,
        "GET",
        "staff_members",
        query={
            "location_id": f"eq.{CONFIG.location_id}",
            "select": "*,profiles(id,first_name,last_name,display_name,role,phone,login_id,active,permissions),staff_classrooms(classroom_id),staff_schedules(id,weekday,start_time,end_time)",
            "order": "hire_date.asc",
        },
    )
    staff_ids = _staff_ids(session)
    shifts = BRIDGE.rest(
        session,
        "GET",
        "staff_shifts",
        query={"staff_id": f"in.({','.join(staff_ids)})" if staff_ids else "eq.00000000-0000-0000-0000-000000000000", "select": "*", "order": "clocked_in_at.desc", "limit": "300"},
    )
    directory = BRIDGE.rest(
        session,
        "GET",
        "profiles",
        query={
            "location_id": f"eq.{CONFIG.location_id}",
            "active": "eq.true",
            "select": "id,first_name,last_name,display_name,role,phone,login_id,active",
            "order": "first_name.asc,last_name.asc",
        },
    )
    return {"ok": True, "staff": _rows(rows), "shifts": _rows(shifts), "directory": _rows(directory)}


def get_attendance(session: Session, attendance_date: Any = None) -> dict[str, Any]:
    day = require_date(attendance_date or date.today().isoformat(), "date")
    ids = _child_ids(session)
    if not ids:
        return {"ok": True, "date": day, "attendance": []}
    rows = BRIDGE.rest(
        session,
        "GET",
        "attendance",
        query={
            "child_id": f"in.({','.join(ids)})",
            "attendance_date": f"eq.{day}",
            "select": "*,children(id,first_name,last_name,classroom_id)",
            "order": "checked_in_at.desc",
        },
    )
    return {"ok": True, "date": day, "attendance": _rows(rows)}


def _range_query(session: Session, table: str, timestamp_column: str, start: Any, end: Any) -> list[dict[str, Any]]:
    start_day = require_date(start or (date.today().replace(day=1)).isoformat(), "from")
    end_day = require_date(end or date.today().isoformat(), "to")
    if start_day > end_day:
        raise DaycareError(400, "from must be on or before to", "validation_error")
    ids = _child_ids(session)
    if not ids:
        return []
    return _rows(BRIDGE.rest(
        session,
        "GET",
        table,
        query={
            "child_id": f"in.({','.join(ids)})",
            timestamp_column: [f"gte.{start_day}T00:00:00Z", f"lte.{end_day}T23:59:59.999Z"],
            "select": "*,children(id,first_name,last_name,classroom_id)",
            "order": f"{timestamp_column}.desc",
            "limit": "500",
        },
    ))


def get_logs(session: Session, start: Any = None, end: Any = None) -> dict[str, Any]:
    return {"ok": True, "logs": _range_query(session, "daily_logs", "occurred_at", start, end)}


def get_incidents(session: Session, start: Any = None, end: Any = None) -> dict[str, Any]:
    return {"ok": True, "incidents": _range_query(session, "incident_reports", "occurred_at", start, end)}


def get_announcements(session: Session) -> dict[str, Any]:
    rows = BRIDGE.rest(
        session,
        "GET",
        "announcements",
        query={
            "location_id": f"eq.{CONFIG.location_id}",
            "select": "*",
            "order": "pinned.desc,published_at.desc",
            "limit": "300",
        },
    )
    return {"ok": True, "announcements": _rows(rows)}


def get_threads(session: Session) -> dict[str, Any]:
    rows = BRIDGE.rest(
        session,
        "GET",
        "message_threads",
        query={
            "location_id": f"eq.{CONFIG.location_id}",
            "select": "*,thread_participants(profile_id,last_read_at,profiles(id,display_name,first_name,last_name,role,active)),messages(id,sender_id,body,attachment_path,reactions,created_at)",
            "order": "created_at.desc",
            "limit": "200",
        },
    )
    threads = _rows(rows)
    for thread in threads:
        messages = thread.get("messages") if isinstance(thread.get("messages"), list) else []
        latest = max(messages, key=lambda item: str(item.get("created_at") or ""), default=None)
        if latest:
            thread["last_message"] = latest.get("body") or (
                "Attachment" if latest.get("attachment_path") else "New message")
            thread["preview"] = thread["last_message"]
        participant = next((item for item in thread.get("thread_participants", [])
                            if item.get("profile_id") == session.profile.get("id")), None)
        last_read_at = str(participant.get("last_read_at") or "") if participant else ""
        thread["unread_count"] = sum(
            1 for message in messages
            if message.get("sender_id") != session.profile.get("id")
            and str(message.get("created_at") or "") > last_read_at)
    return {"ok": True, "threads": threads}


def get_thread(session: Session, thread_id: Any) -> dict[str, Any]:
    thread = _ensure_location_record(session, "message_threads", thread_id)
    messages = BRIDGE.rest(
        session,
        "GET",
        "messages",
        query={
            "thread_id": f"eq.{thread['id']}",
            "select": "*,profiles!messages_sender_id_fkey(id,display_name,first_name,last_name,role)",
            "order": "created_at.asc",
            "limit": "1000",
        },
    )
    participants = BRIDGE.rest(
        session,
        "GET",
        "thread_participants",
        query={
            "thread_id": f"eq.{thread['id']}",
            "select": "*,profiles(id,display_name,first_name,last_name,role,active)",
        },
    )
    message_rows = _rows(messages)
    for message in message_rows:
        sender = message.get("profiles") if isinstance(message.get("profiles"), dict) else None
        message["sender"] = sender
        message["sender_name"] = (
            sender.get("display_name")
            or " ".join(value for value in (sender.get("first_name"), sender.get("last_name")) if value)
            or "Team member"
        ) if sender else "Team member"
        message["mine"] = message.get("sender_id") == session.profile.get("id")
    participant_rows = _rows(participants)
    return {
        "ok": True,
        "thread": {
            **thread,
            "messages": message_rows,
            "participants": participant_rows,
            "thread_participants": participant_rows,
        },
    }


def get_notifications(session: Session) -> dict[str, Any]:
    rows = BRIDGE.rest(
        session,
        "GET",
        "notifications",
        query={
            "profile_id": f"eq.{session.profile['id']}",
            "select": "*",
            "order": "created_at.desc",
            "limit": "300",
        },
    )
    return {"ok": True, "notifications": _rows(rows)}


def get_billing(session: Session) -> dict[str, Any]:
    rows = BRIDGE.rest(
        session,
        "GET",
        "invoices",
        query={
            "location_id": f"eq.{CONFIG.location_id}",
            "select": "*,children(id,first_name,last_name),profiles!invoices_guardian_id_fkey(id,display_name,first_name,last_name,login_id,auth_email),payments(*)",
            "order": "issued_on.desc",
            "limit": "500",
        },
    )
    invoices = _rows(rows)
    for invoice in invoices:
        guardian = invoice.get("profiles")
        if guardian:
            invoice["guardian"] = guardian
            invoice["guardian_name"] = guardian.get("display_name") or " ".join(
                value for value in (guardian.get("first_name"), guardian.get("last_name")) if value)
    guardians = BRIDGE.rest(
        session,
        "GET",
        "profiles",
        query={
            "location_id": f"eq.{CONFIG.location_id}",
            "role": "eq.parent",
            "active": "eq.true",
            "select": "id,first_name,last_name,display_name,login_id,auth_email,phone,active",
            "order": "first_name.asc,last_name.asc",
        },
    )
    return {"ok": True, "invoices": invoices, "directory": _rows(guardians)}


def get_payroll(session: Session) -> dict[str, Any]:
    staff_ids = _staff_ids(session)
    if not staff_ids:
        return {"ok": True, "payroll": []}
    rows = BRIDGE.rest(
        session,
        "GET",
        "payroll_records",
        query={
            "staff_id": f"in.({','.join(staff_ids)})",
            "select": "*,staff_members(id,job_title,profiles(id,display_name,first_name,last_name,active))",
            "order": "period_start.desc",
            "limit": "500",
        },
    )
    return {"ok": True, "payroll": _rows(rows)}


def get_overview(session: Session) -> dict[str, Any]:
    children = get_children(session)["children"]
    classrooms = get_classrooms(session)["classrooms"]
    staff = get_staff(session)["staff"]
    attendance = get_attendance(session)["attendance"]
    invoices = get_billing(session)["invoices"]
    incidents = get_incidents(session, date.today().replace(day=1).isoformat(), date.today().isoformat())["incidents"]
    announcements = get_announcements(session)["announcements"]
    notifications = get_notifications(session)["notifications"]
    center = get_status(session).get("location") or {}
    active_children = [row for row in children if row.get("active")]
    present = [row for row in attendance if not row.get("checked_out_at")]
    due = [row for row in invoices if row.get("status") in {"due", "overdue"}]
    amount_due = sum(float(row.get("amount") or 0) for row in due)
    alerts: list[dict[str, Any]] = []
    for room in classrooms:
        if room.get("active") and int(room.get("enrolled") or 0) >= int(room.get("capacity") or 1):
            alerts.append({"kind": "capacity", "level": "warning", "title": f"{room.get('name')} is at capacity", "recordId": room.get("id")})
    if due:
        alerts.append({"kind": "billing", "level": "info", "title": f"{len(due)} invoices need attention"})
    return {
        "ok": True,
        "center": center,
        "location": center,
        "metrics": {
            "childrenActive": len(active_children),
            "presentToday": len(present),
            "staffActive": sum(1 for row in staff if (row.get("profiles") or {}).get("active")),
            "classroomsActive": sum(1 for row in classrooms if row.get("active")),
            "capacityTotal": sum(int(row.get("capacity") or 0) for row in classrooms if row.get("active")),
            "invoicesDue": len(due),
            "amountDue": round(amount_due, 2),
            "unreadNotifications": sum(1 for row in notifications if not row.get("read_at")),
            "openIncidents": len(incidents),
        },
        "alerts": alerts,
        "recent": {
            "attendance": attendance[:12],
            "incidents": incidents[:8],
            "announcements": announcements[:8],
        },
    }


def get_reports(session: Session, start: Any = None, end: Any = None) -> dict[str, Any]:
    start_day = require_date(start or date.today().replace(day=1).isoformat(), "from")
    end_day = require_date(end or date.today().isoformat(), "to")
    if start_day > end_day:
        raise DaycareError(400, "from must be on or before to", "validation_error")
    ids = _child_ids(session)
    attendance: list[dict[str, Any]] = []
    if ids:
        attendance = _rows(BRIDGE.rest(
            session,
            "GET",
            "attendance",
            query={
                "child_id": f"in.({','.join(ids)})",
                "attendance_date": [f"gte.{start_day}", f"lte.{end_day}"],
                "select": "*",
                "limit": "5000",
            },
        ))
    incidents = get_incidents(session, start_day, end_day)["incidents"]
    invoices = get_billing(session)["invoices"]
    invoices_period = [row for row in invoices if start_day <= str(row.get("issued_on") or "") <= end_day]
    children = get_children(session)["children"]
    classrooms = get_classrooms(session)["classrooms"]
    staff = get_staff(session)["staff"]
    active_children = [row for row in children if row.get("active")]
    active_classrooms = [row for row in classrooms if row.get("active")]
    capacity = sum(int(row.get("capacity") or 0) for row in active_classrooms)
    weekday_count = 0
    cursor = date.fromisoformat(start_day)
    last_day = date.fromisoformat(end_day)
    while cursor <= last_day:
        if cursor.weekday() < 5:
            weekday_count += 1
        cursor += timedelta(days=1)
    possible_child_days = len(active_children) * weekday_count
    attendance_rate = (len(attendance) / possible_child_days * 100) if possible_child_days else 0
    occupancy_rate = (len(active_children) / capacity * 100) if capacity else 0
    payments = _rows(BRIDGE.rest(
        session,
        "GET",
        "payments",
        query={
            "paid_at": [f"gte.{start_day}T00:00:00Z", f"lte.{end_day}T23:59:59.999999Z"],
            "status": "eq.succeeded",
            "select": "amount",
            "limit": "5000",
        },
    ))
    staff_ids = _staff_ids(session)
    shifts: list[dict[str, Any]] = []
    if staff_ids:
        shifts = _rows(BRIDGE.rest(
            session,
            "GET",
            "staff_shifts",
            query={
                "staff_id": f"in.({','.join(staff_ids)})",
                "started_at": [f"gte.{start_day}T00:00:00Z", f"lte.{end_day}T23:59:59.999999Z"],
                "select": "started_at,ended_at",
                "limit": "5000",
            },
        ))
    hours_worked = 0.0
    for shift in shifts:
        if not shift.get("started_at") or not shift.get("ended_at"):
            continue
        try:
            started = datetime.fromisoformat(str(shift["started_at"]).replace("Z", "+00:00"))
            ended = datetime.fromisoformat(str(shift["ended_at"]).replace("Z", "+00:00"))
            hours_worked += max(0, (ended - started).total_seconds() / 3600)
        except ValueError:
            continue
    due_invoices = [row for row in invoices if row.get("status") in {"due", "overdue"}]
    amount_due = 0.0
    for invoice in due_invoices:
        paid = sum(float(payment.get("amount") or 0) for payment in (invoice.get("payments") or []))
        amount_due += max(0, float(invoice.get("amount") or 0) - paid)
    metrics = {
        "attendance_rate": round(attendance_rate, 1),
        "occupancy_rate": round(occupancy_rate, 1),
        "incident_count": len(incidents),
        "amount_collected": round(sum(float(row.get("amount") or 0) for row in payments), 2),
        "attendance_days": len(attendance),
        "children_active": len(active_children),
        "classrooms_active": len(active_classrooms),
        "staff_active": sum(1 for row in staff if (row.get("profiles") or {}).get("active")),
        "hours_worked": round(hours_worked, 2),
        "amount_due": round(amount_due, 2),
        "invoices_due": len(due_invoices),
    }
    return {
        "ok": True,
        "from": start_day,
        "to": end_day,
        "metrics": metrics,
        "summary": {
            "attendanceRecords": len(attendance),
            "completedDays": sum(1 for row in attendance if row.get("status") == "completed"),
            "incidentCount": len(incidents),
            "invoicesIssued": len(invoices_period),
            "invoicedAmount": round(sum(float(row.get("amount") or 0) for row in invoices_period), 2),
            "paidAmount": round(sum(float(row.get("amount") or 0) for row in invoices_period if row.get("status") == "paid"), 2),
        },
        "attendance": attendance,
        "incidents": incidents,
        "invoices": invoices_period,
    }


def save_settings(session: Session, body: dict[str, Any]) -> dict[str, Any]:
    source = body.get("settings") if isinstance(body.get("settings"), dict) else body
    update = {
        "name": require_text(source.get("name"), "name", maximum=160),
        "address": require_text(source.get("address"), "address", maximum=500, optional=True),
        "phone": require_text(source.get("phone"), "phone", maximum=40, optional=True),
        "timezone": require_text(source.get("timezone") or "America/New_York", "timezone", maximum=80),
        "opens_at": require_time(
            _body_value(source, "opens_at", "opensAt", source.get("opening_time")), "opens_at"),
        "closes_at": require_time(
            _body_value(source, "closes_at", "closesAt", source.get("closing_time")), "closes_at"),
    }
    rows = BRIDGE.rest(
        session,
        "PATCH",
        "locations",
        query={"id": f"eq.{CONFIG.location_id}"},
        body=update,
        prefer="return=representation",
    )
    return {"ok": True, "settings": _single(rows, "Daycare location")}


def save_child(session: Session, body: dict[str, Any]) -> dict[str, Any]:
    source = body.get("child") if isinstance(body.get("child"), dict) else body
    child_id = source.get("id")
    classroom_id = require_uuid(_body_value(source, "classroom_id", "classroomId"), "classroom_id", optional=True)
    if classroom_id:
        _ensure_location_record(session, "classrooms", classroom_id)
    record = {
        "first_name": require_text(_body_value(source, "first_name", "firstName"), "first_name", maximum=100),
        "last_name": require_text(_body_value(source, "last_name", "lastName"), "last_name", maximum=100),
        "preferred_name": require_text(_body_value(source, "preferred_name", "preferredName"), "preferred_name", maximum=100, optional=True),
        "birth_date": require_date(_body_value(source, "birth_date", "birthDate"), "birth_date"),
        "classroom_id": classroom_id,
        "allergies": require_text(source.get("allergies"), "allergies", maximum=1000, optional=True),
        "medical_notes": require_text(_body_value(source, "medical_notes", "medicalNotes"), "medical_notes", maximum=4000, optional=True),
        "pickup_notes": require_text(_body_value(source, "pickup_notes", "pickupNotes"), "pickup_notes", maximum=4000, optional=True),
        "enrollment_date": require_date(_body_value(source, "enrollment_date", "enrollmentDate") or date.today().isoformat(), "enrollment_date"),
        "active": bool(source.get("active", True)),
    }
    provision: dict[str, Any] | None = None
    guardian_id = _body_value(source, "guardian_profile_id", "guardianProfileId")
    guardian_email = _body_value(source, "guardian_email", "guardianEmail")
    guardian_fields_present = any(_body_value(source, key, alias) for key, alias in (
        ("guardian_first_name", "guardianFirstName"),
        ("guardian_last_name", "guardianLastName"),
        ("guardian_phone", "guardianPhone"),
    ))
    if not child_id and guardian_fields_present and not guardian_email and not guardian_id:
        raise DaycareError(
            400,
            "guardian_email is required when provisioning a guardian",
            "validation_error",
        )
    if not child_id and guardian_email:
        provision = BRIDGE.edge_function(session, "provision-user", {
            "action": "ensure-guardian",
            "email": require_text(guardian_email, "guardian_email", maximum=254),
            "first_name": require_text(_body_value(source, "guardian_first_name", "guardianFirstName"), "guardian_first_name", maximum=100),
            "last_name": require_text(_body_value(source, "guardian_last_name", "guardianLastName"), "guardian_last_name", maximum=100),
        })
        guardian_id = provision.get("profile_id")
        if guardian_id:
            guardian_id = require_uuid(guardian_id, "guardian_profile_id")
        guardian_phone = require_text(
            _body_value(source, "guardian_phone", "guardianPhone"),
            "guardian_phone",
            maximum=40,
            optional=True,
        )
        if guardian_phone and guardian_id:
            BRIDGE.rest(
                session,
                "PATCH",
                "profiles",
                query={"id": f"eq.{guardian_id}", "location_id": f"eq.{CONFIG.location_id}"},
                body={"phone": guardian_phone},
                prefer="return=minimal",
            )
    if guardian_id:
        record["guardian_profile_id"] = require_uuid(guardian_id, "guardian_profile_id")
    if child_id:
        existing = _ensure_location_record(session, "children", child_id)
        rows = BRIDGE.rest(session, "PATCH", "children", query={"id": f"eq.{existing['id']}"}, body=record, prefer="return=representation")
    else:
        record["location_id"] = CONFIG.location_id
        rows = BRIDGE.rest(session, "POST", "children", body=record, prefer="return=representation")
    response = {"ok": True, "child": _single(rows, "Child")}
    if provision:
        response["provision"] = {key: provision.get(key) for key in ("profile_id", "login_id", "pin", "existing") if key in provision}
    return response


def deactivate_child(session: Session, body: dict[str, Any]) -> dict[str, Any]:
    child = _ensure_location_record(session, "children", body.get("id") or body.get("childId"))
    rows = BRIDGE.rest(session, "PATCH", "children", query={"id": f"eq.{child['id']}"}, body={"active": False}, prefer="return=representation")
    return {"ok": True, "child": _single(rows, "Child")}


def save_classroom(session: Session, body: dict[str, Any]) -> dict[str, Any]:
    source = body.get("classroom") if isinstance(body.get("classroom"), dict) else body
    record = {
        "name": require_text(source.get("name"), "name", maximum=120),
        "age_group": require_text(_body_value(source, "age_group", "ageGroup"), "age_group", maximum=120),
        "capacity": require_int(source.get("capacity"), "capacity", 1, 500),
        "ratio_children": require_int(_body_value(source, "ratio_children", "ratioChildren", 6), "ratio_children", 1, 100),
        "color": require_text(source.get("color") or "#2DD4BF", "color", maximum=20),
        "active": bool(source.get("active", True)),
    }
    if source.get("id"):
        room = _ensure_location_record(session, "classrooms", source.get("id"))
        rows = BRIDGE.rest(session, "PATCH", "classrooms", query={"id": f"eq.{room['id']}"}, body=record, prefer="return=representation")
    else:
        record["location_id"] = CONFIG.location_id
        rows = BRIDGE.rest(session, "POST", "classrooms", body=record, prefer="return=representation")
    return {"ok": True, "classroom": _single(rows, "Classroom")}


def archive_classroom(session: Session, body: dict[str, Any]) -> dict[str, Any]:
    room = _ensure_location_record(session, "classrooms", body.get("id") or body.get("classroomId"))
    children = BRIDGE.rest(session, "GET", "children", query={"classroom_id": f"eq.{room['id']}", "active": "eq.true", "select": "id", "limit": "1"})
    if _rows(children):
        raise DaycareError(409, "Move active children before archiving this classroom", "classroom_not_empty")
    rows = BRIDGE.rest(session, "PATCH", "classrooms", query={"id": f"eq.{room['id']}"}, body={"active": False}, prefer="return=representation")
    return {"ok": True, "classroom": _single(rows, "Classroom")}


def _validate_classroom_ids(session: Session, values: Any) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list) or len(values) > 50:
        raise DaycareError(400, "classroom_ids must be a list", "validation_error")
    ids = list(dict.fromkeys(require_uuid(value, "classroom_id") for value in values))
    for classroom_id in ids:
        _ensure_location_record(session, "classrooms", classroom_id)
    return [str(value) for value in ids]


def save_staff(session: Session, body: dict[str, Any]) -> dict[str, Any]:
    source = body.get("staff") if isinstance(body.get("staff"), dict) else body
    classroom_ids = _validate_classroom_ids(session, _body_value(source, "classroom_ids", "classroomIds", []))
    staff_id = source.get("id") or _body_value(source, "staff_id", "staffId")
    requested_role = source.get("role")
    role = enum_value(requested_role or "staff", "role", {"staff", "manager"})
    if not staff_id:
        result = BRIDGE.edge_function(session, "provision-user", {
            "action": "create-staff",
            "first_name": require_text(_body_value(source, "first_name", "firstName"), "first_name", maximum=100),
            "last_name": require_text(_body_value(source, "last_name", "lastName"), "last_name", maximum=100),
            "role": role,
            "job_title": require_text(_body_value(source, "job_title", "jobTitle"), "job_title", maximum=160),
            "hourly_rate": require_number(_body_value(source, "hourly_rate", "hourlyRate"), "hourly_rate", maximum=Decimal("10000"), optional=True),
            "classroom_ids": classroom_ids,
        })
        return {"ok": True, "staff": result, "provision": {key: result.get(key) for key in ("profile_id", "login_id", "pin", "existing") if key in result}}
    staff = _ensure_location_record(session, "staff_members", staff_id)
    profile_id = require_uuid(staff.get("profile_id"), "profile_id")
    current_profile = _single(
        BRIDGE.rest(
            session,
            "GET",
            "profiles",
            query={
                "id": f"eq.{profile_id}",
                "location_id": f"eq.{CONFIG.location_id}",
                "select": "id,role,active",
                "limit": "1",
            },
        ),
        "Staff profile",
    )
    if requested_role is None:
        current_role = str(current_profile.get("role") or "")
        if current_role not in {"staff", "manager", "admin"}:
            raise DaycareError(409, "Staff profile has an unsupported role", "role_conflict")
        role = current_role
    profile_update = {
        "first_name": require_text(_body_value(source, "first_name", "firstName"), "first_name", maximum=100),
        "last_name": require_text(_body_value(source, "last_name", "lastName"), "last_name", maximum=100),
        "phone": require_text(source.get("phone"), "phone", maximum=40, optional=True),
        "role": role,
        "active": bool(source.get("active", True)),
    }
    member_update = {
        "job_title": require_text(_body_value(source, "job_title", "jobTitle"), "job_title", maximum=160),
        "hourly_rate": require_number(_body_value(source, "hourly_rate", "hourlyRate"), "hourly_rate", maximum=Decimal("10000"), optional=True),
        "hire_date": require_date(_body_value(source, "hire_date", "hireDate"), "hire_date", optional=True),
    }
    BRIDGE.rest(session, "PATCH", "profiles", query={"id": f"eq.{profile_id}", "location_id": f"eq.{CONFIG.location_id}"}, body=profile_update, prefer="return=representation")
    rows = BRIDGE.rest(session, "PATCH", "staff_members", query={"id": f"eq.{staff['id']}"}, body=member_update, prefer="return=representation")
    if "classroom_ids" in source or "classroomIds" in source:
        BRIDGE.rest(session, "DELETE", "staff_classrooms", query={"staff_id": f"eq.{staff['id']}"}, prefer="return=minimal")
        if classroom_ids:
            BRIDGE.rest(session, "POST", "staff_classrooms", body=[{"staff_id": staff["id"], "classroom_id": classroom_id} for classroom_id in classroom_ids], prefer="return=minimal")
    return {"ok": True, "staff": _single(rows, "Staff member")}


def deactivate_staff(session: Session, body: dict[str, Any]) -> dict[str, Any]:
    staff = _ensure_location_record(session, "staff_members", body.get("id") or body.get("staffId"))
    profile_id = require_uuid(staff.get("profile_id"), "profile_id")
    if profile_id == session.profile.get("id"):
        raise DaycareError(409, "You cannot deactivate your own active session", "self_deactivation")
    rows = BRIDGE.rest(session, "PATCH", "profiles", query={"id": f"eq.{profile_id}", "location_id": f"eq.{CONFIG.location_id}"}, body={"active": False}, prefer="return=representation")
    return {"ok": True, "profile": _single(rows, "Staff profile")}


def save_schedule(session: Session, body: dict[str, Any]) -> dict[str, Any]:
    staff = _ensure_location_record(session, "staff_members", body.get("staff_id") or body.get("staffId"))
    schedules = body.get("schedules")
    if not isinstance(schedules, list) or len(schedules) > 7:
        raise DaycareError(400, "schedules must contain at most seven days", "validation_error")
    clean: list[dict[str, Any]] = []
    seen: set[int] = set()
    for schedule in schedules:
        if not isinstance(schedule, dict):
            raise DaycareError(400, "Each schedule must be an object", "validation_error")
        weekday = require_int(schedule.get("weekday"), "weekday", 0, 6)
        if weekday in seen:
            raise DaycareError(409, "Only one schedule per weekday is allowed", "conflict")
        seen.add(weekday)
        start_time = require_time(_body_value(schedule, "start_time", "startTime"), "start_time")
        end_time = require_time(_body_value(schedule, "end_time", "endTime"), "end_time")
        if start_time >= end_time:
            raise DaycareError(400, "Schedule end time must be after start time", "validation_error")
        clean.append({"staff_id": staff["id"], "weekday": weekday, "start_time": start_time, "end_time": end_time})
    BRIDGE.rest(session, "DELETE", "staff_schedules", query={"staff_id": f"eq.{staff['id']}"}, prefer="return=minimal")
    rows = []
    if clean:
        rows = BRIDGE.rest(session, "POST", "staff_schedules", body=clean, prefer="return=representation")
    return {"ok": True, "schedules": _rows(rows)}


def set_attendance(session: Session, body: dict[str, Any]) -> dict[str, Any]:
    child = _ensure_location_record(session, "children", body.get("child_id") or body.get("childId"))
    day = require_date(body.get("date") or date.today().isoformat(), "date")
    action = enum_value(body.get("action"), "action", {"check-in", "check-out"})
    existing = _rows(BRIDGE.rest(session, "GET", "attendance", query={"child_id": f"eq.{child['id']}", "attendance_date": f"eq.{day}", "select": "*", "limit": "1"}))
    timestamp = now_iso()
    notes = require_text(body.get("notes"), "notes", maximum=1000, optional=True)
    if action == "check-out":
        if not existing or existing[0].get("checked_out_at"):
            raise DaycareError(409, "This child is not currently checked in", "attendance_not_open")
        rows = BRIDGE.rest(session, "PATCH", "attendance", query={"id": f"eq.{existing[0]['id']}"}, body={"checked_out_at": timestamp, "checked_out_by": session.profile["id"], "status": "completed", "notes": notes}, prefer="return=representation")
    else:
        record = {"child_id": child["id"], "attendance_date": day, "checked_in_at": timestamp, "checked_out_at": None, "checked_in_by": session.profile["id"], "checked_out_by": None, "status": "present", "notes": notes}
        rows = BRIDGE.rest(session, "POST", "attendance", query={"on_conflict": "child_id,attendance_date"}, body=record, prefer="resolution=merge-duplicates,return=representation")
    return {"ok": True, "attendance": _single(rows, "Attendance")}


def sign_out_all(session: Session, body: dict[str, Any]) -> dict[str, Any]:
    day = require_date(body.get("date") or date.today().isoformat(), "date")
    ids = _child_ids(session)
    if not ids:
        return {"ok": True, "count": 0, "attendance": []}
    rows = BRIDGE.rest(
        session,
        "PATCH",
        "attendance",
        query={"child_id": f"in.({','.join(ids)})", "attendance_date": f"eq.{day}", "checked_out_at": "is.null"},
        body={"checked_out_at": now_iso(), "checked_out_by": session.profile["id"], "status": "completed"},
        prefer="return=representation",
    )
    records = _rows(rows)
    return {"ok": True, "count": len(records), "attendance": records}


def save_log(session: Session, body: dict[str, Any]) -> dict[str, Any]:
    source = body.get("log") if isinstance(body.get("log"), dict) else body
    child = _ensure_location_record(session, "children", source.get("child_id") or source.get("childId"))
    nap_value = _body_value(source, "nap_minutes", "napMinutes")
    record = {
        "child_id": child["id"],
        "author_id": session.profile["id"],
        "log_date": require_date(_body_value(source, "log_date", "logDate") or date.today().isoformat(), "log_date"),
        "activity": require_text(source.get("activity"), "activity", maximum=1000, optional=True),
        "mood": require_text(source.get("mood"), "mood", maximum=100, optional=True),
        "meal": require_text(source.get("meal"), "meal", maximum=1000, optional=True),
        "nap_minutes": None if nap_value in (None, "") else require_int(nap_value, "nap_minutes", 0, 1440),
        "bathroom": require_text(source.get("bathroom"), "bathroom", maximum=500, optional=True),
        "notes": require_text(source.get("notes"), "notes", maximum=4000, optional=True),
        "occurred_at": require_timestamp(_body_value(source, "occurred_at", "occurredAt") or now_iso(), "occurred_at"),
    }
    rows = BRIDGE.rest(session, "POST", "daily_logs", body=record, prefer="return=representation")
    return {"ok": True, "log": _single(rows, "Daily log")}


def save_incident(session: Session, body: dict[str, Any]) -> dict[str, Any]:
    source = body.get("incident") if isinstance(body.get("incident"), dict) else body
    child = _ensure_location_record(session, "children", source.get("child_id") or source.get("childId"))
    notified_supplied = "parent_notified_at" in source or "parentNotifiedAt" in source
    notified_value = _body_value(source, "parent_notified_at", "parentNotifiedAt")
    record = {
        "child_id": child["id"],
        "reporter_id": session.profile["id"],
        "occurred_at": require_timestamp(_body_value(source, "occurred_at", "occurredAt") or now_iso(), "occurred_at"),
        "location_detail": require_text(_body_value(source, "location_detail", "locationDetail"), "location_detail", maximum=500),
        "severity": enum_value(source.get("severity"), "severity", {"minor", "moderate", "serious"}),
        "description": require_text(source.get("description"), "description", maximum=4000),
        "action_taken": require_text(_body_value(source, "action_taken", "actionTaken"), "action_taken", maximum=4000),
        "witness_names": require_text(_body_value(source, "witness_names", "witnessNames"), "witness_names", maximum=1000, optional=True),
        "parent_notified_at": (
            require_timestamp(notified_value, "parent_notified_at", optional=True)
            if notified_supplied else now_iso()
        ),
    }
    rows = BRIDGE.rest(session, "POST", "incident_reports", body=record, prefer="return=representation")
    return {"ok": True, "incident": _single(rows, "Incident")}


def save_announcement(session: Session, body: dict[str, Any]) -> dict[str, Any]:
    source = body.get("announcement") if isinstance(body.get("announcement"), dict) else body
    record = {
        "audience": enum_value(source.get("audience"), "audience", {"everyone", "parents", "staff"}),
        "title": require_text(source.get("title"), "title", maximum=200),
        "body": require_text(source.get("body"), "body", maximum=8000),
        "pinned": bool(source.get("pinned", False)),
        "expires_at": require_timestamp(_body_value(source, "expires_at", "expiresAt"), "expires_at", optional=True),
    }
    if source.get("id"):
        item = _ensure_location_record(session, "announcements", source.get("id"))
        rows = BRIDGE.rest(session, "PATCH", "announcements", query={"id": f"eq.{item['id']}"}, body=record, prefer="return=representation")
    else:
        record.update({"location_id": CONFIG.location_id, "author_id": session.profile["id"]})
        rows = BRIDGE.rest(session, "POST", "announcements", body=record, prefer="return=representation")
    return {"ok": True, "announcement": _single(rows, "Announcement")}


def delete_announcement(session: Session, body: dict[str, Any]) -> dict[str, Any]:
    item = _ensure_location_record(
        session, "announcements", body.get("id") or body.get("announcement_id"))
    BRIDGE.rest(session, "DELETE", "announcements", query={"id": f"eq.{item['id']}"}, prefer="return=minimal")
    return {"ok": True, "id": item["id"]}


def _validate_participants(session: Session, participant_ids: Any) -> list[str]:
    if not isinstance(participant_ids, list) or not participant_ids or len(participant_ids) > 500:
        raise DaycareError(400, "participants must be a non-empty list", "validation_error")
    ids = [str(require_uuid(value, "participant_id")) for value in participant_ids]
    ids.append(str(session.profile["id"]))
    ids = list(dict.fromkeys(ids))
    rows = BRIDGE.rest(session, "GET", "profiles", query={"id": f"in.({','.join(ids)})", "location_id": f"eq.{CONFIG.location_id}", "active": "eq.true", "select": "id"})
    found = {str(row.get("id")) for row in _rows(rows)}
    if found != set(ids):
        raise DaycareError(403, "Every participant must be active at this daycare location", "participant_location_mismatch")
    return ids


def save_thread(session: Session, body: dict[str, Any]) -> dict[str, Any]:
    source = body.get("thread") if isinstance(body.get("thread"), dict) else body
    kind = enum_value(source.get("kind") or "direct", "kind", {"direct", "group", "broadcast"})
    participants = _validate_participants(
        session,
        source.get("participants") or source.get("participant_ids") or source.get("participantIds"),
    )
    if kind == "direct" and len(participants) != 2:
        raise DaycareError(400, "Direct threads require exactly two participants", "validation_error")
    title = require_text(source.get("title"), "title", maximum=200, optional=kind == "direct")
    created = BRIDGE.rest(session, "POST", "message_threads", body={"location_id": CONFIG.location_id, "created_by": session.profile["id"], "title": title, "kind": kind}, prefer="return=representation")
    thread = _single(created, "Message thread")
    try:
        BRIDGE.rest(session, "POST", "thread_participants", body=[{"thread_id": thread["id"], "profile_id": profile_id} for profile_id in participants], prefer="return=minimal")
    except DaycareError:
        try:
            BRIDGE.rest(session, "DELETE", "message_threads", query={"id": f"eq.{thread['id']}"}, prefer="return=minimal")
        except DaycareError:
            pass
        raise
    return {"ok": True, "thread": thread, "participants": participants}


def rename_thread(session: Session, body: dict[str, Any]) -> dict[str, Any]:
    thread = _ensure_location_record(
        session, "message_threads", body.get("id") or body.get("thread_id") or body.get("threadId"))
    title = require_text(body.get("title"), "title", maximum=200)
    rows = BRIDGE.rest(session, "PATCH", "message_threads", query={"id": f"eq.{thread['id']}"}, body={"title": title}, prefer="return=representation")
    return {"ok": True, "thread": _single(rows, "Message thread")}


def leave_thread(session: Session, body: dict[str, Any]) -> dict[str, Any]:
    thread = _ensure_location_record(session, "message_threads", body.get("id") or body.get("threadId"))
    BRIDGE.rest(session, "DELETE", "thread_participants", query={"thread_id": f"eq.{thread['id']}", "profile_id": f"eq.{session.profile['id']}"}, prefer="return=minimal")
    return {"ok": True, "threadId": thread["id"]}


def send_message(session: Session, body: dict[str, Any]) -> dict[str, Any]:
    thread = _ensure_location_record(session, "message_threads", body.get("thread_id") or body.get("threadId"))
    message_text = require_text(body.get("body"), "body", maximum=4000, optional=bool(body.get("attachment_path") or body.get("attachmentPath"))) or ""
    attachment = _body_value(body, "attachment_path", "attachmentPath")
    if attachment:
        attachment = validate_storage_path(attachment)
        if not attachment.startswith(f"chat/{thread['id']}/"):
            raise DaycareError(403, "Attachment path does not belong to this thread", "forbidden")
    rows = BRIDGE.rest(session, "POST", "messages", body={"thread_id": thread["id"], "sender_id": session.profile["id"], "body": message_text, "attachment_path": attachment}, prefer="return=representation")
    message = _single(rows, "Message")
    return {"ok": True, "message": message}


def react_message(session: Session, body: dict[str, Any]) -> dict[str, Any]:
    message_id = require_uuid(
        body.get("id") or body.get("message_id") or body.get("messageId"), "message_id")
    reaction = enum_value(body.get("reaction"), "reaction", {"👍", "❤️", "✅"})
    rows = BRIDGE.rest(session, "GET", "messages", query={"id": f"eq.{message_id}", "select": "id,thread_id,reactions", "limit": "1"})
    message = _single(rows, "Message")
    _ensure_location_record(session, "message_threads", message.get("thread_id"))
    current = message.get("reactions") if isinstance(message.get("reactions"), list) else []
    actor = str(session.profile["id"])
    def same_reaction(value):
        return isinstance(value, dict) and value.get("profile_id") == actor and value.get("reaction") == reaction
    already_set = any(same_reaction(value) for value in current)
    updated = [value for value in current if not same_reaction(value) and value != actor]
    if not already_set:
        updated.append({"profile_id": actor, "reaction": reaction})
    result = BRIDGE.rest(session, "PATCH", "messages", query={"id": f"eq.{message_id}"}, body={"reactions": updated}, prefer="return=representation")
    return {"ok": True, "message": _single(result, "Message")}


def mark_notifications_read(session: Session, body: dict[str, Any]) -> dict[str, Any]:
    ids = body.get("ids") if "ids" in body else body.get("notification_ids")
    query: dict[str, Any] = {"profile_id": f"eq.{session.profile['id']}", "read_at": "is.null"}
    if ids is not None:
        if not isinstance(ids, list) or len(ids) > 500:
            raise DaycareError(400, "ids must be a list", "validation_error")
        clean = [str(require_uuid(value, "notification_id")) for value in ids]
        if not clean:
            return {"ok": True, "count": 0, "notifications": []}
        query["id"] = f"in.({','.join(clean)})"
    rows = BRIDGE.rest(session, "PATCH", "notifications", query=query, body={"read_at": now_iso()}, prefer="return=representation")
    records = _rows(rows)
    return {"ok": True, "count": len(records), "notifications": records}


def save_invoice(session: Session, body: dict[str, Any]) -> dict[str, Any]:
    source = body.get("invoice") if isinstance(body.get("invoice"), dict) else body
    guardian_id = require_uuid(_body_value(source, "guardian_id", "guardianId"), "guardian_id")
    guardian = _single(BRIDGE.rest(session, "GET", "profiles", query={"id": f"eq.{guardian_id}", "location_id": f"eq.{CONFIG.location_id}", "role": "eq.parent", "select": "id", "limit": "1"}), "Guardian")
    child_id = require_uuid(_body_value(source, "child_id", "childId"), "child_id", optional=True)
    if child_id:
        child = _ensure_location_record(session, "children", child_id)
        if child.get("guardian_profile_id") and child.get("guardian_profile_id") != guardian["id"]:
            raise DaycareError(409, "The selected child is not linked to that guardian", "guardian_mismatch")
    status = str(source.get("status") or "due").strip().lower()
    if status == "open":
        status = "due"
    record = {
        "guardian_id": guardian["id"],
        "child_id": child_id,
        "invoice_number": require_text(
            _body_value(source, "invoice_number", "invoiceNumber")
            or f"DC-{date.today().strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}",
            "invoice_number",
            maximum=80,
        ),
        "description": require_text(source.get("description"), "description", maximum=1000),
        "amount": require_number(source.get("amount"), "amount", maximum=Decimal("1000000")),
        "status": enum_value(status, "status", {"draft", "due", "paid", "void", "overdue"}),
        "issued_on": require_date(_body_value(source, "issued_on", "issuedOn") or date.today().isoformat(), "issued_on"),
        "due_on": require_date(_body_value(source, "due_on", "dueOn"), "due_on"),
    }
    if record["due_on"] < record["issued_on"]:
        raise DaycareError(400, "due_on cannot be before issued_on", "validation_error")
    if source.get("id"):
        invoice = _ensure_location_record(session, "invoices", source.get("id"))
        rows = BRIDGE.rest(session, "PATCH", "invoices", query={"id": f"eq.{invoice['id']}"}, body=record, prefer="return=representation")
    else:
        record["location_id"] = CONFIG.location_id
        rows = BRIDGE.rest(session, "POST", "invoices", body=record, prefer="return=representation")
    return {"ok": True, "invoice": _single(rows, "Invoice")}


def record_invoice_payment(session: Session, body: dict[str, Any]) -> dict[str, Any]:
    invoice = _ensure_location_record(session, "invoices", body.get("invoice_id") or body.get("invoiceId"))
    source = body.get("payment") if isinstance(body.get("payment"), dict) else body
    result = BRIDGE.rpc(session, "record_invoice_payment", {
        "p_invoice_id": invoice["id"],
        "p_amount": require_number(source.get("amount"), "amount", minimum=Decimal("0.01"), maximum=Decimal("1000000")),
        "p_method_label": require_text(_body_value(source, "method_label", "methodLabel") or "Manual", "method_label", maximum=120),
        "p_reference": require_text(source.get("reference"), "reference", maximum=300, optional=True),
        "p_paid_at": require_timestamp(_body_value(source, "paid_at", "paidAt") or now_iso(), "paid_at"),
        "p_provider": enum_value(source.get("provider") or "manual", "provider", {"manual", "stripe"}),
        "p_provider_reference": require_text(_body_value(source, "provider_reference", "providerReference"), "provider_reference", maximum=300, optional=True),
        "p_idempotency_key": require_text(_body_value(source, "idempotency_key", "idempotencyKey"), "idempotency_key", maximum=200, optional=True),
    })
    payment = result[0] if isinstance(result, list) and result else result
    return {"ok": True, "payment": payment}


def save_payroll(session: Session, body: dict[str, Any]) -> dict[str, Any]:
    source = body.get("payroll") if isinstance(body.get("payroll"), dict) else body
    staff = _ensure_location_record(session, "staff_members", _body_value(source, "staff_id", "staffId"))
    record = {
        "staff_id": staff["id"],
        "period_start": require_date(_body_value(source, "period_start", "periodStart"), "period_start"),
        "period_end": require_date(_body_value(source, "period_end", "periodEnd"), "period_end"),
        "regular_hours": require_number(_body_value(source, "regular_hours", "regularHours", 0), "regular_hours", maximum=Decimal("1000")),
        "overtime_hours": require_number(_body_value(source, "overtime_hours", "overtimeHours", 0), "overtime_hours", maximum=Decimal("1000")),
        "gross_pay": require_number(_body_value(source, "gross_pay", "grossPay", 0), "gross_pay", maximum=Decimal("1000000")),
        "deductions": require_number(source.get("deductions", 0), "deductions", maximum=Decimal("1000000")),
        "status": enum_value(source.get("status") or "draft", "status", {"draft", "approved"}),
    }
    if record["period_end"] < record["period_start"]:
        raise DaycareError(400, "period_end cannot be before period_start", "validation_error")
    if record["deductions"] > record["gross_pay"]:
        raise DaycareError(400, "deductions cannot exceed gross pay", "validation_error")
    if source.get("id"):
        payroll_id = require_uuid(source.get("id"), "payroll_id")
        existing = _single(BRIDGE.rest(session, "GET", "payroll_records", query={"id": f"eq.{payroll_id}", "staff_id": f"eq.{staff['id']}", "select": "*", "limit": "1"}), "Payroll record")
        if existing.get("status") == "paid":
            raise DaycareError(409, "Paid payroll records cannot be edited", "payroll_already_paid")
        rows = BRIDGE.rest(session, "PATCH", "payroll_records", query={"id": f"eq.{payroll_id}"}, body=record, prefer="return=representation")
    else:
        rows = BRIDGE.rest(session, "POST", "payroll_records", body=record, prefer="return=representation")
    return {"ok": True, "payroll": _single(rows, "Payroll record")}


def mark_payroll_paid(session: Session, body: dict[str, Any]) -> dict[str, Any]:
    payroll_id = require_uuid(
        body.get("id") or body.get("payroll_id") or body.get("payrollId"), "payroll_id")
    result = BRIDGE.rpc(session, "mark_payroll_paid", {
        "p_payroll_id": payroll_id,
        "p_paid_at": require_timestamp(_body_value(body, "paid_at", "paidAt") or now_iso(), "paid_at"),
        "p_reference": require_text(body.get("reference"), "reference", maximum=300, optional=True),
    })
    payroll = result[0] if isinstance(result, list) and result else result
    return {"ok": True, "payroll": payroll}


def sign_media(session: Session, body: dict[str, Any], *, upload: bool) -> dict[str, Any]:
    purpose = str(body.get("purpose") or "").strip().lower()
    bucket_value = body.get("bucket")
    path_value = body.get("path")
    if upload and purpose == "message":
        thread = _ensure_location_record(
            session, "message_threads", body.get("thread_id") or body.get("threadId"))
        filename = require_text(body.get("filename"), "filename", maximum=240)
        assert filename is not None
        filename = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(filename).name).strip(".-") or "attachment"
        path_value = f"chat/{thread['id']}/{secrets.token_hex(16)}-{filename}"
        bucket_value = "message-attachments"
    elif not bucket_value and isinstance(path_value, str) and path_value.startswith("chat/"):
        bucket_value = "message-attachments"
    bucket = require_text(bucket_value, "bucket", maximum=80)
    path = validate_storage_path(path_value)
    parts = path.split("/")
    first = parts[0]
    if bucket == "child-photos":
        _ensure_location_record(session, "children", first)
    elif bucket == "message-attachments":
        if len(parts) < 3 or first != "chat":
            raise DaycareError(400, "Message media paths must use chat/thread-id/file", "validation_error")
        _ensure_location_record(session, "message_threads", parts[1])
    elif bucket == "avatars" and first != session.profile.get("id"):
        target = _single(BRIDGE.rest(session, "GET", "profiles", query={"id": f"eq.{first}", "location_id": f"eq.{CONFIG.location_id}", "select": "id", "limit": "1"}), "Profile")
        if not target:
            raise DaycareError(403, "Avatar path is outside this location", "forbidden")
    signed = BRIDGE.storage_sign(session, str(bucket), path, upload=upload)
    if upload:
        return {
            "ok": True,
            "media": signed,
            "upload_url": signed.get("signedUrl"),
            "path": signed.get("path"),
            "token": signed.get("token"),
        }
    return {
        "ok": True,
        "media": signed,
        "url": signed.get("signedUrl"),
        "path": signed.get("path"),
    }
