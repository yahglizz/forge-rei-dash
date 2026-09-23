# FORGE Mobile UI 2 — handoff

## Changes

- `mobile/m_shell.jsx`, `mobile/mobile.css`: replaced the dark mobile-only look with soft pastel cards, rounded tap targets, and an original inline SVG fox mascot. Added the five-item business tab bar and a header shortcut to Agents.
- `mobile/m_app.jsx`: Today / Wholesale / Agency / Daycare / More navigation. Old Home and Actions land on Today; Convos, Pipeline, and Calc map into Wholesale segments. Agent chat remains one tap away.
- `mobile/m_workspaces.jsx`: Today owner-action preview and active-business cards; new Agency dial tally and call sheet; new Daycare Lead Desk and Solomon brief. Calls, status updates, and stage marks use the existing same-origin routes.
- `mobile/m_home.jsx`: Wholesale Approvals and Hot segments share the existing wholesale logic.
- `mobile/m_agents.jsx`: roster now comes from `/api/agents/registry`, archived agents are hidden, status is visible, and existing shared chat/history and bus remain.
- `mobile/m_more.jsx`: retained all More destinations and grouped them under Pulses, Wholesale tools, System, and Team.
- `mobile/index.html`, `mobile/manifest.json`: loaded the new workspace screen and matched the PWA browser chrome to the pastel UI.

## Navigation map

| Previous path | New path |
|---|---|
| Home | Today → business cards / Wholesale → Approvals |
| Actions | Today → Needs you → See all actions |
| Convos | Wholesale → Convos |
| Pipeline | Wholesale → Pipeline |
| Calc | Wholesale → Calc |
| Agents | Header bot button or More → Agents |
| More tools | More → grouped destinations |
| Agency Call Center | Agency |
| Daycare Lead Desk | Daycare |

Legacy `m_tab` values for home, actions, convos, pipeline, and calc map to a valid landing tab or Wholesale segment.

## Routes and guardrails

- No backend routes or dependencies added. Existing agency, daycare, owner-actions, mission-control, registry, and shared chat routes are used.
- Call, tally, status, and stage controls require an explicit item-level tap. Daycare stage selection has a confirmation sheet. No action was submitted during preview.
- The local connector returned `503: Daycare live operations are disabled`; the Daycare error state rendered. The session-specific 401/403 state could not be exercised locally.

## Validation and known gaps

- `node deploy/valjsx.js mobile/*.jsx` and `node deploy/valjsx.js *.jsx` passed; duplicate top-level JSX names check was empty.
- Previewed Today, Agency, Daycare, More, and Agents against the local UI-only connector (`FORGE_MARCUS=0`, port 7798 because 7799 was already occupied). The preview viewport was desktop-sized; iPhone 390×844, SE 375×667, and Pro Max 430×932 checks remain.
- No before/after screenshot files were saved in `docs/ui-audit/mobile/`.
- No missing backend route was added or stubbed. Daycare live data requires the existing authorized server session.
