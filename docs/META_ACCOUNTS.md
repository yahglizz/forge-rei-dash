# Meta accounts: two businesses, two ad accounts. They never mix.

*Single source of truth for which Meta ad account, Facebook Page and Instagram belongs to which
FORGE business. Agents and code read this before any Meta / Instagram / Pipeboard call.
Verified live through the Pipeboard MCP on 2026-10-31. Ids are not secrets; tokens are, and never go in this file.*

## The table

| | **Daycare** (A Touch of Blessings) | **Agency** (ClientForge / Forge Labs) |
|---|---|---|
| Agent | Solomon (ads lane: Nova) | Dyson, Eco (ads lane) |
| Ad account | `act_1175564690150627` | `act_2344043939684594` (name `ClienForgePhiladelphia`) |
| Facebook Page | `939494549239823` "A Touch of Blessings Daycare" | **Unknown. No agency Page exists yet.** |
| Instagram | `@atouchofblessing2.3`, id `17841436257715501` (real account) | `@forgelabsphiladelphia`, id `17841464279234508`, "Forge Labs \| Graphic & Software Designer" (real account, linked to `act_2344043939684594` on 2026-10-31) |
| Page-backed IG identity | `17841439350588476` (belongs to the daycare Page) | none |
| Metricool brand | none | `forgelabsx` (blogId 6354174): **TikTok only**, Instagram not yet linked in Metricool |
| Env file / key home | `forge-daycare/config/daycare.env` | `forge-agency/config/agency.env` |
| Env var for the account | `PIPEBOARD_AD_ACCOUNT_ID`, `META_AD_ACCOUNT_MAP={"daycare":...}` | `META_AD_ACCOUNT_MAP={"<clientId>":"act_2344043939684594"}` |

Both ad accounts sit under ONE Pipeboard connection (Facebook login "Yahjair Mack"). Pipeboard's
"Configure Access" lists four ad accounts on that login; only the two above are ticked. `lushlooms`
and the personal `Yahjair Mack` ad account belong to neither business: never read or touch them.

## The rules

1. **Always pass the exact `account_id` on every Pipeboard / Meta call.** Never rely on a default,
   "the first account", or a cached account. With two accounts on one login, a call without
   `account_id` can land on the wrong business.
2. **Daycare agents use only the daycare column. Agency agents use only the agency column.**
   A daycare id in an agency call (or the reverse) is a bug: stop and say so.
3. **Do not use the daycare Page or its page-backed Instagram for agency work.** Pipeboard shows the
   daycare Page `939494549239823` (and its identity `17841439350588476`) under the *agency* ad account too,
   because the same login owns both (both ad accounts live in the one Meta portfolio "ATOB daycare",
   business_id `2074190253211758`). Using it would run agency content under the daycare's name. Agency ads that need
   a Page must wait for the agency's own Facebook Page; until then say "Unknown / no agency Page".
4. **Code already enforces this.** `agency_ads.agency_account` is a fail-closed allowlist (the agency's own
   `META_AD_ACCOUNT_MAP` minus the daycare's ids). `agency_ads.owner_of()` labels the daycare account
   `accountOwner:'daycare'`. Do not widen either. Agency Instagram code (`agency_instagram.py`) pins
   `act_2344043939684594` + `@forgelabsphiladelphia`, and refuses any draft naming the daycare.
   Agents learn this from `forge-agency/skills/agency-instagram-tools.md`.
5. **Instagram identity is not API-linkable.** Linking a real Instagram to an ad account is done by the owner in
   Meta Business Settings > Instagram Accounts. The agency's is `@forgelabsphiladelphia` (`17841464279234508`); use
   only that for agency Instagram work, never `@atouchofblessing2.3` or the daycare's page-backed identity.
6. **Propose, review, execute.** Pipeboard reads are free. Creating or changing campaigns, ads, posts or spend needs the
   owner's yes, per `CLAUDE.md` rule 2.
7. Metricool (`forgelabsx`) is the **agency's** social tool. The daycare's reuse of `agency_social.py` runs on its
   own creds (`daycare_growth.py`); never point it at `forgelabsx`.

## Still open

- Link `@forgelabsphiladelphia` to Metricool brand `forgelabsx` (Metricool shows TikTok only) and set `METRICOOL_USER_TOKEN`.
- Create the agency's own Facebook Page, fill the Page `Unknown` cell above.
- Add the agency ids to `META_AD_ACCOUNT_MAP` in `forge-agency/config/agency.env` (owner approval; live env).
- Update this file in the same change as each of the above.
