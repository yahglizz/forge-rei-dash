"""marcus_chat.py — the live Marcus chat brain for FORGE REI OS.

The dashboard chat used to call a browser-side Claude SDK that doesn't exist in
the static app, so every message fell back to "my brain isn't connected yet."

This routes the chat through the connector instead: it SEARCHES the operator's
real GoHighLevel SMS threads, finds the ones relevant to the question (e.g.
"the seller who was asking 85k yesterday"), and hands those transcripts —
with the seller's NAME attached — to Claude so Marcus can actually answer.

Graceful: no ANTHROPIC_API_KEY -> {"needsKey": True}; the UI shows a hint.
Reuses review_agent's Claude plumbing + analytics_engine's conversation puller.
"""
import re
import time
from concurrent.futures import ThreadPoolExecutor

import agent_collab
import review_agent
import caveman
from analytics_engine import _pull_conversations, _to_ms

_STOP = {
    "the", "and", "for", "was", "with", "you", "your", "have", "had", "his",
    "her", "him", "she", "they", "them", "that", "this", "what", "who", "when",
    "where", "find", "me", "tell", "name", "seller", "home", "house", "asking",
    "ask", "messages", "message", "msg", "can", "could", "would", "yesterday",
    "today", "from", "about", "give", "show", "get", "got", "are", "were",
    "his", "their", "our", "i", "a", "an", "of", "to", "in", "on", "is", "it",
}


def _name_of(c):
    return (c.get("fullName") or c.get("contactName") or c.get("name")
            or (c.get("contact") or {}).get("name") or "Unknown seller")


def _keywords(question):
    """Salient tokens to score threads by. Numbers (and their k-suffix money
    forms) are the strongest signal in 'asking 85k' style questions."""
    q = question.lower()
    words = re.findall(r"[a-z0-9$]+", q)
    kws = set()
    for w in words:
        if w in _STOP or len(w) < 3:
            continue
        kws.add(w)
        m = re.match(r"\$?(\d+)k?$", w)
        if m:
            n = m.group(1)
            kws.add(n)          # 85
            kws.add(n + "k")    # 85k
            kws.add("$" + n)    # $85
    return kws


def _fetch_thread(ghl_get, conv, max_msgs=16):
    cid = conv.get("id")
    try:
        data = ghl_get(f"/conversations/{cid}/messages", {"limit": 40})
        raw = data.get("messages", data)
        if isinstance(raw, dict):
            raw = raw.get("messages", [])
        msgs = []
        for m in (raw or []):
            b = (m.get("body") or "").strip()
            if not b:
                continue
            d = m.get("direction")
            ts = _to_ms(m.get("dateAdded")) or 0
            msgs.append((ts, d, b))
        msgs.sort(key=lambda x: x[0])
        return msgs[-max_msgs:]
    except Exception:
        return []


def _score(msgs, kws):
    if not kws:
        return 0
    blob = " ".join(b for _t, _d, b in msgs).lower()
    total = 0
    for k in kws:
        # Numbers/money get word-boundary matching so "85" doesn't hit "5885".
        if re.search(r"\d", k):
            total += len(re.findall(r"(?<![\w$])" + re.escape(k) + r"(?![\w])", blob))
        else:
            total += blob.count(k)
    return total


def _render(conv, msgs):
    lines = [f"### Seller: {_name_of(conv)}"]
    phone = (conv.get("phone") or (conv.get("contact") or {}).get("phone") or "")
    if phone:
        lines.append(f"(phone {phone})")
    for ts, d, b in msgs:
        who = "SELLER" if d == "inbound" else "ME"
        when = time.strftime("%b %d %I:%M%p", time.localtime(ts / 1000)) if ts else ""
        lines.append(f"[{when}] {who}: {b}")
    return "\n".join(lines)


def chat(ghl_get, location_id, question, days=7, scan=100, keep=12, _depth=0):
    # _depth > 0 means a TEAMMATE agent (via agent_collab.ask) is consulting Marcus —
    # he answers normally but gets no consult protocol himself (no ask-back loops).
    key = review_agent._api_key()
    if not key:
        return {"needsKey": True,
                "reply": "Add ANTHROPIC_API_KEY to ghl.env and I'll start working your leads."}
    question = (question or "").strip()
    if not question:
        return {"reply": "Ask me something — a seller, a number, a deal."}

    convos = _pull_conversations(ghl_get, location_id, pages=4)
    now = int(time.time() * 1000)
    window = days * 86400 * 1000
    scoped = [c for c in convos
              if (_to_ms(c.get("lastMessageDate")) or 0) >= now - window] or convos
    scoped = scoped[:scan]

    kws = _keywords(question)

    # Pull threads concurrently, score against the question's keywords.
    with ThreadPoolExecutor(max_workers=4) as ex:
        threads = list(ex.map(lambda c: (c, _fetch_thread(ghl_get, c)), scoped))
    threads = [(c, m) for c, m in threads if m]
    ranked = sorted(threads, key=lambda cm: _score(cm[1], kws), reverse=True)

    # Keep the best matches; if nothing scored, fall back to most-recent threads
    # so Marcus can still reason over the latest activity.
    top = [cm for cm in ranked if _score(cm[1], kws) > 0][:keep]
    if not top:
        top = threads[:keep]
    matched = sum(1 for cm in ranked if _score(cm[1], kws) > 0)

    corpus = "\n\n".join(_render(c, m) for c, m in top)[:16000]

    system = (
        "You are Marcus, the LEAD AGENT and head of operations for a real-estate "
        "wholesaling operation (FORGE REI OS). You run the agent team — Scout (triage) "
        "and every other agent report to you, come to you for information and judgment, "
        "and take direction from you; you know the whole business, not just one lane. "
        "Your own craft is screening: tell the operator who is worth a personal CALL — "
        "you are NOT a closer: you never text sellers, "
        "never make offers, and never talk numbers (no ARV/MAO/price unless the seller "
        "already gave one). You are given the operator's REAL recent GoHighLevel SMS "
        "threads with sellers, each labeled with the seller's NAME. Answer the operator's "
        "question directly from these threads — who the seller is, how motivated they "
        "seem, what's missing, and whether to call. If the answer isn't in the threads, "
        "say so plainly and say what would help — do NOT invent a name or number. "
        "Be concise, confident, tactical: 1-4 sentences. End with a next action when useful."
    )
    if _depth == 0:
        # Consult protocol: Marcus may ask Scout one question mid-answer (agent_collab).
        system += "\n\n" + agent_collab.protocol(
            "scout", "lead-triage analyst with live motivation scores + buckets for "
            "every seller thread")
    user = (
        f"OPERATOR'S QUESTION:\n{question}\n\n"
        f"RECENT SELLER THREADS ({len(top)} shown, {matched} matched the question):\n\n"
        f"{corpus if corpus else '(no threads found)'}\n\n"
        "Answer now."
    )
    try:
        reply = review_agent._claude(key, system + caveman.block(), user, max_tokens=600)
    except Exception as e:  # noqa: BLE001
        return {"reply": f"Hit an error reaching my brain: {e}"}
    if _depth == 0:
        # One consult round: Marcus may [ASK SCOUT] mid-answer (agent_collab logs
        # both sides on the bus). Guarded — collab errors never break a normal reply.
        try:
            reply = agent_collab.consult_round(
                "marcus", system, user, reply, key, max_tokens=600,
                ghl_get=ghl_get, location_id=location_id)
        except Exception:  # noqa: BLE001
            pass
    return {"reply": reply or "On it.", "scanned": len(scoped),
            "matched": matched, "shown": len(top)}
