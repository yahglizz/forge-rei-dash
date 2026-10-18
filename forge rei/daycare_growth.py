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
_ADS_KEYS = ("META_ACCESS_TOKEN", "META_AD_ACCOUNT_MAP", "PIPEBOARD_API_TOKEN",
             "PIPEBOARD_AD_ACCOUNT_ID", "PIPEBOARD_MCP_URL")
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


def ads_overview(account: str | None = None, days: int = 7, preset: str | None = None,
                 since: str | None = None, until: str | None = None, compare: bool = False,
                 fresh: bool = False) -> dict:
    """Meta ads connection + analytics for the daycare account (mock until keyed).

    When the DAYCARE's own Pipeboard token is in daycare.env, this is the Meta-exact path
    (ads_report: account-timezone range resolver, paged reads, reconciliation, compare). Without
    it, the legacy agency_ads path below runs unchanged (and keeps its honesty guards).
    `account` is ignored on the Pipeboard path — the daycare route only ever reads the daycare's
    own ad account."""
    tok, url, acct = _pb_ctx()
    if tok:
        return _ads_overview_pb(acct, tok, url, days, preset, since, until, compare, fresh)
    return _ads_overview_legacy(account, days)


def _ads_overview_legacy(account: str | None = None, days: int = 7) -> dict:
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


# ── Meta-exact ads reads (Pipeboard, the daycare's own token) ──────────────────────────────────
# One machinery for the dashboard card (ads_report), the agents' evidence packet (ads_feed) and
# the Solomon -> Eco share. READ-ONLY: nothing here imports or calls a pipeboard_io write.
EVIDENCE = ("Meta-reported leads via Pipeboard (website pixel leads + on-Facebook form leads, Meta's "
            "'lead' action) — NOT enrollments. Totals are Meta's own account-level figures for the "
            "window; reach is de-duplicated by Meta and not additive across windows.")
FEED_RULES = ("Use ONLY these numbers for ad questions. Every figure you state names its window "
              "(label + dates + tz) and 'Meta via Pipeboard'. A section with unknown:true is Unknown — "
              "never 0, never guessed. Series lists only days with delivery; unlisted days had none. "
              "Autopilot pending items wait on the owner's tap.")
FEED_WINDOWS = ("last_7d", "last_30d", "last_90d", "maximum")
_FIELDS = ("results",)
_META_TTL = 3600
_acct_meta_cache: dict = {}


def _pb_ctx() -> tuple[str, str, str]:
    """(token, mcp_url, account) from the DAYCARE's env only — never the shell's/agency's token."""
    import json as _json
    c = _daycare_creds()
    tok = (c.get("PIPEBOARD_API_TOKEN") or "").strip()
    acct = (c.get("PIPEBOARD_AD_ACCOUNT_ID") or "").strip()
    if not acct:
        try:
            acct = str(_json.loads(c.get("META_AD_ACCOUNT_MAP") or "{}").get("daycare") or "")
        except (ValueError, AttributeError):
            acct = ""
    if not acct:
        import daycare_ads_studio
        acct = daycare_ads_studio.AD_ACCOUNT
    return tok, (c.get("PIPEBOARD_MCP_URL") or "").strip(), acct


def _acct_meta(acct: str) -> dict:
    """{tz, created} for the account (cached 1 h). Caller holds pb.creds. A failed read is not
    cached and returns tz None → the resolver falls back to FORGE_TZ_OFFSET and says so."""
    import time as _t
    import pipeboard_io as pb
    hit = _acct_meta_cache.get(acct)
    if hit and _t.time() - hit[0] < _META_TTL:
        return hit[1]
    try:
        d = pb.call("get_account_info", {"account_id": acct, "fields": "timezone_name,created_time"})
    except pb.PipeboardAuthError:
        raise
    except pb.PipeboardError as e:
        return {"tz": None, "created": None, "error": str(e)[:160]}
    meta = {"tz": d.get("timezone_name") or None, "created": (d.get("created_time") or "")[:10] or None}
    _acct_meta_cache[acct] = (_t.time(), meta)
    return meta


def _fetched_at(tz: str | None) -> str:
    import datetime as _dt
    try:
        from zoneinfo import ZoneInfo
        return _dt.datetime.now(ZoneInfo(tz)).isoformat(timespec="seconds") if tz else ""
    except Exception:  # noqa: BLE001
        pass
    try:
        off = float(os.environ.get("FORGE_TZ_OFFSET") or -4)
    except ValueError:
        off = -4.0
    return _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=off))).isoformat(timespec="seconds")


def _counts(r: dict) -> dict:
    import pipeboard_io as pb
    return {"spend": pb._num(r.get("spend")), "impressions": int(pb._num(r.get("impressions"))),
            "reach": int(pb._num(r.get("reach"))), "clicks": int(pb._num(r.get("clicks"))),
            "leads": pb.lead_count(r)}


def _derive(c: dict, tcpl: float | None = None) -> dict:
    spend, imp, clk, leads = round(c["spend"], 2), c["impressions"], c["clicks"], c["leads"]
    out = {"spend": spend, "impressions": imp, "reach": c.get("reach", 0), "clicks": clk, "leads": leads,
           "ctr": round(clk / imp * 100, 2) if imp else None,
           "cpc": round(spend / clk, 2) if clk else None,
           "cpl": round(spend / leads, 2) if leads else None}
    if tcpl:
        out["tcpl"] = tcpl
        out["cplVsTarget"] = round(out["cpl"] / tcpl, 2) if out["cpl"] else None
    return out


def _zero() -> dict:
    return {"spend": 0.0, "impressions": 0, "reach": 0, "clicks": 0, "leads": 0}


def _jobs(acct: str, key: str, rng: dict, fresh: bool, series: bool, compare: bool) -> dict:
    import ads_range
    import pipeboard_io as pb
    s, u = rng["since"], rng["until"]
    j = {f"{key}|acct": (pb.insights_paged, (acct, s, u, "account", _FIELDS, fresh)),
         f"{key}|ads": (pb.insights_paged, (acct, s, u, "ad", _FIELDS, fresh))}
    if series:
        gran = "day" if rng["days"] <= 90 else "month"
        j[f"{key}|series"] = (pb.daily_account_rows, (acct, s, u, gran, fresh))
    if compare:
        p = ads_range.previous(rng)
        j[f"{key}|prev"] = (pb.insights_paged, (acct, p["since"], p["until"], "account", _FIELDS, fresh))
    return j


def _run_jobs(jobs: dict, tok: str, url: str) -> dict:
    """Run Pipeboard reads in parallel. pb.creds is thread-local, so each worker sets it."""
    from concurrent.futures import ThreadPoolExecutor
    import pipeboard_io as pb

    def one(item):
        k, (fn, args) = item
        with pb.creds(tok, url):
            try:
                return k, fn(*args), None
            except pb.PipeboardError as e:
                return k, None, e
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(jobs)))) as ex:
        return {k: (v, e) for k, v, e in ex.map(one, jobs.items())}


def _series(rng: dict, rows: list) -> dict:
    """Zero-filled per-day (≤90 days) or per-month series; Meta omits periods with no delivery."""
    import datetime as _dt
    gran = "day" if rng["days"] <= 90 else "month"
    by = {}
    for r in rows or []:
        k = str(r.get("day") or "")[:10 if gran == "day" else 7]
        c = _counts(r)
        b = by.setdefault(k, _zero())
        for f in ("spend", "impressions", "clicks", "leads"):
            b[f] += c[f]
    s, u = _dt.date.fromisoformat(rng["since"]), _dt.date.fromisoformat(rng["until"])
    keys, d = [], s
    while d <= u:
        k = d.isoformat() if gran == "day" else d.isoformat()[:7]
        if not keys or keys[-1] != k:
            keys.append(k)
        d += _dt.timedelta(days=1)
    pts = [{"d": k, "spend": round(by.get(k, _zero())["spend"], 2), "leads": by.get(k, _zero())["leads"],
            "clicks": by.get(k, _zero())["clicks"]} for k in keys]
    return {"granularity": gran, "points": pts}


def _assemble(rng: dict, res: dict, key: str, statuses: dict, tcpl: float, detail: bool) -> dict:
    """One window from fetched rows. Raises the window's PipeboardError if its core reads failed."""
    import pipeboard_io as pb
    (arows, aerr), (drows, derr) = res[f"{key}|acct"], res[f"{key}|ads"]
    if aerr and derr:
        raise aerr
    ad_rows, truncated = drows if drows else ([], None)
    acct_row = (arows[0][0] if arows and arows[0] else None) if arows else None
    sums, camps, ads, res_leads, any_res, checked = _zero(), {}, [], 0, False, 0
    for r in ad_rows:
        c = _counts(r)
        rl = pb.result_leads(r)
        if rl is not None:                     # only rows where Meta states a lead Result
            res_leads += rl
            checked += c["leads"]
            any_res = True
        for f in sums:
            sums[f] += c[f]
        cid = str(r.get("campaign_id") or "unknown")
        k = camps.setdefault(cid, {"id": cid, "name": r.get("campaign_name") or "Unknown", **_zero(),
                                   "results": 0})
        for f in ("spend", "impressions", "clicks", "leads"):
            k[f] += c[f]
        k["results"] += rl or 0
        ads.append({"id": str(r.get("ad_id") or ""), "name": r.get("ad_name") or "(ad)",
                    "campaign": r.get("campaign_name") or "", "campaignId": cid, **c})
    # Totals = Meta's account-level row (authoritative; reach is de-duplicated there). Fall back to
    # summed ad rows only when the account read failed — and then reconciliation is Unknown.
    if aerr is None:
        tot = _counts(acct_row) if acct_row else _zero()
        r2 = lambda v: round(v, 2)  # noqa: E731
        reconciled = None if derr else {
            "spend": abs(r2(tot["spend"]) - r2(sums["spend"])) < 0.015,
            "impressions": tot["impressions"] == sums["impressions"],
            "clicks": tot["clicks"] == sums["clicks"],
            "leads": tot["leads"] == sums["leads"],
            "leadsMatchMetaResults": (checked == res_leads) if any_res else None,
            "leadsWithoutMetaResult": sums["leads"] - checked}
    else:
        tot = dict(sums, reach=None)
        reconciled = None
    for cid, st in (statuses or {}).items():                  # campaigns with no delivery still exist
        camps.setdefault(cid, {"id": cid, "name": st.get("name") or cid, **_zero(), "results": 0})
    camp_out = []
    for k in camps.values():
        st = (statuses or {}).get(k["id"]) or {}
        camp_out.append({"id": k["id"], "name": k["name"], "status": (st.get("status") or "unknown").lower(),
                         "objective": st.get("objective") or "", "results": k["results"],
                         **_derive({**k, "reach": 0})})
    camp_out.sort(key=lambda x: (-x["spend"], x["name"]))
    ads_out = [dict(a, **_derive(a)) for a in ads]
    spent = [a for a in ads_out if a["spend"] > 0]
    rank = lambda a: (a["leads"], a["ctr"] or 0)  # noqa: E731
    out = {"dateRange": rng, "totals": _derive(tot if tot.get("reach") is not None else dict(tot, reach=0), tcpl),
           "campaigns": camp_out, "topAds": sorted(spent, key=rank, reverse=True)[:3],
           "weakAds": sorted(spent, key=rank)[:3], "reconciled": reconciled,
           "truncated": truncated, "partial": bool(aerr or derr)}
    if aerr is not None:
        out["totals"]["reach"] = None
    if (aerr or derr):
        out["partialError"] = str(aerr or derr)[:160]
    if detail:
        out["ads"] = ads_out
    if f"{key}|series" in res:
        rows, err = res[f"{key}|series"]
        out["series"] = {"unknown": True, "error": str(err)[:160]} if err else _series(rng, rows)
    if f"{key}|prev" in res:
        import ads_range
        rows, err = res[f"{key}|prev"]
        prng = ads_range.previous(rng)
        if err:
            out["compare"] = {"unknown": True, "error": str(err)[:160], "dateRange": prng}
        else:
            prow = rows[0][0] if rows and rows[0] else None
            ptot = _derive(_counts(prow) if prow else _zero())
            out["compare"] = {"dateRange": prng, "totals": ptot, "delta": {
                f: ads_range.delta_pct(out["totals"].get(f), ptot.get(f))
                for f in ("spend", "leads", "cpl", "clicks", "impressions", "ctr", "cpc")}}
    return out


def _statuses(res: dict) -> dict:
    rows, err = res.get("statuses", (None, None))
    return {str(c.get("id")): c for c in rows or []} if not err else {}


def _resolve(meta: dict, preset, since, until, days):
    import ads_range
    return ads_range.resolve(preset, since, until, tz_name=meta.get("tz"), earliest=meta.get("created"),
                             days=days if not (preset or since or until) else None)


def _tcpl() -> float | None:
    try:
        import daycare_ads_autopilot
        return daycare_ads_autopilot.cfg()["tcpl"]
    except Exception:  # noqa: BLE001
        return None


def ads_report(preset=None, since=None, until=None, days=None, compare=False, fresh=False,
               _ctx=None) -> dict:
    """One window, Meta-exact, in the analytics shape the Ads UI reads (+ series, compare,
    reconciliation, evidence). Raises ValueError (bad range) or pipeboard_io.PipeboardError."""
    import pipeboard_io as pb
    tok, url, acct = _ctx or _pb_ctx()
    with pb.creds(tok, url):
        meta = _acct_meta(acct)
    rng = _resolve(meta, preset, since, until, days)
    jobs = _jobs(acct, "w", rng, fresh, series=True, compare=bool(compare))
    jobs["statuses"] = (pb.campaigns, (acct, 200, fresh))
    res = _run_jobs(jobs, tok, url)
    for _k, (_v, e) in res.items():
        if isinstance(e, pb.PipeboardAuthError):
            raise e
    w = _assemble(rng, res, "w", _statuses(res), _tcpl(), detail=True)
    return {"account": {"id": acct, "name": acct, "clientName": "daycare"}, "accountId": acct,
            "days": rng["days"], **w, "source": "live", "dataSource": "live", "via": "pipeboard",
            "fetchedAt": _fetched_at(meta.get("tz")), "evidence": EVIDENCE, "fresh": bool(fresh),
            "accountTz": meta.get("tz"), "tzFallback": rng.get("tzFallback")}


def _ads_overview_pb(acct, tok, url, days, preset, since, until, compare, fresh) -> dict:
    import pipeboard_io as pb
    conn = {"connected": True, "hasToken": True, "source": "live", "via": "pipeboard", "todo": None}
    accounts = [{"id": acct, "name": "daycare — Meta (Pipeboard)", "clientId": "daycare",
                 "clientName": "daycare"}]
    auth = {"connected": False, "hasToken": True, "source": "auth_error", "via": "pipeboard",
            "todo": "PIPEBOARD_API_TOKEN was rejected (or its Meta login expired) — re-paste it in "
                    "daycare.env / reconnect at pipeboard.co/connections (retried every 15 min)."}
    if pb.auth_dead():
        return {"ok": True, "connection": auth, "accounts": [], "analytics": None,
                "configured": False, "detail": auth["todo"]}
    try:
        a = ads_report(preset, since, until, days if days not in (None, "") else 7, compare, fresh,
                       _ctx=(tok, url, acct))
    except ValueError as e:
        return {"ok": False, "error": f"bad date range: {e}", "code": "bad_range", "connection": conn}
    except pb.PipeboardAuthError:
        return {"ok": True, "connection": auth, "accounts": [], "analytics": None,
                "configured": False, "detail": auth["todo"]}
    except pb.PipeboardError as e:
        msg = f"Pipeboard read failed: {str(e)[:160]} — ad numbers are Unknown, not zero."
        return {"ok": True, "configured": True, "accounts": accounts,
                "connection": {**conn, "connected": False, "source": "read_failed", "todo": msg},
                "analytics": {"unknown": True, "error": msg, "dataSource": "unknown", "via": "pipeboard",
                              "accountId": acct}}
    return {"ok": True, "connection": conn, "accounts": accounts, "analytics": a, "configured": True}


def _compact_window(w: dict, selected: bool) -> dict:
    """Agent-sized: no raw rows, no per-ad dumps beyond top/weak, nulls kept (null = Unknown)."""
    r = w["dateRange"]
    keep_t = ("spend", "impressions", "reach", "clicks", "ctr", "cpc", "leads", "cpl", "tcpl", "cplVsTarget")
    out = {"window": f"{r['label']} {r['since']}..{r['until']}", "preset": r["preset"],
           "partialToday": r["partialToday"], "totals": {k: w["totals"].get(k) for k in keep_t},
           "campaigns": [{k: c.get(k) for k in ("id", "name", "status", "spend", "leads", "cpl")}
                         for c in w["campaigns"]][:12],
           "reconciled": w.get("reconciled"), "truncated": w.get("truncated")}
    if w.get("partial"):
        out["partial"] = w.get("partialError") or True
    if selected or w["totals"].get("spend"):
        out["topAds"] = [{k: a.get(k) for k in ("name", "campaign", "spend", "leads", "cpl", "ctr")}
                         for a in w.get("topAds") or []]
        out["weakAds"] = [{k: a.get(k) for k in ("name", "campaign", "spend", "leads", "cpl", "ctr")}
                          for a in w.get("weakAds") or []]
    s = w.get("series")
    if s:
        out["series"] = s if s.get("unknown") else {
            "granularity": s["granularity"], "cols": ["period", "spend", "leads", "clicks"],
            "rows": [[p["d"], p["spend"], p["leads"], p["clicks"]] for p in s["points"]
                     if p["spend"] or p["leads"] or p["clicks"]]}
    if w.get("compare"):
        cp = w["compare"]
        out["compare"] = cp if cp.get("unknown") else {
            "window": f"{cp['dateRange']['since']}..{cp['dateRange']['until']}",
            "totals": {k: cp["totals"].get(k) for k in ("spend", "leads", "cpl", "clicks")},
            "deltaPct": {k: cp["delta"].get(k) for k in ("spend", "leads", "cpl", "clicks")}}
    return out


def _autopilot_block() -> dict:
    """The optimizer's own state (local state file + env config) — never a Meta call."""
    try:
        import daycare_ads_autopilot as ap
        st = ap.status()
    except Exception as e:  # noqa: BLE001
        return {"unknown": True, "error": type(e).__name__}
    c, lr = st.get("config") or {}, st.get("lastRun") or None
    mode = st.get("mode")
    nxt = None
    if mode != "off":
        nxt = ("due now — next loop tick (≤15 min, box only)" if st.get("dueNow") else
               f"daily, first loop tick after {c.get('hour')}:00 local (box only)")
    return {"mode": mode, "tcpl": c.get("tcpl"), "maxDaily": c.get("maxDaily"), "hour": c.get("hour"),
            "dueNow": st.get("dueNow"), "nextRun": nxt, "lastRunDay": st.get("lastRunDay"),
            "lastRun": ({k: lr.get(k) for k in ("day", "ts", "mode", "judge", "totalBudget", "counts")}
                        | {"note": str(lr.get("note") or "")[:400]}) if lr else None,
            "lastError": st.get("lastError"),
            "pending": [{"id": a.get("aid"), "action": ap._fmt_action(a), "reason": str(a.get("reason") or "")[:200]}
                        for a in (st.get("pending") or [])[:8]],
            "recent": [{"action": ap._fmt_action(a), "status": a.get("status"), "ts": a.get("ts"),
                        "why": str(a.get("why") or a.get("reason") or "")[:140]}
                       for a in (st.get("recent") or [])[:5]],
            "held": st.get("held") or []}


def ads_feed(preset=None, since=None, until=None, compare=False, fresh=True,
             windows=FEED_WINDOWS) -> dict:
    """THE agent evidence packet: Meta via Pipeboard, pulled FRESH (no 60 s cache) on every call.
    Always carries 7d / 30d / 90d / maximum so history is never invisible, plus the selected window
    (default last_30d) with a day series (+ previous period when compare). A failed read is an
    explicit {unknown:true, error} section — never zeros. Read-only; never raises."""
    import pipeboard_io as pb
    tok, url, acct = _pb_ctx()
    base = {"ok": True, "kind": "daycare_ads_feed", "source": "Meta via Pipeboard (read-only)",
            "accountId": acct, "evidence": EVIDENCE, "rules": FEED_RULES, "autopilot": _autopilot_block()}
    if not tok:
        return {**base, "configured": False, "unknown": True,
                "error": "PIPEBOARD_API_TOKEN not set in daycare.env — ad numbers are Unknown"}
    if pb.auth_dead():
        return {**base, "configured": True, "unknown": True, "authError": True,
                "error": "Pipeboard rejected the daycare token (or its Meta login expired) — ad numbers Unknown"}
    try:
        with pb.creds(tok, url):
            meta = _acct_meta(acct)
        sel = _resolve(meta, preset or (None if (since or until) else "last_30d"), since, until, None)
        rngs = {}
        for p in windows:
            r = _resolve(meta, p, None, None, None)
            rngs[p] = r
        jobs = {}
        sel_key = next((p for p, r in rngs.items() if (r["since"], r["until"]) == (sel["since"], sel["until"])), "selected")
        for p, r in rngs.items():
            jobs.update(_jobs(acct, p, r, fresh, series=(p == sel_key), compare=(p == sel_key and compare)))
        if sel_key == "selected":
            jobs.update(_jobs(acct, "selected", sel, fresh, series=True, compare=bool(compare)))
        jobs["statuses"] = (pb.campaigns, (acct, 200, fresh))
        res = _run_jobs(jobs, tok, url)
    except ValueError as e:
        return {**base, "configured": True, "unknown": True, "error": f"bad date range: {e}"}
    except pb.PipeboardAuthError as e:
        return {**base, "configured": True, "unknown": True, "authError": True, "error": str(e)[:160]}
    except pb.PipeboardError as e:
        return {**base, "configured": True, "unknown": True, "error": str(e)[:160]}
    if any(isinstance(e, pb.PipeboardAuthError) for _v, e in res.values()):
        return {**base, "configured": True, "unknown": True, "authError": True,
                "error": "Pipeboard rejected the daycare token — ad numbers Unknown"}
    statuses, tcpl = _statuses(res), _tcpl()

    def one(key, r, selected):
        try:
            return _compact_window(_assemble(r, res, key, statuses, tcpl, detail=False), selected)
        except pb.PipeboardError as e:
            return {"window": f"{r['label']} {r['since']}..{r['until']}", "preset": r["preset"],
                    "unknown": True, "error": str(e)[:160]}
    wins = [one(p, r, p == sel_key) for p, r in rngs.items()]
    # the selected window is one of the standard ones (no duplicate pull) or its own custom pull
    selected = one("selected", sel, True) if sel_key == "selected" else {"sameAs": sel_key}
    return {**base, "configured": True, "fetchedAt": _fetched_at(meta.get("tz")),
            "tz": sel.get("tz"), "tzFallback": sel.get("tzFallback"), "fresh": bool(fresh),
            "selected": selected, "windows": wins,
            "unknown": all(w.get("unknown") for w in wins)}


def ads_feed_block(feed: dict | None = None, **kw) -> str:
    """Prompt text for an agent: rules + the compact packet. Never raises."""
    import json as _json
    try:
        feed = feed if feed is not None else ads_feed(**kw)
        body = _json.dumps(feed, separators=(",", ":"), default=str)
    except Exception as e:  # noqa: BLE001
        body = _json.dumps({"unknown": True, "error": f"ad packet failed: {type(e).__name__}"})
    return ("\n\n=== LIVE AD PACKET (Meta via Pipeboard, pulled fresh for THIS answer — the ONLY "
            "source of ad numbers; the daycare creed applies) ===\n" + FEED_RULES + "\n" + body[:9000])


_SHARE_FILE = None


def share_ad_results(days: int = 30) -> dict:
    """Solomon -> Eco: broadcast the daycare's REAL ad results as one coaching insight, so the
    agency's ad agent learns what converts for enrollment (and Solomon's tips flow both ways).

    Zero Claude, read-only on Meta, internal + reversible (coaching moves TEXT only — CLAUDE.md §11).
    Evidence discipline: figures carry source + window; one account is a hypothesis, not a law.
    Sent at most once per distinct (window, totals) so a polling loop never spams the feed."""
    import json
    from pathlib import Path
    import agent_coach
    path = _SHARE_FILE or Path(__file__).resolve().parent / "marcus_state" / "ad_share.json"
    try:
        # Fresh, Meta-exact (same reads as the agents' packet) when the daycare's Pipeboard is keyed.
        out = ads_overview(days=days, fresh=True)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "skipped": f"ads read failed: {type(e).__name__}"}
    a = out.get("analytics") or {}
    t = a.get("totals") or {}
    if not out.get("configured") or a.get("dataSource") != "live" or not (t.get("spend") or 0) > 0:
        return {"ok": True, "skipped": "no live spend to report"}
    rng = a.get("dateRange") or {}
    ads = [x for x in (a.get("topAds") or []) + (a.get("weakAds") or []) if x.get("spend")]
    best = max(ads, key=lambda x: (x.get("leads", 0), x.get("ctr", 0)), default=None)
    worst = min(ads, key=lambda x: (x.get("leads", 0), x.get("ctr", 0)), default=None)
    text = (f"Daycare enrollment ads (Meta via Pipeboard, {rng.get('since')}→{rng.get('until')}): "
            f"${t.get('spend'):.2f} spend → {t.get('leads', 0)} leads"
            + (f" (CPL ${t.get('cpl'):.2f})" if t.get("leads") else "")
            + (f", CTR {t.get('ctr')}%" if t.get("ctr") is not None else ", CTR Unknown")
            + f", {t.get('clicks')} clicks.")
    if best and best is not worst:
        text += (f" Best ad: \"{str(best.get('name'))[:60]}\" ({best.get('leads', 0)} leads on "
                 f"${best.get('spend'):.2f}); weakest: \"{str(worst.get('name'))[:60]}\" "
                 f"({worst.get('leads', 0)} leads on ${worst.get('spend'):.2f}).")
    text += " One account, small sample — treat as a hypothesis to test, not a rule."
    key = f"{rng.get('since')}|{rng.get('until')}|{t.get('spend')}|{t.get('leads')}"
    try:
        last = json.loads(path.read_text()).get("key") if path.exists() else None
    except Exception:  # noqa: BLE001
        last = None
    if last == key:
        return {"ok": True, "skipped": "already shared"}
    res = agent_coach.broadcast("solomon", text, to="eco",
                                tags=["daycare", "meta-ads", "results"])
    if res.get("ok"):
        import forge_atomic
        forge_atomic.atomic_write_json(path, {"key": key, "at": int(__import__("time").time() * 1000)})
    return {"ok": bool(res.get("ok")), "shared": text if res.get("ok") else None,
            "error": res.get("error")}


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
    if _is_demo_account(built.get("account")):
        # Same creed guard as ads_overview: unmapped/unkeyed -> agency_eco serves the AGENCY's
        # Bloom Dental concepts (dentistry copy, ROAS 10.26). Never present that as the daycare's.
        return {"ok": True, "configured": False, "dataSource": "none", "next": [], "best": [],
                "weak": [], "account": None,
                "detail": "Daycare Meta account not connected — no strategy built from "
                          "another business's numbers.",
                "context": daycare_context.status()}
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
    conn = {}
    if _pb_ctx()[0]:
        # The daycare's own Pipeboard: the same fresh agent packet Solomon reads (7/30/90/max +
        # autopilot), never the 7-day cached call. Unknown windows say so inside the packet.
        feed = ads_feed()
        if not feed.get("unknown"):
            analytics_block = ads_feed_block(feed)
            live = {"dateRange": {"windows": [w.get("window") for w in feed.get("windows") or []],
                                  "tz": feed.get("tz"), "fetchedAt": feed.get("fetchedAt")}}
        elif feed.get("authError"):
            conn = {"source": "auth_error"}
    else:
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
