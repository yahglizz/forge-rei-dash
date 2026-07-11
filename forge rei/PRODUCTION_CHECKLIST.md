# FORGE REI OS — Production Readiness Checklist

Last audited: 2026-06-06. Be honest with this list — green means *verified*, not *assumed*.

## Verdict (read this first)

The dashboard **already runs 24/7 on DigitalOcean via systemd** (auto-start on boot,
auto-restart on crash) — that core requirement is **MET**. It is **not** a
Docker/Postgres/Redis/Node app and does not need to be. The real gaps are
**security** (no app-level auth, secret-handling) and **operational** (schedulers
not armed on the box, no backups). Do **NOT** put this on the public internet until
the auth item below is done.

---

## Tech stack (what this actually is)

| Layer | Reality |
|---|---|
| Frontend | Static React 18 (UMD) + in-browser Babel. **No build step, no npm, no bundler.** Files: `*.jsx`, `styles.css`, `FORGE REI OS.html`. |
| Backend | Single Python file `connector.py` using **stdlib `http.server`** (ThreadingHTTPServer). No Flask/Django/FastAPI. |
| Package manager | **None for JS.** Python needs only `requests` (one dep, for the classifier). |
| Build command | **None.** Browser compiles JSX at runtime. |
| Start command | `python3 connector.py` (serves UI + `/api/*` on port 7799). |
| "Database" | Flat files: `marcus_state/*.jsonl` (append logs) + `marcus_state/config.json` + the Obsidian vault (git repo). `ruvector.db` is a separate vector store, not used by the connector. **No SQL DB.** |
| Agent/worker | `marcus_engine.py` poll loop in a daemon thread inside the connector process. |
| Schedulers | `style_agent` (daily voice learn) + `review_agent` (weekly). Triggered by timers that POST to the connector. |
| Hosting | Ubuntu droplet, **systemd** service `forge-reios`, **Tailscale** for private access, **ufw** firewall. |
| External APIs | GoHighLevel v2, Anthropic, Retell. |

---

## Checklist

### 🔴 Security (do before any public exposure)
- [x] **Secrets no longer downloadable over HTTP.** (Fixed: static server now allow-lists asset types and denies `deploy/`, `marcus_state/`, dotfiles, `.py`. Verified `404`.)
- [x] **SSH key + secret backup removed from the web-served dir on the box.** (Fixed.)
- [x] **`push.sh` excludes `deploy/keys`** so secrets are never shipped to the box again. (Fixed.)
- [x] **`.gitignore` added** so secrets/state never reach git. (Fixed.)
- [ ] **No application-level authentication.** Anyone who can reach `:7799` can send SMS, toggle auto-send, move deals, create voice agents. Today this is shielded **only** by Tailscale + ufw. **Add nginx Basic Auth (or an SSO proxy) before exposing publicly.** See DEPLOY doc.
- [ ] **Rotate the keys that were exposed.** Anthropic key (was in a screenshot) and Retell key (was pasted in chat) — rotate both. GHL key if `deploy/keys` was ever shared.
- [ ] **Move `deploy/keys/` out of the project folder on your Mac** (e.g. `~/.forge-secrets/`). It's the SSH key + a full secret backup sitting inside the app dir.
- [ ] Error responses return `str(e)` to the client (minor info-leak). Acceptable on a private tool; sanitize if public.

### 🟠 Compliance (texting real people)
- [x] **TCPA quiet-hours guard on auto-send** (default 8am–9pm ET; manual approvals never gated). (Fixed.)
- [x] DNC: inbound "stop/unsubscribe" auto-suppressed + tagged, never replied. (Already present.)
- [ ] The canned NRN referral reply has **no opt-out language** ("reply STOP to opt out"). Add it if you treat this as marketing SMS.
- [ ] `_is_soft_no()` uses broad substring matching ("no thanks", "not really") — can misfire and force the referral reply on an otherwise-warm lead. Review the phrase list.

### 🟢 24/7 / reliability (mostly done)
- [x] Auto-start on boot — systemd `enable`. Verified `enabled`.
- [x] Auto-restart on crash — `Restart=always`, `RestartSec=3`. Verified.
- [x] Survives terminal close — it's a service, not a shell job.
- [x] **Marcus toggle state persists across restart** (`marcus_state/config.json`). (Fixed — previously auto_send silently reverted on every restart.)
- [x] **Single-poller guard** via `FORGE_MARCUS=0` so a second instance (your Mac) won't double-text. (Fixed.) **Action: set `FORGE_MARCUS=0` on your Mac.**
- [x] **API cache is now bounded** (`_CACHE_MAX=200`) — no slow memory leak on a long-running process. (Fixed.)
- [ ] **Schedulers are NOT armed on the box.** The daily voice-learn (9pm) and weekly review (Mon 8am) are macOS LaunchAgents only. On the box they never fire. **Add systemd timers** (commands in DEPLOY doc).
- [ ] **No backups.** `marcus_state/` and the vault live only on the droplet. Enable DigitalOcean weekly snapshots ($1.20/mo) and/or `git push` the vault to a private remote.
- [ ] `handled.jsonl` grows unbounded and is fully re-read at boot. Fine for months; compact eventually.

### 🟢 Networking / TLS
- [x] Same-origin design — connector serves UI + API, so **no CORS needed** and the GHL/Anthropic tokens never reach the browser. Good architecture.
- [x] Firewall: deny-all inbound except SSH + tailnet. Verified.
- [ ] **No HTTPS.** Traffic is plain HTTP over the tailnet. Acceptable while private. For public access add nginx + Let's Encrypt (DEPLOY doc) — **and the auth item above first.**

### Rate limits
- [x] GHL 429/5xx backoff + retry in `ghl_get/post/put`. 45s response cache softens bursts.
- [ ] No rate limit on `/api/marcus/chat` / `/api/agents/chat` (Claude spend). Low risk while private.

---

## Required environment variables
All are present in your `ghl.env` today (nothing functionally missing). Documented in `.env.example`:
`GHL_API_KEY`, `GHL_LOCATION_ID`, `GHL_BASE_URL`, `GHL_API_VERSION`, `GHL_USER_EMAIL`,
`ANTHROPIC_API_KEY`, `RETELL_API_KEY`, `PRIMARY_MARKET`, `PRIMARY_ZIP`, `PRIMARY_COUNTY`,
`YAHJAIR_PHONE`. Runtime knobs: `FORGE_HOST`, `FORGE_PORT`, `FORGE_VAULT`, `FORGE_MARCUS`,
`FORGE_QUIET_HOURS`, `FORGE_TZ`, `FORGE_QUIET_START`, `FORGE_QUIET_END`.

## Red flags — do not ignore
1. **No login on the API.** Never expose `:7799` publicly without auth in front.
2. **Rotate exposed keys** (Anthropic, Retell).
3. **No backups** of state/vault — one droplet failure loses Marcus's memory + learned voice.
4. **Schedulers dead on the box** — "learning" and "weekly review" silently do nothing until timers are installed.
