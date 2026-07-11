"""deal_stats.py — derive wholesaling deal stats from GoHighLevel opportunities.

Pure stdlib, no GHL coupling. The caller (connector.py) passes a pre-built list of
`_opp_view()` dicts, an optional pipelines list (for pipeline-name JV matching), the
JV keyword, and the current "YYYY-MM" month prefix. Every function here is pure and
deterministic — no datetime/clock calls happen inside `compute()`.

Opp shape (from `_opp_view()`):
    {id, name, value:float, status, pipelineId, stageId, stage, contactId,
     phone, tags:[], updated}
status ∈ open/won/lost/abandoned. updated = ISO string ("2026-06-01T12:00:00Z") or None.

Be defensive everywhere: missing keys, None values, value as str all coerce cleanly.
Never raise.
"""


def _num(x):
    """Coerce anything to a float, never raising. None/""/garbage -> 0.0."""
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _money(x):
    """Round a coerced number to 2 decimals."""
    return round(_num(x), 2)


def _s(x):
    """Coerce to a stripped lowercase string for matching; None -> ''."""
    return ("" if x is None else str(x)).strip().lower()


def _status(opp):
    """Lowercased opp status, defensive against missing/None."""
    return _s(opp.get("status"))


def _updated(opp):
    """The opp 'updated' value as a string ('' if None/missing) for sort keys + month."""
    u = opp.get("updated")
    return "" if u is None else str(u)


def _is_jv(opp, kw, pl_name_by_id):
    """True if this opp is a joint-venture deal.

    Case-insensitive match of `kw` OR the literal "joint venture" across:
      - the opp name
      - the opp stage
      - the mapped pipeline name (pl_name_by_id[opp.pipelineId])
      - any contact tag in opp["tags"]

    `kw` is already lowercased by the caller, but we lowercase defensively.
    Never raises.
    """
    kw = _s(kw)
    pl_name_by_id = pl_name_by_id or {}
    needles = [n for n in (kw, "joint venture") if n]
    if not needles:
        return False

    haystack_parts = [
        _s(opp.get("name")),
        _s(opp.get("stage")),
        _s(pl_name_by_id.get(opp.get("pipelineId"))),
    ]

    tags = opp.get("tags") or []
    if isinstance(tags, (list, tuple)):
        for t in tags:
            haystack_parts.append(_s(t))
    else:
        haystack_parts.append(_s(tags))

    haystack = " ".join(p for p in haystack_parts if p)
    return any(n in haystack for n in needles)


def _pl_name_by_id(pls):
    """Map pipelineId -> pipeline name from an optional pipelines list."""
    out = {}
    for p in (pls or []):
        if not isinstance(p, dict):
            continue
        pid = p.get("id")
        if pid is not None:
            out[pid] = p.get("name")
    return out


def compute(opps, pls=None, jv_keyword="jv", month_prefix=""):
    """Derive lifetime + month deal stats and the closed/fell-through/JV lists.

    See module docstring + the spec contract for the exact return shape. Pure and
    deterministic: pass `month_prefix` in (no clock calls here).
    """
    opps = opps or []
    kw = _s(jv_keyword)
    pl_name_by_id = _pl_name_by_id(pls)
    month_prefix = month_prefix or ""

    # --- lifetime accumulators ---
    deals_closed = 0
    total_earned = 0.0
    jv_deals = 0
    fell_through = 0
    open_value = 0.0

    # --- month accumulators ---
    m_deals_closed = 0
    m_earned = 0.0
    m_fell_through = 0

    closed_list = []
    fell_through_list = []
    jv_list = []

    for opp in opps:
        if not isinstance(opp, dict):
            continue
        st = _status(opp)
        val = _num(opp.get("value"))
        updated = _updated(opp)
        in_month = bool(month_prefix) and updated[:7] == month_prefix
        is_jv = _is_jv(opp, kw, pl_name_by_id)

        if st == "won":
            deals_closed += 1
            total_earned += val
            if is_jv:
                jv_deals += 1
            if in_month:
                m_deals_closed += 1
                m_earned += val

            closed_list.append({
                "id": opp.get("id"),
                "name": opp.get("name"),
                "value": _money(val),
                "stage": opp.get("stage"),
                "jv": is_jv,
                "updated": opp.get("updated"),
            })
            if is_jv:
                jv_list.append({
                    "id": opp.get("id"),
                    "name": opp.get("name"),
                    "value": _money(val),
                    "stage": opp.get("stage"),
                    "updated": opp.get("updated"),
                })

        elif st in ("lost", "abandoned"):
            fell_through += 1
            if in_month:
                m_fell_through += 1
            fell_through_list.append({
                "id": opp.get("id"),
                "name": opp.get("name"),
                "value": _money(val),
                "stage": opp.get("stage"),
                "status": st,
                "updated": opp.get("updated"),
            })

        elif st == "open":
            open_value += val

    # Sort every list by `updated` descending; None/"" sorts last.
    # "" naturally sorts before any real ISO string ascending, so we make the
    # key (has_value, value) and reverse — empty strings drop to the bottom.
    def _sort_key(row):
        u = row.get("updated")
        u = "" if u is None else str(u)
        return (u != "", u)

    closed_list.sort(key=_sort_key, reverse=True)
    fell_through_list.sort(key=_sort_key, reverse=True)
    jv_list.sort(key=_sort_key, reverse=True)

    avg_fee = (total_earned / deals_closed) if deals_closed else 0.0

    return {
        "lifetime": {
            "dealsClosed": deals_closed,
            "totalEarned": _money(total_earned),
            "avgFee": _money(avg_fee),
            "jvDeals": jv_deals,
            "fellThrough": fell_through,
        },
        "month": {
            "prefix": month_prefix,
            "dealsClosed": m_deals_closed,
            "earned": _money(m_earned),
            "fellThrough": m_fell_through,
        },
        "openValue": _money(open_value),
        "closedList": closed_list,
        "fellThroughList": fell_through_list,
        "jvList": jv_list,
    }


if __name__ == "__main__":
    import json

    pls = [
        {"id": "pl_1", "name": "Wholesale Pipeline", "stages": []},
        {"id": "pl_2", "name": "JV Pipeline", "stages": []},
    ]

    opps = [
        # Won, this month, JV via name keyword "JV".
        {"id": "o1", "name": "123 Main St (JV w/ Mike)", "value": 12000.0,
         "status": "won", "pipelineId": "pl_1", "stageId": "s_won",
         "stage": "Closed Won", "contactId": "c1", "phone": "215-555-0101",
         "tags": ["seller"], "updated": "2026-06-01T12:00:00Z"},

        # Won, this month, JV via contact tag "jv". value as str -> coerced.
        {"id": "o2", "name": "88 Oak Ave", "value": "8500",
         "status": "won", "pipelineId": "pl_1", "stageId": "s_won",
         "stage": "Closed Won", "contactId": "c2", "phone": "215-555-0102",
         "tags": ["hot", "JV"], "updated": "2026-06-05T09:30:00Z"},

        # Won, LAST month, not JV. Should count lifetime but NOT this month.
        {"id": "o3", "name": "42 Elm Rd", "value": 6000.0,
         "status": "won", "pipelineId": "pl_1", "stageId": "s_won",
         "stage": "Closed Won", "contactId": "c3", "phone": None,
         "tags": [], "updated": "2026-05-20T15:00:00Z"},

        # Lost, this month.
        {"id": "o4", "name": "7 Pine Ct", "value": 0,
         "status": "lost", "pipelineId": "pl_1", "stageId": "s_lost",
         "stage": "Dead", "contactId": "c4", "phone": "215-555-0104",
         "tags": ["cold"], "updated": "2026-06-03T11:00:00Z"},

        # Abandoned, last month, missing some keys / None value.
        {"id": "o5", "name": "9 Birch Ln", "value": None,
         "status": "abandoned", "stage": "Abandoned",
         "contactId": "c5", "tags": None, "updated": "2026-05-11T08:00:00Z"},

        # Open — contributes only to openValue.
        {"id": "o6", "name": "55 Cedar Way", "value": 15000.0,
         "status": "open", "pipelineId": "pl_2", "stageId": "s_open",
         "stage": "Negotiating", "contactId": "c6", "phone": "215-555-0106",
         "tags": ["warm"], "updated": "2026-06-07T10:00:00Z"},
    ]

    result = compute(opps, pls, jv_keyword="jv", month_prefix="2026-06")
    print(json.dumps(result, indent=2))

    # Smoke assertions proving JV + month logic work.
    assert result["lifetime"]["dealsClosed"] == 3, result["lifetime"]
    assert result["lifetime"]["totalEarned"] == 26500.0, result["lifetime"]
    assert result["lifetime"]["jvDeals"] == 2, result["lifetime"]  # o1 (name) + o2 (tag)
    assert result["lifetime"]["fellThrough"] == 2, result["lifetime"]
    assert result["month"]["dealsClosed"] == 2, result["month"]      # o1, o2 only
    assert result["month"]["earned"] == 20500.0, result["month"]
    assert result["month"]["fellThrough"] == 1, result["month"]      # o4 only
    assert result["openValue"] == 15000.0, result["openValue"]
    assert {r["id"] for r in result["jvList"]} == {"o1", "o2"}, result["jvList"]
    # newest-updated first: o2 (06-05) before o1 (06-01)
    assert [r["id"] for r in result["jvList"]] == ["o2", "o1"], result["jvList"]
    print("\nOK — all smoke assertions passed.")
