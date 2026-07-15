"""agents_chat.py — talk to your AI agents directly from the dashboard.

Powers the Agents tab (iMessage-style, but the left list is your AGENTS, not leads):
  • Marcus  — the lead-screening analyst. Routes to marcus_chat, so he answers
              from your REAL GoHighLevel seller threads (screens; never texts/offers).
  • Retell agents — your live outbound voice agents. Chatting with one runs Claude
              in that agent's configured persona (its general_prompt) so you can
              test tone/answers in text before it ever dials.

Graceful: no ANTHROPIC_API_KEY -> {"needsKey": True}.
"""
import review_agent
import caveman
import retell_io
import marcus_chat
import scout_triage
import agent_collab


def roster():
    """The agent list for the left rail. Marcus is always first."""
    agents = [{
        "id": "marcus",
        "name": "Marcus",
        "role": "Lead Agent · head of the operation · screening + directing the team (never texts/offers)",
        "kind": "coordinator",
        "voice": "",
    }, {
        "id": "scout",
        "name": "Scout",
        "role": "Lead Triage · ranks your seller threads by motivation + speed to lead",
        "kind": "coordinator",
        "voice": "",
    }, {
        "id": "atlas",
        "name": "Atlas",
        "role": "Deal Underwriter · offer anchors, MAO math + call cards (never contacts sellers)",
        "kind": "coordinator",
        "voice": "",
    }]
    seen = {"marcus", "scout", "atlas"}
    try:
        if retell_io.has_key():
            for a in (retell_io.status().get("agents") or []):
                aid = a.get("id")
                if not aid or aid in seen:
                    continue
                seen.add(aid)
                agents.append({
                    "id": aid,
                    "name": a.get("name") or "Agent",
                    "role": "Outbound voice agent · Retell",
                    "kind": "retell",
                    "voice": a.get("voice") or "",
                })
    except Exception:
        pass
    return {"agents": agents, "hasKey": bool(review_agent._api_key())}


def _history_block(history, limit=8):
    if not history:
        return ""
    lines = []
    for h in history[-limit:]:
        role = "OPERATOR" if h.get("role") == "user" else "YOU"
        txt = (h.get("text") or "").strip()
        if txt:
            lines.append(f"{role}: {txt}")
    return ("\n".join(lines) + "\n") if lines else ""


def _detect_audit_window(message):
    """Detect a Missed-Leads audit intent + parse the day window from a Scout message.

    Intent uses specific phrases (not loose substrings like "dig"/"30") so ordinary
    Scout questions don't trigger the expensive deep audit. Durations are parsed only
    when attached to a time unit. Returns (intent: bool, window: int) clamped 1..60.
    """
    import re
    text = (message or "").lower()
    # Multi-word phrases are specific enough to match as substrings. (Dropped the loose
    # ones — "find leads i" matched "find leads in Miami", "potential leads i" matched
    # "potential leads in Tampa".)
    phrases = (
        "missed lead", "missed leads", "leads i missed", "lead i missed",
        "sellers i missed", "seller i missed", "leads i may have missed",
        "anyone i missed", "anything i missed", "deep dive", "deep-dive",
        "go through my messages", "comb through my messages", "review my messages",
        "go back through my messages", "sweep my messages",
    )
    # "audit" only as a whole word, so "auditor"/"auditing tags" don't trigger a sweep.
    intent = any(p in text for p in phrases) or bool(re.search(r"\baudit\b", text))

    window = 7  # default
    m = re.search(r"\b(\d+)\s*(day|days|week|weeks|month|months)\b", text)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit.startswith("week"):
            window = n * 7
        elif unit.startswith("month"):
            window = n * 30
        else:
            window = n
    elif "last month" in text or "past month" in text:
        window = 30
    elif "yesterday" in text:
        window = 1
    elif "last week" in text or "past week" in text or "this week" in text:
        window = 7

    window = max(1, min(60, window))
    return intent, window


def _format_audit_rundown(report):
    """Plain-text ranked rundown of missed leads (no Claude). Used when no key."""
    found = (report.get("found") or [])
    scanned = report.get("scanned", 0)
    summary = report.get("summary") or ""
    if not found:
        base = summary or "No missed leads found in that window."
        return (f"{base}\n\nScanned {scanned} thread(s). A weekly auto-sweep keeps "
                "watching for dropped seller leads.")
    lines = [summary.strip()] if summary else []
    lines.append(f"Scanned {scanned} thread(s) — {len(found)} look like missed leads:\n")
    for i, r in enumerate(found[:12], 1):
        name = r.get("name") or "Unknown"
        score = r.get("score", 0)
        signal = r.get("signal") or ""
        cold = r.get("daysCold", 0)
        action = r.get("recommendedAction") or ""
        lines.append(f"{i}. {name} (score {score}, cold {cold}d) — {signal}")
        if action:
            lines.append(f"   → Move: {action}")
    lines.append("\nA weekly auto-sweep runs on the box, so these keep getting flagged.")
    return "\n".join(lines)


def chat(ghl_get, location_id, agent_id, message, history=None, scout=None,
         enable_commands=True):
    message = (message or "").strip()
    if not message:
        return {"reply": "Say something and I'll answer."}

    if enable_commands and (agent_id or "marcus") in ("marcus", "scout", "atlas"):
        try:
            import telegram_ops
            handled = telegram_ops.handle_agent_command(agent_id or "marcus", message,
                                                        source="dashboard")
            if handled:
                return handled
        except Exception as e:  # noqa: BLE001
            return {"reply": f"Couldn't run that command: {e}",
                    "agent": (agent_id or "Marcus").title()}

    # Marcus = the live GHL-search brain.
    if agent_id == "marcus" or not agent_id:
        return marcus_chat.chat(ghl_get, location_id, message)

    # Scout — deep "Missed Leads" audit intent. Detected BEFORE the normal Claude
    # call so the operator can say "go through my messages from last week" and Scout
    # actually runs a retro sweep. Works with or without an Anthropic key.
    if agent_id == "scout" and scout is not None:
        intent, window = _detect_audit_window(message)
        if intent:
            try:
                report = scout.retro_audit(days=window, query=message)
            except Exception as e:  # noqa: BLE001
                return {"reply": f"Couldn't run the sweep: {e}", "agent": "Scout"}
            key = review_agent._api_key()
            if not key:
                return {"reply": _format_audit_rundown(report),
                        "agent": "Scout", "audit": report}
            found = (report.get("found") or [])[:12]
            scanned = report.get("scanned", 0)
            summary = report.get("summary") or ""
            rows_lines = []
            for r in found:
                rows_lines.append(
                    f"- {r.get('name') or 'Unknown'} | score {r.get('score', 0)} | "
                    f"cold {r.get('daysCold', 0)}d | signal: {r.get('signal') or ''} | "
                    f"last seller said: {(r.get('lastSellerSaid') or '')[:140]} | "
                    f"recommended: {r.get('recommendedAction') or ''}")
            rows_block = "\n".join(rows_lines) or "(no missed leads found this sweep)"
            system = (
                "You are Scout, the lead-triage analyst for a real-estate WHOLESALING "
                "business. You just ran a deep retro audit of the operator's GoHighLevel "
                "seller threads to surface MISSED leads — sellers who gave a real selling "
                "signal that we never capitalized on (dropped ball / went cold). Give the "
                "operator a SHORT, ranked rundown he can act on right now: for each missed "
                "lead, the name, a one-line why-it's-a-missed-lead, and the next move. "
                "Highest score first. Be concise and specific — no fluff, no preamble. "
                "End by noting a weekly auto-sweep runs on its own so nothing slips again."
            )
            user = (
                f"Audited the last {report.get('days', window)} day(s). "
                f"Scanned {scanned} thread(s). Summary: {summary}\n\n"
                f"Missed leads (ranked):\n{rows_block}\n\n"
                "Write the operator's rundown now."
            )
            try:
                reply = review_agent._claude(key, system, user, max_tokens=700)
            except Exception:  # noqa: BLE001
                reply = _format_audit_rundown(report)
            return {"reply": reply or _format_audit_rundown(report),
                    "agent": "Scout", "audit": report}

    key = review_agent._api_key()
    if not key:
        return {"needsKey": True,
                "reply": "Add ANTHROPIC_API_KEY to ghl.env so I can answer."}

    # Scout = the lead-triage brain. Answers from live triage data (scout.json).
    if agent_id == "scout":
        system = (
            "You are Scout, the lead-triage analyst for a real-estate WHOLESALING "
            "business. You read the operator's GoHighLevel seller threads, score how "
            "motivated each seller is, and tell him who to TEXT BACK FIRST (speed to "
            "lead). You do NOT text sellers — Marcus does that. You rank, tag, and "
            "advise. Marcus is your LEAD AGENT — the head of the whole operation: when "
            "you need a screening read, business judgment, or info outside triage, "
            "consult him instead of guessing. Be concise, specific, and use the live "
            "triage data below. When he asks who to contact, give a short ranked list "
            "with name, phone, and why.\n\n"
            "=== LIVE TRIAGE DATA ===\n" + scout_triage.context_from_disk()
            + "\n\n=== YOUR LEARNED PLAYBOOK (from the brain) ===\n"
            + (scout_triage.playbook_text(1500) or "(none yet)")
            + "\n\n" + agent_collab.protocol(
                "marcus", "LEAD AGENT — head of the operation, reads the operator's "
                "real GHL seller threads and makes the business calls")
        )
        user = _history_block(history) + f"OPERATOR: {message}\nYOU:"
        try:
            reply = review_agent._claude(key, system + caveman.block(), user, max_tokens=600)
        except Exception as e:  # noqa: BLE001
            return {"reply": f"Hit an error reaching my brain: {e}"}
        # One consult round: Scout may [ASK MARCUS] mid-answer (agent_collab logs
        # both sides on the bus). Guarded — collab errors never break a normal reply.
        try:
            reply = agent_collab.consult_round(
                "scout", system, user, reply, key, max_tokens=600,
                ghl_get=ghl_get, location_id=location_id, scout=scout)
        except Exception:  # noqa: BLE001
            pass
        return {"reply": reply or "On it.", "agent": "Scout"}

    # Atlas — the deal underwriter. Answers from his live prep records.
    if agent_id == "atlas":
        try:
            import deal_prep as _dp_mod
            preps = []
            dp = getattr(_dp_mod, "INSTANCE", None)
            if dp is not None:
                preps = dp.list_all()[:10]
            import json as _json
            prep_block = _json.dumps(preps, default=str)[:6000] or "(no preps yet)"
        except Exception:  # noqa: BLE001
            prep_block = "(prep data unavailable)"
        system = (
            "You are Atlas, the deal UNDERWRITER for a real-estate wholesaling business "
            "(FORGE REI OS). You prep every screened-interested seller so the operator "
            "walks into the call with numbers: facts from the thread, offer anchors "
            "(opening / target / walkaway derived from the seller's own ask), the MAO "
            "math with unknowns flagged, and a negotiation call card. You never contact "
            "sellers, never invent an ARV, and your numbers are INTERNAL prep only. "
            "Marcus is your lead agent. Be concise and tactical.\n\n"
            "=== YOUR LIVE DEAL PREPS ===\n" + prep_block
            + "\n\n" + agent_collab.protocol(
                "marcus", "LEAD AGENT — head of the operation, reads the operator's "
                "real GHL seller threads and makes the business calls")
        )
        user = _history_block(history) + f"OPERATOR: {message}\nYOU:"
        try:
            reply = review_agent._claude(key, system + caveman.block(), user, max_tokens=600)
        except Exception as e:  # noqa: BLE001
            return {"reply": f"Hit an error reaching my brain: {e}"}
        try:
            reply2 = agent_collab.consult_round(
                "atlas", system, user, reply, key, ghl_get=ghl_get,
                location_id=location_id, scout=scout)
            reply = reply2 or reply
        except Exception:  # noqa: BLE001
            pass
        return {"reply": reply or "On it.", "agent": "Atlas"}

    # Retell agent — answer in its configured persona.
    name, prompt = "Agent", ""
    try:
        a = retell_io.get_agent(agent_id)
        name = a.get("agentName") or "Agent"
        prompt = (a.get("generalPrompt") or "").strip()
    except Exception as e:  # noqa: BLE001
        return {"reply": f"Couldn't load that agent's config: {e}"}

    system = (
        f"You are '{name}', an AI voice agent for a real-estate wholesaling company. "
        "You are talking by TEXT with the operator (the founder) who built you — he is "
        "testing your tone and answers, NOT a seller. Stay in character per your "
        "configured behavior below, but you may also answer his questions about how "
        "you'd handle a call. Be concise and natural.\n\n"
        "=== YOUR CONFIGURED BEHAVIOR ===\n"
        + (prompt or "(no prompt configured yet — answer as a helpful outbound agent)")
    )
    user = _history_block(history) + f"OPERATOR: {message}\nYOU:"
    try:
        reply = review_agent._claude(key, system + caveman.block(), user, max_tokens=500)
    except Exception as e:  # noqa: BLE001
        return {"reply": f"Hit an error reaching my brain: {e}"}
    return {"reply": reply or "On it.", "agent": name}
