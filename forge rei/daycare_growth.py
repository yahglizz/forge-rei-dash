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


def ads_overview(account: str | None = None, days: int = 7) -> dict:
    """Meta ads connection + analytics for the daycare account (mock until keyed)."""
    with _ENV_LOCK, _scoped_env(_ADS_KEYS):
        return {
            "ok": True,
            "connection": agency_ads.connection(),
            "accounts": agency_ads.accounts().get("accounts", []),
            "analytics": agency_ads.analytics(
                account=account, client="daycare", days=_int(days, 7)),
        }


def social_overview(network: str | None = None) -> dict:
    """Metricool social connection + analytics + scheduled posts (mock until keyed)."""
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
    """Explicit action — Claude generates enrollment ideas + competitor analysis,
    grounded in the daycare context brief (read FIRST) and any live ad numbers.

    Read-only: it produces proposals for the owner. Launching an ad stays a
    separate approval-gated step (never autonomous).
    """
    ctx = daycare_context.context_block()
    with _ENV_LOCK, _scoped_env(_ADS_KEYS):
        built = agency_eco._build(
            account=account, client="daycare", use_ai=True,
            include_competitor_ai=True, extra_context=ctx)
    return {
        "ok": True,
        **built,
        "context": daycare_context.status(),
    }
