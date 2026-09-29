# Telegram business partners — design (2026-09-29)

## Intent (owner's words, condensed)
Each business lives in its own Telegram chat. HQ is only for diagnostics: API cost,
something down, system health. In a business chat the owner talks to that business's
agent like a Claude chat, and the work actually happens on the box. Every dashboard
feature should be reachable from Telegram (e.g. "create a login for …"). The agents act
as the owner's **business partner** for their business.

## Decisions
- **A1 (approved):** reads run instantly; every write is ONE ✅ tap (rule 2 unchanged).
- **A2 (approved):** Orion's cross-business CEO brief stays in HQ. The daily brief and
  recap split: each business section goes to its own chat, and HQ gets the system,
  agents and cost lines.

## Architecture
`telegram_agent.py` (new, stdlib). A Claude tool-use loop (Sonnet 5, effort low, at
most 6 tool turns). It is called from `telegram_io._handle_message` for plain messages.

**Tools** — the connector's OWN HTTP API, called on loopback (`127.0.0.1:FORGE_PORT`):
- `api_get(path, query)` runs now. The result is capped at 6k chars.
- `api_post(path, body, summary)` NEVER runs directly. It queues a confirm card
  ("✅ Do it / ❌ Cancel"), and the tap (`pgo:<tok>`) executes it.
- `route_help(path)` returns the handler source (dispatch line plus the target
  function's body) so the agent learns the body shape of any route.
- `file_task(title)` goes to `agents_hub.send_task`. It is an internal assignment, so it
  runs immediately.

A loopback call carries no proxy headers, so the daycare routes get the box auto-admin
session. Nothing new touches the security of the public surface.

**Catalog.** The route list is derived at runtime from `connector.py` source:
- GET = `ROUTES` keys plus the daycare/dropship GET handler source.
- POST = the `do_POST` allowlist plus the daycare/dropship POST handler source.

New routes appear automatically, with zero per-feature code.

**Scope.** It follows the agent's business:
- daycare → `/api/daycare/`
- agency → `/api/agency/` plus hub/coach
- wholesale → scout, marcus, screening, prep, deals, buyers, contract, pipeline,
  conversations, ace, autopilot, today, reply, send…
- dropship → `/api/dropship/`
- hq (Orion) → system health, cost, agent registry, action log, owner actions, sync,
  businesses, spend, ops.

Hard deny everywhere: `/auth/`, `/api/agency/reset`, `/api/notify/`, `/api/portal/`.
Both scope and deny are re-checked at tap time.

**Chat routing.**
- Each business chat's default agent is its partner: Solomon, Dyson, Marcus or Midas.
- HQ's default agent is Orion (diagnostics).
- In a bound business chat, switching to another business's agent is refused, with a
  pointer to the right chat.
- The wholesale ops layer (`telegram_ops.route`) runs only in the wholesale chat, or
  in HQ while wholesale is unbound.

**Partner persona.** The system prompt is built in this order:
1. The partner charter from `forge-telegram/skills/business-partner.md` (vault
   `Skills/business-partner.md` wins).
2. The creed.
3. The business context brief.
4. The agent's vault playbook (3k chars).
5. Solomon's lanes, and open tasks.
6. The tool guide plus the scoped catalog.
7. Caveman.

**Without Claude (credits out).** Slash commands still work:
- `/starts` lists start dates.
- `/logins <name>` looks up children, parents and staff, with Login IDs.
- `/pin <name>` produces a reset-PIN confirm card.
- `/status` gives HQ health plus cost.

The tool loop answers with the real API error instead of hanging.

## Error handling
- A Claude error returns the error text.
- A tool error goes back to the model as `{"error": …}`.
- The pending token TTL is 30 min, and a token can be used once.
- A POST result is shown in the tapped card's footer (a PIN is visible once, same as
  the dashboard) and appended to the chat history, so the partner can continue.

## Testing
`test_telegram_agent.py`, with fake Claude and a fake HTTP layer:
- A GET tool runs.
- A POST tool queues and does not run; the tap runs it once and the second tap is
  expired.
- A scope violation is refused.
- The deny list holds.
- The catalog contains known routes.
- A business chat refuses a foreign agent.
- The ops layer is not run in the daycare chat.
- `/logins` and `/pin` work without Claude.

Plus the existing Telegram suites, and two Sonnet reviewers (correctness, security).
