# Marcus — Lead Agent

**Business:** Wholesale (REI) · **Emoji:** 🎯 · **Roster id:** `marcus`
**Role:** head of the operation — screens sellers, drafts the text-back, directs the team.

Screens each interested / "not ready" seller into a call-ready report (score,
missing info, red flags, call prep, path to contract), and drafts every seller
text-back in your voice. Auto-screens whatever Scout hands over.

## The hard boundary: never a price by text

**Marcus never states, negotiates, hints at, or invents a price, offer, or number
over text — ever.** The offer is given by a human, on a phone call. A text exists
only to get the seller on that call. If a seller asks for a number, Marcus
acknowledges and pivots; if they push again, it holds the line differently.

Enforced in two places, on purpose: in the prompt, and in code at
`marcus_engine._no_price_over_text`, which swaps any drafted figure for a
call-pivot before the draft ever reaches you.

**It also never replies to our own outreach.** GHL sometimes mis-flags our own
blast as inbound; `marcus_engine._is_our_message()` / `_OUR_OUTREACH_PHRASES`
filters it so no agent answers our own "we buy houses" text.

## Autonomy — where the line sits

| Does on its own | Needs your tap |
|---|---|
| Screen every handed-off lead | **Every seller reply** — all drafts are proposals |
| Draft the text-back | Sending it |
| Rewrite its own playbook + voice | Anything outward |

Legacy SMS auto-responder is **off** by default (`FORGE_MARCUS_SMS=1` re-enables).
The one opt-in exception is AUTOPILOT re-engage bumps — off unless you flip it on
in Telegram, and even then gated to re-engage drafts only, never first replies,
never PRICE/READY/HELP/DNC, with a daily cap and a 9am–8pm ET window.

## Where it lives

- **Screening:** `forge rei/marcus_screening.py` → `Screener`, built at `forge rei/connector.py:1137`
- **Draft engine:** `forge rei/marcus_engine.py` · **Chat:** `forge rei/marcus_chat.py`
- **Config + seed skills:** `forge-marcus/`
- **Creed:** `wholesale-evidence-discipline.md`
- **Skills loaded:** `seller-reply-playbook.md` (the rubric), `wholesale-seller-texter.md` (voice), `closing-plays.md`, `marcus-screening-playbook.md`, `marcus-seller-psychology.md`, `marcus-nurture-followup.md`, `yahjair-voice.md`
- **Learned playbook:** vault `Skills/marcus-playbook.md` + `Skills/yahjair-voice.md` (daily `style_agent`, weekly `review_agent`)

## Routes

`/api/marcus/` — `proposals` · `approve` · `dismiss` · `chat` · `poll` · `status` · `toggle` · `directives`
`/api/screening/` — `queue` · `report` · `run` · `send` · `stage` · `note` · `status` · `learn`
