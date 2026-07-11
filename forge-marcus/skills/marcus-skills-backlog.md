# Marcus Screening — skills backlog (future capabilities)

Brainstormed upgrades to Marcus's screening brain. Build the high-leverage ones into
`marcus-screening-playbook.md` (or as new screening behaviours) over time.

- **Custom-field hydration.** Pull GHL contact custom fields + opportunity data
  (owner-occupied, condition, asking, lead source) so the report draws on structured
  data, not just the SMS thread. Map per-location custom-field IDs to readable names.
- **Skip-trace / ownership confirm.** Cross-check the contact against a property/owner
  record so "confirm ownership" stops being a perpetual Missing-Info item.
- **Call-outcome feedback loop.** After the operator calls, capture the outcome (booked /
  no-answer / dead / under contract) and feed it into `learn()` so the 1–10 score
  calibrates to which screens actually converted to deals.
- **Voice call-prep export.** One-tap export of the call-prep notes to the phone (or a
  Retell/Ava outbound brief) so the operator has the script in hand on the call.
- **Batch morning brief.** A single "who to call today" digest ranking all Qualified/Hot
  screenings, newest distress first — the operator's daily call list.
- **Objection library.** Grow `callPrep` with a learned objection→response bank (still
  price-free) so the operator handles "I want retail" / "just testing the market" well.
- **Re-screen on new reply.** Auto-refresh a lead's report when the seller sends a new
  message so the screening never goes stale.
- **Duplicate-property detection.** Flag when two threads are the same property/owner.
