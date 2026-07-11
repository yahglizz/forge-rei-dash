# Goals & Deals — Tasks page rebuild (design + contract)

Date: 2026-06-08 · Status: approved

## Goal
Turn the read-only Tasks page into a Goals & Deals command center.
**Stats come from GHL (derived, auto-refresh). Goals live in the dashboard (editable JSON store).**

## Sections (in `TasksPage`)
1. **This Month** — GHL tasks due in the current month (existing `/api/tasks`, filtered to month) + a month deal snapshot (deals closed this month, $ this month).
2. **Monthly Goals** — dashboard-owned, editable. Seeded with **"Close my first deal."** Add / edit / toggle / remove + progress bar.
3. **Lifetime Stats** — from GHL: Deals Closed, Total Earned, Avg Fee, JV Deals Done.
4. **Deals That Fell Through** — from GHL: lost/abandoned opps (name, value, stage, when).
Keep the existing `DailyNonNegotiables` card and the existing GHL task list.

## Definitions (GHL-derived)
- **Deal closed** = opportunity `status == "won"`.
- **Earned** = Σ `value` (monetaryValue) of won opps. **Avg fee** = earned / dealsClosed.
- **Fell through** = `status in ("lost","abandoned")`.
- **JV deal** = a won opp where the keyword (`FORGE_JV_KEYWORD`, default `"jv"`, also matches "joint venture") appears in the opp `name`, `stage`, mapped pipeline name, OR any of the contact `tags`. Zero extra API calls.
- **This month** = `updated[:7] == month_prefix` (`YYYY-MM`). (`updated` = opp updatedAt ≈ when marked won. Approximation, acceptable.)

## Opp shape (from `_opp_view()` in connector.py — already available)
`{ id, name, value:float, status, pipelineId, stageId, stage, contactId, phone, tags:[], updated }`

## Workstreams (parallel, isolated)

### A — `deal_stats.py` (NEW FILE, pure functions, no GHL coupling)
```python
def compute(opps, pls=None, jv_keyword="jv", month_prefix=""):
    # opps: list of _opp_view dicts. pls: pipelines list (for pipeline-name JV match), optional.
    # month_prefix: "YYYY-MM" (caller passes time.strftime). Pure + deterministic.
    return {
      "lifetime": {"dealsClosed": int, "totalEarned": float, "avgFee": float,
                   "jvDeals": int, "fellThrough": int},
      "month":    {"prefix": month_prefix, "dealsClosed": int, "earned": float, "fellThrough": int},
      "openValue": float,                      # Σ value of open opps (pipeline potential)
      "closedList":      [{"id","name","value","stage","jv":bool,"updated"}],  # won, newest first
      "fellThroughList": [{"id","name","value","stage","status","updated"}],   # lost+abandoned, newest first
      "jvList":          [{"id","name","value","stage","updated"}],
    }
```
- Provide `_is_jv(opp, kw, pipeline_name_by_id)` helper. Match `kw` and "joint venture", case-insensitive, across name/stage/pipeline-name/tags.
- Sort lists by `updated` desc (None last). Round money to 2dp.
- No imports beyond stdlib. Must `python3 -c "import ast; ast.parse(...)"` clean.

### B — `monthly_goals.py` (NEW FILE, mirror `daily_goals.py` exactly)
- State: `marcus_state/monthly_goals.json`, `threading.Lock`, `_load`/`_save`.
- Shape: `{ "month": "YYYY-MM", "goals": [{"id","text","done":bool}], "updatedAt": ms }`.
- Seed on first run: one goal `{text: "Close my first deal", done: false}`.
- **Month roll-over** in a `_ensure_month(d)`: if stored `month` != current, set month to current and reset every goal's `done` to false (recurring monthly goals carry over, unchecked). Keep the goal texts.
- `get()` → ensured state. `update(op, gid=None, text=None)` where op ∈ `add|toggle|edit|remove`:
  - add → append `{id, text, done:false}` (id = millis-based string).
  - toggle → flip `done` for gid. edit → set text for gid. remove → drop gid.
  - returns the updated state. Ignore unknown op safely.
- Pure stdlib. ast-clean.

### C — `TasksPage` in `pages.jsx` (rebuild the ONE component, additive elsewhere)
- Consumes: `/api/tasks?scan=60` (existing), `/api/deals/stats` (new GET), `/api/goals/monthly` (new GET), `/api/goals/monthly/update` (POST `{op,gid,text}`).
- Keep `<DailyNonNegotiables />` and the GHL task list. Add the 4 sections above.
- **Collision rules (hard):** this file's hooks already alias `useStateP`/`useEffectP` — reuse those. NO computed JSX tags (`<Icons[x]/>`) — resolve to a const first. Unique top-level names if any new helper is added (prefix `Gd`).
- Style: match the existing brutalist/CRT cards — `className="card"/"card-pad"`, CSS vars (`--text,--faint,--green,--orange,--blue,--red,--border,--card-2`), `Icons`, `window.timeAgo`, money via `toLocaleString`. Progress bar = a simple div track + fill.
- Optimistic goal toggle then `refresh()`; alert on POST failure.
- Must pass `node /tmp/valjsx.js pages.jsx`.

## Integration (main thread, after agents return — NOT the agents' job)
`connector.py`: `import deal_stats, monthly_goals`; `api_deal_stats` ( `pls,opps=_opp_view()` → `deal_stats.compute(opps, pls, JV_KW, time.strftime("%Y-%m"))` ); `api_goals_monthly` → `monthly_goals.get()`; add to `ROUTES` (`/api/deals/stats`, `/api/goals/monthly`); add `/api/goals/monthly/update` to the POST allowlist tuple + `elif` dispatch → `monthly_goals.update(body.get("op"), body.get("gid"), body.get("text"))`. `JV_KW = os.environ.get("FORGE_JV_KEYWORD","jv").lower()`.

## Validate + deploy
`ast.parse` the .py files, `node /tmp/valjsx.js pages.jsx`, then `./deploy/push.sh root@24.199.81.124` + SSH-verify (service active, `/api/deals/stats` & `/api/goals/monthly` 200, secret 404).
