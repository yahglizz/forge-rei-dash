"""caveman.py — operator-chat brevity ("caveman") block. Token discipline.

Appended to OPERATOR-FACING CHAT system prompts ONLY: Scout/Atlas/Retell chat
(agents_chat.py), daycare Solomon/Nora/Nova chat (agents_hub.py), agency
Dyson/Eco chat (agency_agents.py), Marcus screening chat (marcus_chat.py). Cuts
Anthropic OUTPUT tokens on every operator reply.

NEVER used on: seller-facing SMS drafts (`marcus_engine._ai_draft` — voice +
quality critical), internal scoring/screening/underwriting jobs, briefs, or the
creed. Substance / names / numbers / Unknowns stay — only filler is cut.

Flip off with FORGE_CAVEMAN=0. The block is appended last, so it frames tone
without outranking the creed or evidence discipline above it.
"""
import os

_ON = os.environ.get("FORGE_CAVEMAN", "1") != "0"

_BLOCK = (
    "\n\n=== ANSWER STYLE — BE BRIEF (token discipline) ===\n"
    "Answer the operator in the fewest words that fully answer. This is a cost "
    "rule and a clarity rule at once.\n"
    "- Lead with the answer. No preamble, no 'great question', no restating his "
    "question, no sign-off.\n"
    "- Terse bullet fragments over full sentences. Drop filler words.\n"
    "- Keep every fact, name, number, and the reasoning that changes the "
    "decision. Cut everything else.\n"
    "- One line if one line does it. Never pad to sound thorough.\n"
    "- Never drop a real caveat or an Unknown for brevity — evidence discipline "
    "outranks this. Be short, not wrong."
)


def block():
    """The brevity instruction, or '' when FORGE_CAVEMAN=0. Never raises."""
    return _BLOCK if _ON else ""
