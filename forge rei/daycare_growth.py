#!/usr/bin/env python3
"""Daycare growth — Ads + Social monitoring for the daycare business.

Reuses the Agency engines (``agency_ads`` / ``agency_social``) so there is ONE
implementation of the Meta + Metricool logic, but runs them with the DAYCARE's
own credentials read from ``forge-daycare/config/daycare.env`` (``META_ACCESS_TOKEN``,
``METRICOOL_USER_TOKEN``, …).

The engines read their tokens from ``os.environ``. To run them under the daycare's
account without disturbing the Agency workspace, we swap the relevant env keys for
the duration of a single call under a process lock, then restore. This is a
single-tenant / low-concurrency assumption appropriate to the owner's box; if the
daycare and the agency ever run live campaigns concurrently, parametrize the engine
functions with an explicit token instead.

When the daycare tokens are blank (the default until the owner adds them), the
engines fall back to their built-in mock/"not connected" payloads, so the UI renders
cleanly and lights up the moment a key is dropped into ``daycare.env`` — no rebuild.

Stdlib only; read-only monitoring. Launching ads / publishing posts stays an
approval-gated action added later, never autonomous.
"""

from __future__ import annotations

import contextlib
import os
import threading

import agency_ads
import agency_eco
import agency_social
import daycare_context
import daycare_supabase

_ENV_LOCK = threading.Lock()
_ADS_KEYS = ("META_ACCESS_TOKEN", "META_AD_ACCOUNT_MAP")
_SOCIAL_KEYS = ("METRICOOL_USER_TOKEN", "METRICOOL_BLOG_ID", "METRICOOL_USER_ID")


def _daycare_creds() -> dict[str, str]:
    try:
        return daycare_supabase._read_env()
    except Exception:  # noqa: BLE001 — never let config IO break a read
        return {}


@contextlib.contextmanager
def _scoped_env(keys: tuple[str, ...]):
    """Temporarily overlay the daycare's own creds onto os.environ for `keys`."""
    creds = _daycare_creds()
    saved = {k: os.environ.get(k) for k in keys}
    try:
        for k in keys:
            value = (creds.get(k) or "").strip()
            if value:
                os.environ[k] = value
            else:
                os.environ.pop(k, None)
        yield
    finally:
        for k, previous in saved.items():
            if previous is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = previous


def _int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _is_demo_account(acct: dict | None) -> bool:
    """True when this is one of agency_ads' built-in demo accounts.

    agency_ads ships mock accounts (Bloom Dental, Peak Fitness) for the AGENCY
    workspace. Its analytics() falls back to _ACCOUNTS[0] whenever it cannot resolve
    a real account for the caller — so an unmapped daycare lands on Bloom Dental.
    """
    if not isinstance(acct, dict):
        return False
    demo_ids = {a.get("id") for a in getattr(agency_ads, "_ACCOUNTS", [])}
    return (acct.get("id") in demo_ids
            or str(acct.get("clientId") or "").startswith("demo-"))


def ads_overview(account: str | None = None, days: int = 7) -> dict:
    """Meta ads connection + analytics for the daycare account (mock until keyed).

    EVIDENCE DISCIPLINE (daycare creed): a token alone is not enough. daycare.env can
    carry META_ACCESS_TOKEN while carrying no META_AD_ACCOUNT_MAP, in which case
    agency_ads reports source="live" and then serves the AGENCY's demo numbers
    (Bloom Dental: $3,370 spend / 117 leads). Those were rendering under a green LIVE
    badge on the daycare Growth tab AND being fed to Solomon under "TODAY'S LIVE
    CENTER DATA". A dentist's ad spend is not the daycare's. Refuse it and report the
    honest not-configured read instead — same guard dropship_director already applies.
    agency_ads itself is untouched; its mock still serves the agency workspace.
    """
    with _ENV_LOCK, _scoped_env(_ADS_KEYS):
        conn = agency_ads.connection()
        accounts = agency_ads.accounts().get("accounts", [])
        analytics = agency_ads.analytics(
            account=account, client="daycare", days=_int(days, 7))
        # analytics() is what discovers a rejected token — re-read so the FIRST call
        # after a restart reports auth_error instead of "add META_AD_ACCOUNT_MAP".
        conn = agency_ads.connection()

    if conn.get("source") == "auth_error":
        # WP-A — Meta REJECTED the token (agency_ads' 6h cache). Say so; the demo-account
        # guard below would otherwise misreport it as "add META_AD_ACCOUNT_MAP".
        return {"ok": True, "connection": conn, "accounts": [], "analytics": None,
                "configured": False, "detail": conn.get("todo")}
    if _is_demo_account((analytics or {}).get("account")) or any(
            _is_demo_account(a) for a in accounts):
        return {
            "ok": True,
            "connection": {**conn, "connected": False, "source": "not_configured",
                           "todo": "Add META_AD_ACCOUNT_MAP to daycare.env so the "
                                   "daycare's own Meta account resolves."},
            "accounts": [],
            "analytics": None,
            "configured": False,
            "detail": "Meta ad account not mapped for the daycare — add "
                      "META_AD_ACCOUNT_MAP to daycare.env. No numbers are shown "
                      "rather than another business's.",
        }
    return {"ok": True, "connection": conn, "accounts": accounts,
            "analytics": analytics, "configured": True}


def social_overview(network: str | None = None) -> dict:
    """Metricool social connection + analytics + scheduled posts (mock until keyed)."""
    if not (_daycare_creds().get("METRICOOL_USER_TOKEN") or "").strip():
        # agency_social falls back to the AGENCY's Metricool brand + mock numbers and
        # reports connected — that rendered as the daycare's LIVE social. Refuse it.
        return {"ok": True, "configured": False, "analytics": None, "posts": [], "bestTime": None,
                "connection": {"connected": False, "source": "not_configured",
                               "todo": "Add METRICOOL_USER_TOKEN + METRICOOL_BLOG_ID to daycare.env."}}
    with _ENV_LOCK, _scoped_env(_SOCIAL_KEYS):
        return {
            "ok": True,
            "connection": agency_social.connection(),
            "bestTime": agency_social.best_time(network),
            "analytics": agency_social.analytics(network),
            "posts": agency_social.list_posts(network),
        }


def eco_overview(account: str | None = None) -> dict:
    """Fast, read-only Eco strategy view for the daycare (no Claude, no persist).

    Renders instantly on the Growth tab; the heavy Claude idea generation is the
    explicit ``eco_ideas`` action behind a button. Always reports whether the
    business context brief loaded so the UI can nudge the owner if it's missing.
    """
    with _ENV_LOCK, _scoped_env(_ADS_KEYS):
        built = agency_eco.recommendations(account=account, client="daycare")
    return {
        **built,
        "context": daycare_context.status(),
    }


def eco_ideas(account: str | None = None) -> dict:
    """Explicit action — Claude drafts DAYCARE enrollment concepts + a local-daycare
    competitor read, grounded in the business brief (read FIRST).

    Uses a daycare-scoped generator (``agency_eco.daycare_enrollment_ideas``) that
    reasons purely from the brief until the daycare's OWN Meta account is connected —
    it never borrows the agency's demo ad data, so ideas stay on-industry. When the
    daycare's Meta is live, its real numbers are folded in.

    Read-only: proposals for the owner. Launching an ad stays approval-gated.
    """
    ctx = daycare_context.context_block()
    # Fold in the Enrollment Ad Agent spec: the real Meta account, live angles, ad
    # copy, image prompts, and the Higgsfield→Pipeboard workflow — so new ideas build
    # on the actual running assets, not generic ones.
    ctx += daycare_context.ad_agent_block()
    # Utilize the brain: fold Solomon's learned operating playbook (which owns
    # enrollment) into the enrollment engine so the brain's strategy shapes ideas.
    try:
        import daycare_director
        pb = daycare_director.playbook_text(2000)
        if pb:
            ctx += ("\n\n=== SOLOMON'S ENROLLMENT PLAYBOOK (learned from the brain — "
                    "apply his strategy) ===\n" + pb)
    except Exception:
        pass
    key, _src = agency_eco._agency_key()
    if not key:
        # No Claude key — return the fast template view so the tab still renders.
        built = eco_overview(account)
        built["ok"] = True
        built["detail"] = "Add ANTHROPIC_API_KEY (agency.env) to generate live ideas."
        return built

    analytics_block = ""
    live = None
    with _ENV_LOCK, _scoped_env(_ADS_KEYS):
        conn = agency_ads.connection()
        if conn.get("connected") or conn.get("source") == "live":
            live = agency_ads.analytics(client="daycare")
            # Creed: a present token is not live data — a failed fetch falls back to the
            # AGENCY's mock (Bloom Dental). Fold numbers in only when they are real.
            if live.get("dataSource") == "live" and not _is_demo_account(live.get("account")):
                analytics_block = agency_eco._format_analytics_block(live)

    try:
        built = agency_eco.daycare_enrollment_ideas(ctx, key, analytics_block)
        # Brief-only ideas carry no ad metrics: "none", or why the real numbers are missing.
        built["dataSource"] = ("live" if analytics_block else
                               "token_rejected" if conn.get("source") == "auth_error"
                               else "none")
        built["dateRange"] = live.get("dateRange") if analytics_block else None
    except Exception as exc:  # noqa: BLE001 — fall back to template, never 500
        built = eco_overview(account)
        built["detail"] = f"Idea generation fell back to template ({exc})."
    return {
        "ok": True,
        **built,
        "context": daycare_context.status(),
    }
