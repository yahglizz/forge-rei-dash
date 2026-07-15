# Skill: Caveman Brevity (token discipline)

*A reusable brevity discipline for FORGE REI OS. Answer in the fewest words that
fully answer — cut filler, keep substance. Applies to two surfaces.*

---

## Why

Every output token on the Anthropic API costs money, and long answers are usually
worse answers. "Caveman" here means: strip the padding, keep the meat. Short, not
dumb; terse, not wrong.

## The rule

- **Lead with the answer.** No preamble, no "great question", no restating the
  question, no sign-off.
- **Fragments over sentences.** Terse bullets. Drop filler words ("basically",
  "in order to", "it's worth noting that").
- **Keep every fact, name, number, and the reasoning that changes the decision.**
  Cut everything that doesn't.
- **One line if one line does it.** Never pad to sound thorough.
- **Never trade a real caveat or an Unknown for brevity.** Evidence discipline
  outranks brevity. Be short, not wrong.

## Where it's applied

### 1. Dashboard agent chat (cuts the API bill)

`forge rei/caveman.py` → `caveman.block()` is appended (last, so it can't outrank
the creed) to the operator-facing **chat** system prompts:

- `agents_chat.py` — Scout, Atlas, Retell chats
- `agents_hub.py` — daycare Solomon/Nora/Nova chat
- `agency_agents.py` — Dyson/Eco chat
- `marcus_chat.py` — Marcus screening chat

**Never** applied to seller-facing SMS drafts (`marcus_engine._ai_draft` — voice
and quality critical), internal scoring/screening/underwriting/brief jobs, or the
creed. Flip off with `FORGE_CAVEMAN=0`.

### 2. Claude Code replies (cuts Claude Code usage)

Recorded as an operator preference in Claude Code memory
(`feedback: keep-responses-terse`): lead with the answer, fragments over prose,
no preamble/sign-off, keep the numbers, still surface real caveats.

## Guardrail

Brevity is a tone layer, not a license to skip grounding. If being brief would
drop a number, a source, a caveat, or an Unknown that changes the decision —
keep it. The creed always wins.
