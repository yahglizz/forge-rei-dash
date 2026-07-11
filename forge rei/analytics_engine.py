"""analytics_engine.py — deterministic message analytics for FORGE REI OS.

No LLM. Aggregates GoHighLevel conversations + sampled threads + Marcus logs +
pipeline into a metrics bundle the Analytics tab and the weekly review agent consume.

Called by the connector: build(ghl_get, opp_view, location_id, days=30).
Reuses Marcus's classifier so "what sellers say" matches Marcus's own buckets.
"""

import json
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROPOSALS_LOG = HERE / "marcus_state" / "proposals.jsonl"

try:
    from marcus_engine import classify
except Exception:  # pragma: no cover
    def classify(_b):
        return "CONTINUE"


def _to_ms(v):
    """Accept epoch-ms ints or ISO strings; return epoch ms or None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    try:
        s = str(v).replace("Z", "+00:00")
        return int(datetime.fromisoformat(s).timestamp() * 1000)
    except Exception:
        return None


def _pull_conversations(ghl_get, location_id, pages=5, per=100):
    out, start_after, start_after_id = [], None, None
    for _ in range(pages):
        params = {"locationId": location_id, "limit": per, "sortBy": "last_message_date"}
        if start_after:
            params["startAfter"] = start_after
            params["startAfterId"] = start_after_id
        data = ghl_get("/conversations/search", params)
        batch = data.get("conversations", []) or []
        out.extend(batch)
        if len(batch) < per:
            break
        last = batch[-1]
        start_after = last.get("sort", [None])[0] if isinstance(last.get("sort"), list) else last.get("lastMessageDate")
        start_after_id = last.get("id")
        if not start_after:
            break
    return out


def _sample_latency(ghl_get, convos, sample=40):
    """Pull a sample of threads; measure median seller->reply latency + turn counts."""
    picked = convos[:sample]

    def one(c):
        try:
            cid = c.get("id")
            data = ghl_get(f"/conversations/{cid}/messages", {"limit": 50})
            raw = data.get("messages", data)
            if isinstance(raw, dict):
                raw = raw.get("messages", [])
            msgs = []
            for m in (raw or []):
                msgs.append((m.get("direction"), _to_ms(m.get("dateAdded"))))
            msgs = [m for m in msgs if m[1]]
            msgs.sort(key=lambda x: x[1])  # oldest first
            latencies = []
            for i, (d, t) in enumerate(msgs):
                if d == "inbound":
                    for d2, t2 in msgs[i + 1:]:
                        if d2 == "outbound":
                            latencies.append((t2 - t) / 1000.0)
                            break
            return {"turns": len(msgs), "latencies": latencies}
        except Exception:
            return {"turns": 0, "latencies": []}

    with ThreadPoolExecutor(max_workers=3) as ex:
        results = list(ex.map(one, picked))
    all_lat = [x for r in results for x in r["latencies"] if x >= 0]
    turns = [r["turns"] for r in results if r["turns"]]
    all_lat.sort()
    median = all_lat[len(all_lat) // 2] if all_lat else None
    return {
        "sampled": len(picked),
        "medianReplySeconds": median,
        "avgTurns": round(sum(turns) / len(turns), 1) if turns else 0,
        "repliedSamples": sum(1 for r in results if r["latencies"]),
    }


def _marcus_stats():
    if not PROPOSALS_LOG.exists():
        return {"proposed": 0, "sent": 0, "dismissed": 0, "suppressed": 0, "byClass": {}}
    latest = {}
    suppressed = 0
    for line in PROPOSALS_LOG.read_text().splitlines():
        if not line.strip():
            continue
        try:
            p = json.loads(line)
        except Exception:
            continue
        latest[p.get("id")] = p
    by_status = defaultdict(int)
    by_class = defaultdict(int)
    for p in latest.values():
        by_status[p.get("status", "pending")] += 1
        by_class[p.get("classification", "?")] += 1
    return {
        "proposed": len(latest),
        "sent": by_status.get("sent", 0),
        "dismissed": by_status.get("dismissed", 0),
        "pending": by_status.get("pending", 0),
        "byClass": dict(by_class),
    }


def build(ghl_get, opp_view, location_id, days=30, pages=4, sample=25):
    now = int(time.time() * 1000)
    window = days * 86400 * 1000
    convos = _pull_conversations(ghl_get, location_id, pages=pages)

    in_window = [c for c in convos if (_to_ms(c.get("lastMessageDate")) or 0) >= now - window]
    scope = in_window or convos

    inbound_last = [c for c in scope if c.get("lastMessageDirection") == "inbound"]
    outbound_last = [c for c in scope if c.get("lastMessageDirection") == "outbound"]
    unanswered = [c for c in inbound_last if (c.get("unreadCount") or 0) > 0]

    # Classification of what sellers said (inbound-last bodies).
    cls = defaultdict(int)
    for c in inbound_last:
        cls[classify(c.get("lastMessageBody") or "")] += 1

    # Channel mix.
    channel = defaultdict(int)
    for c in scope:
        t = (c.get("lastMessageType") or "UNKNOWN").replace("TYPE_", "")
        channel[t] += 1

    # Per-market via tags.
    market = defaultdict(int)
    for c in scope:
        for t in (c.get("tags") or []):
            tl = t.lower()
            if any(k in tl for k in ("market-", "ohio", "pa ", "read", "chest", "delaware", "wilm", "toledo", "419", "267")):
                market[t] += 1

    # Timing — inbound by hour + weekday.
    by_hour = defaultdict(int)
    by_dow = defaultdict(int)
    for c in inbound_last:
        ms = _to_ms(c.get("lastMessageDate"))
        if not ms:
            continue
        dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        by_hour[dt.hour] += 1
        by_dow[dt.strftime("%a")] += 1

    latency = _sample_latency(ghl_get, scope, sample=sample)
    marcus = _marcus_stats()

    # Conversion from pipeline.
    try:
        _pls, opps = opp_view()
        open_opps = [o for o in opps if o.get("status") == "open"]
        conversion = {
            "openOpportunities": len(open_opps),
            "pipelineValue": sum(o.get("value", 0) for o in open_opps),
            "totalOpportunities": len(opps),
        }
    except Exception:
        conversion = {"openOpportunities": 0, "pipelineValue": 0, "totalOpportunities": 0}

    total = len(scope)
    awaiting = len(inbound_last)
    response_rate = round(100 * (1 - (awaiting / total)), 1) if total else 0

    return {
        "generatedAt": now,
        "days": days,
        "scope": total,
        "volume": {
            "conversations": total,
            "inboundLast": awaiting,
            "outboundLast": len(outbound_last),
            "unanswered": len(unanswered),
        },
        "responseRate": response_rate,
        "hotSignals": cls.get("READY", 0) + cls.get("PRICE", 0),
        "classification": dict(cls),
        "channels": dict(channel),
        "markets": dict(sorted(market.items(), key=lambda kv: -kv[1])[:12]),
        "timing": {"byHour": dict(by_hour), "byDow": dict(by_dow)},
        "latency": latency,
        "marcus": marcus,
        "conversion": conversion,
    }
