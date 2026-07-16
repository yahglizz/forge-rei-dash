"""caveman.py — operator-chat brevity ("caveman") block. Token discipline.

Appended to OPERATOR-FACING CHAT system prompts ONLY: Scout/Atlas/Retell chat
(agents_chat.py), daycare Solomon/Nora/Nova chat (agents_hub.py), agency
Dyson/Eco chat (agency_agents.py), Marcus screening chat (marcus_chat.py). Cuts
Anthropic OUTPUT tokens on every operator reply.

NEVER used on: seller-facing SMS drafts (`marcus_engine._ai_draft` — voice +
quality critical), internal scoring/screening/underwriting jobs, briefs, or the
creed. Substance / names / numbers / Unknowns stay — only filler is cut.

Mirrors the caveman SKILL (github.com/JuliusBrussee/caveman) that governs Claude
Code / the operator's own replies — same house style, agent side. Intensity via
FORGE_CAVEMAN_LEVEL = lite | full (default) | ultra. Flip the whole thing off
with FORGE_CAVEMAN=0. The block is appended last, so it frames tone without
outranking the creed or evidence discipline above it.
"""
import os

_ON = os.environ.get("FORGE_CAVEMAN", "1") != "0"

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


def _level():
    lv = (os.environ.get("FORGE_CAVEMAN_LEVEL", "full") or "full").strip().lower()
    return lv if lv in _LEVELS else "full"


def block(level=None):
    """The brevity instruction, or '' when FORGE_CAVEMAN=0. Never raises.

    level overrides FORGE_CAVEMAN_LEVEL for a single call (lite|full|ultra)."""
    if not _ON:
        return ""
    lv = level or _level()
    if lv not in _LEVELS:
        lv = "full"
    return _CORE + _LEVELS[lv]
