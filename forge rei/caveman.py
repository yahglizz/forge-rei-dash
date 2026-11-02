"""caveman.py — operator-chat answer style: caveman brevity + ADHD-friendly shape.

Appended LAST to OPERATOR-FACING CHAT system prompts ONLY: Scout/Atlas/Retell chat
(agents_chat.py), Solomon/Midas/Orion chat (agents_hub.py), agency Dyson/Eco chat
(agency_agents.py), Marcus chat (marcus_chat.py), the consult-round final reply
(agent_collab.py, passed in by those chats); text_block() goes on the Telegram partners
(telegram_agent.py) and gateway chat (agent_gateway.py). Cuts Anthropic OUTPUT tokens on
every operator reply.

NEVER used on: seller-facing SMS drafts (`marcus_engine._ai_draft` — voice +
quality critical), internal scoring/screening/underwriting jobs, briefs, the
creed, or any JSON generator. Substance / names / numbers / Unknowns stay — only
filler is cut.

Two parts:
  1. caveman — mirrors github.com/JuliusBrussee/caveman (the operator's own house
     style). Intensity FORGE_CAVEMAN_LEVEL = lite | full (default) | ultra.
  2. ADHD shape — the owner's reading needs, adapted for agents from
     github.com/ayghri/i-have-adhd (MIT, © 2026 Ayoub Ghriss; vendored at
     vendor/i-have-adhd/, commit 1ecea19). FORGE_ADHD=0 drops just this part.
FORGE_CAVEMAN=0 turns the whole block off. Env is read per call (no restart needed
for a test; the box still needs a restart to change its unit env).
"""
import os

# Shared spine — the discipline that holds at every level. Substance never dies.
_CORE = (
    "\n\n=== ANSWER STYLE — BE BRIEF (token discipline) ===\n"
    "Answer the operator in the fewest words that fully answer. This is a cost "
    "rule and a clarity rule at once.\n"
    "- Lead with the answer. No preamble, no 'great question', no restating his "
    "question, no sign-off.\n"
    "- Keep every fact, name, number, and the reasoning that changes the "
    "decision. Cut everything else.\n"
    "- Never drop a real caveat or an Unknown for brevity — evidence discipline "
    "outranks this. Be short, not wrong.\n"
    "- Keep code, commands, API names, and exact error strings verbatim — never "
    "abbreviate those.\n"
)

# Per-level tightening. Only the ACTIVE level's line is injected (input-token
# thrift): more compression = fewer output tokens, each level costs one line.
_LEVELS = {
    "lite": (
        "- Level LITE: drop filler and hedging, keep full sentences. Tight and "
        "professional.\n"
    ),
    "full": (
        "- Level FULL (caveman): terse bullet fragments over full sentences. "
        "Drop articles (a/an/the) and filler (just/really/basically). Short "
        "synonyms (big not extensive, fix not 'implement a solution for'). One "
        "line if one line does it. Never pad to sound thorough.\n"
    ),
    "ultra": (
        "- Level ULTRA: strip conjunctions when cause-then-effect stays clear. "
        "One word when one word enough. State each fact once. No invented "
        "abbreviations (cfg/impl/req) — they save zero tokens and cost clarity.\n"
    ),
}

# The owner has ADHD: shape the reply so he can ACT on it (i-have-adhd, agent-side).
_ADHD = (
    "\n=== SHAPE FOR AN ADHD READER (the owner) ===\n"
    "1. First line = the answer or the next action. Never context first.\n"
    "2. Multi-step work = a numbered list, one action per step, fewest steps that work.\n"
    "3. End with ONE concrete next action he can do in under 2 minutes (a tap, a call, a name).\n"
    "4. No tangents. A second issue gets one closing line: 'Separately: X. Want that next?'\n"
    "5. Max 5 items per list, best first. Hold the rest; show on request. Never hide one that "
    "changes the decision.\n"
    "6. Errors: matter-of-fact — cause, then fix. No 'uh oh'.\n"
    "7. No preamble ('Great question', 'Let me…', 'Sure!'), no recap, no closer ('Hope this "
    "helps', 'Let me know').\n"
    "8. Caveman brevity and evidence discipline still hold: Unknowns, sources, date windows "
    "and real caveats are never cut to look short.\n"
    "Exceptions (full prose): he asks to 'explain' or 'walk me through' (use short headers, "
    "still no preamble/closer); anything irreversible or outward (send, spend, delete, launch) "
    "— state the exact effect in full sentences before he taps.\n"
)


# Telegram and the n8n chat page: the owner reads on his phone and wants an assistant, not a
# report (owner 2026-11-02). Replaces block() there; the dashboard chats keep block().
_TEXT = (
    "\n\n=== HOW YOU TEXT THE OWNER (this beats every style rule above) ===\n"
    "You are his assistant, texting him on his phone. Sound like a sharp person, not a report.\n"
    "Your first word starts the answer: no opener ('Sure', 'Got it', 'Good news'), no restating his "
    "question.\n"
    "Earlier replies in this thread may be long and formatted. Never copy them or mention them.\n"
    "Example. He asks: how many tours this week\n"
    "You text: 3 this week, all at 2318: Ana Mon 1:30, Ben Tue 1:00, Cara Fri 1:00.\n"
    "- Answer exactly what he asked in one to three short, plain sentences, then stop.\n"
    "- Normal sentences. No bold, no headers, no markdown. A few names or times go in one sentence. "
    "Use a list only when he asks for one: five items at most, one short line each.\n"
    "- No 'Source:' line, no 'checked just now', no recap, no 'Next action' line, no 'Separately', "
    "no sign-off. Say where a number came from only if he asks or it is in doubt.\n"
    "- Add a next step only when something needs him today, in one short sentence.\n"
    "- Don't know: say so in a few words. Never guess. A caveat that changes the answer stays, in "
    "one clause. Ad and money numbers keep their date range.\n"
    "- He says why or explain: give more.\n"
    "- Anything outward (send, spend, delete, launch): state the exact effect in full sentences "
    "before he taps.\n"
)


# Sits on his newest message: a rule at the end of an 88k prompt loses to a thread of long replies.
TEXT_NUDGE = "\n\n[Text back in one to three plain sentences, no bullets, unless I asked for a list.]"


def text_block():
    """The owner-texting style, or '' when FORGE_CAVEMAN=0. Never raises."""
    return "" if os.environ.get("FORGE_CAVEMAN", "1") == "0" else _TEXT


def _level():
    lv = (os.environ.get("FORGE_CAVEMAN_LEVEL", "full") or "full").strip().lower()
    return lv if lv in _LEVELS else "full"


def block(level=None):
    """The answer-style instruction, or '' when FORGE_CAVEMAN=0. Never raises.

    level overrides FORGE_CAVEMAN_LEVEL for a single call (lite|full|ultra).
    FORGE_ADHD=0 drops the ADHD shape and keeps caveman."""
    if os.environ.get("FORGE_CAVEMAN", "1") == "0":
        return ""
    lv = level or _level()
    if lv not in _LEVELS:
        lv = "full"
    adhd = _ADHD if os.environ.get("FORGE_ADHD", "1") != "0" else ""
    return _CORE + _LEVELS[lv] + adhd
