"""agent_collab.py — agent↔agent consults for FORGE REI OS (Marcus ⇄ Scout).

Lets one chat agent ask the other a question MID-ANSWER, without the operator in the
loop: Marcus can pull Scout's live triage read, and Scout can pull Marcus's read of the
real GHL seller threads. The asking agent emits a one-line [ASK <AGENT>] marker as its
whole first reply, gets the teammate's answer injected back, then writes its final
reply for the operator.

Both sides of every consult are logged on the agent bus so they show in the Command
Center / Comms feed. Depth-capped at MAX_DEPTH=1 — a consulted agent can never consult
back (no ping-pong loops). ask() and consult_round() NEVER raise: on any failure the
operator still gets a reply (the teammate answer degrades to an "(unavailable: …)"
note, or the first reply goes out with the marker stripped).
"""
import re

import agent_bus

MAX_DEPTH = 1  # one consult hop — the consulted agent answers from its own data only

# The [ASK X] marker an agent emits as its ENTIRE first reply to request a consult.
_ASK_RE = re.compile(r"^\s*\[ASK (SCOUT|MARCUS)\]\s*(.+)", re.DOTALL)


def protocol(other, role):
    """The system-prompt block that teaches an agent how to consult its teammate."""
    return (
        f"TEAMMATE: You can consult {other.title()} (the {role}) when his data would "
        "improve your answer. To do it, reply with EXACTLY one line and nothing else: "
        f"[ASK {other.upper()}] <your question>. You will receive the teammate's answer "
        "and can then give your final reply. Only consult when genuinely needed."
    )


def _log(frm, to, kind, text, data):
    """Best-effort bus log — a comms-feed hiccup must never kill a consult."""
    try:
        agent_bus.send(frm, to, kind, text, data)
    except Exception:  # noqa: BLE001
        pass


def ask(asker, target, question, ghl_get=None, location_id=None, scout=None, depth=0):
    """One agent asks the other; returns the teammate's answer as a plain string.

    target "scout" runs the same Scout-persona Claude call the dashboard chat uses
    (live triage data read from disk — no scout instance needed); target "marcus"
    runs the full marcus_chat GHL-thread search. Both sides log on the agent bus.
    Never raises — errors come back as "(<target> unavailable: …)" strings.
    """
    target = (target or "").strip().lower()
    question = (question or "").strip()
    if depth >= MAX_DEPTH:
        return "(consult depth limit reached)"
    if not question:
        return f"({target or 'teammate'} unavailable: empty question)"

    _log(asker, target, "ask",
         f"🤝 {str(asker).title()} → {target.title()}: {question[:200]}",
         {"type": "collab", "q": question})
    try:
        if target == "scout":
            # Same Scout persona as agents_chat — answers from the live triage data
            # on disk (scout.json) + the learned brain playbook. Imported here (not
            # at module top) to avoid circular imports.
            import review_agent
            import scout_triage
            key = review_agent._api_key()
            if not key:
                answer = "(scout unavailable: no ANTHROPIC_API_KEY)"
            else:
                system = (
                    "You are Scout, the lead-triage analyst for a real-estate WHOLESALING "
                    "business. You read the operator's GoHighLevel seller threads, score "
                    "how motivated each seller is, and advise who to contact first (speed "
                    "to lead). A teammate agent (not the operator) is consulting you — "
                    "answer its question directly and concisely from the live triage data "
                    "below.\n\n"
                    "=== LIVE TRIAGE DATA ===\n" + scout_triage.context_from_disk()
                    + "\n\n=== YOUR LEARNED PLAYBOOK (from the brain) ===\n"
                    + (scout_triage.playbook_text(1500) or "(none yet)")
                )
                answer = (review_agent._claude(key, system, question, max_tokens=500)
                          or "").strip() or "(scout had no answer)"
        elif target == "marcus":
            import marcus_chat
            # _depth marks this as a consult so Marcus can't consult back (no loops).
            res = marcus_chat.chat(ghl_get, location_id, question, _depth=depth + 1)
            answer = ((res or {}).get("reply") or "").strip() or "(marcus had no answer)"
        else:
            answer = f"({target} unavailable: unknown agent)"
    except Exception as e:  # noqa: BLE001
        answer = f"({target} unavailable: {e})"

    _log(target, asker, "answer",
         f"💬 {target.title()} → {str(asker).title()}: {answer[:200]}",
         {"type": "collab"})
    return answer


def consult_round(asker, system, user, reply, key, max_tokens=600,
                  ghl_get=None, location_id=None, scout=None):
    """One consult round on an agent's first reply. If `reply` is an [ASK X] marker,
    ask the teammate via ask(), then make a SECOND Claude call (same system prompt,
    teammate's answer appended to the user content) and return that final reply with
    a visible "🤝 consulted X" trace. No re-detect on the second reply — one round
    max. Never raises: on any error the first reply goes out, marker stripped."""
    m = _ASK_RE.match(reply or "")
    if not m:
        return reply
    try:
        import review_agent
        target = m.group(1).lower()
        question = m.group(2).strip()
        answer = ask(asker, target, question, ghl_get=ghl_get,
                     location_id=location_id, scout=scout)
        user2 = (user + f"\n\n[{target.upper()} ANSWERED]: {answer}\n\n"
                 "Now give your final answer to the operator (do not consult again):")
        final = (review_agent._claude(key, system, user2, max_tokens=max_tokens)
                 or "").strip()
        if final:
            return final + f"\n\n🤝 consulted {target.title()}"
    except Exception:  # noqa: BLE001
        pass
    # Fall back: hand the operator the first reply with the marker token stripped.
    return re.sub(r"^\s*\[ASK (SCOUT|MARCUS)\]\s*", "", reply).strip() or reply
