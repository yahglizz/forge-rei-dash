# FORGE end-to-end wiring: Mac, n8n, agents, box

**Status:** draft, waiting on the owner's approval. Nothing here is built.
**Date:** 2026-11-01. The owner skipped the design questions, so scope comes from the handoff defaults (`HANDOFF-forge-agents-2026-11-02.md`, item 3) plus their new asks: the mobile dashboard from anywhere, full box access to the Mac, terse agent replies, and a Haiku 5.5 / Sonnet 5.5 model policy.

**Revision 2 (owner direction):** the owner chose full Mac access with agents able to act on the Mac while it is awake. That reverses the earlier "no shell" position. Their go on this spec is their acceptance of the risk stated under "Security position".

## Intent

From a phone, anywhere, the owner can ask any agent a question and get current information, or give it a task. The answer should be the same whether the message came in through Telegram, the n8n chat page, the dashboard or the mobile app. The Mac is a helpful extra, never a dependency.

## Goals

1. One agent turn path: every chat surface runs the agent from its own folder, under its own rules.
2. One brain: Mac and box notes stay within about 15 minutes of each other, and agents use them without being told to.
3. Mac reach: the box has full access to the Mac. Agents can read and do things there while it is awake, and report "Mac offline" cleanly when it is not.
4. Phone reach: the dashboard works off home Wi-Fi.
5. n8n stays the manager of schedules and events without spending executions on routine traffic.
6. Model policy: every Anthropic API agent runs Haiku 5.5 for simple work and Sonnet 5.5 for complex work, never Opus or Fable. Operator replies stay in caveman style to save output tokens.

## Non-goals

- New Telegram bots (owner decision).
- Agents writing brain notes. No route exists today. Add one when the owner asks for it.
- Agents sending anything outward. Propose, review, execute stays as it is.

## Anti-goals (failure even if it technically works)

- Parent, seller or lead text causing a Mac command to run without the owner's tap.
- Caveman style reaching a parent or seller. SMS drafts keep their human voice.
- Any dashboard route exposed through Funnel. The dashboard trusts loopback and holds children's records.
- A chat or Telegram message that goes dead because the Mac is asleep.
- An n8n polling schedule, or a normal dashboard message costing an execution.

## Current state (verified 2026-11-02 UTC)

| Surface | Path today | Runs from agent's folder? | Executions |
|---|---|---|---|
| n8n chat page | n8n → Funnel `/gateway` → `agent_runner.py` | Yes | 1 per message |
| `@Forgeagentsbot` DM | Same path, once a real message arrives | Yes, not yet proven: no Telegram run has reached n8n | 1 per message |
| `@Forgelabsxbot` DM and groups | Box polling → `telegram_agent.chat` | No | 0 |
| Dashboard and mobile | `/api/hub/chat`, `/api/agency/agents/chat` → `dash_live` | No | 0 |
| n8n schedules and pings | n8n → `/gateway/v1/run` | Yes | Per run |

Other facts:

- The dashboard is tailnet-only. The owner's iPhone rejoined the tailnet on 2026-11-02 and answers pings from the box. A dashboard load on the phone is not tested.
- Agents today: `FAST_MODEL` is Haiku 4.5 at 7 call sites, `SMART_MODEL` is Sonnet 5.5 at 65 (owner decision 2026-10-17, now replaced).
- The Mac has port 22 closed, and sleeps after 1 minute unless a caffeinate process holds it awake.
- Brain sync runs box to Mac only, every 6 hours.
- `agent_creed.py` lets a `vault/Skills` copy override an agent's creed, so the sync must never push `Skills/` from the Mac to the box.
- `brain-sync.sh` copies the daycare mirror with plain `cp`, which resets modified times. That is why 17 daycare notes look newer on every pass.
- The box has no n8n API key. `N8N_API_KEY__FORGE_N` and its base URL read empty when `master.env` is loaded. Hunt the other key sources first, otherwise the owner makes one. Only phase 5 needs it.

## The wiring

```
  PHONE, ANYWHERE
  Telegram agent bot ──► n8n Chat ───────────┐
  n8n chat page ───────► n8n Chat ───────────┤  /gateway/v1/chat
                                             ▼
  Telegram box bot ──────────────────► ┌───────────────────────┐
  Dashboard + mobile app ──(Tailscale)►│ BOX: agent_gateway    │ one turn path
                                       │  → agent_runner       │ agent's own folder
  n8n schedules + events ─/v1/run ───► │  → connector tools    │ existing gates
                                       └──┬─────────┬──────────┘
                                          │         │
                      box pings n8n on    │         │ Mac job queue
                      real events only    ▼         ▼
                                       n8n     ┌───────────────┐
                                               │ MAC WORKER    │ dials OUT to the box
                                               │ full shell    │ every 5 seconds
                                               │ tap gate      │ nothing listens on the Mac
                                               └───────────────┘
  BRAIN: Mac vault ◄── rsync, newest wins, every 15 min ──► box vault
```

### 1. Phone reach

Done on the owner's side: the iPhone is back on Tailscale. Enabling its VPN On Demand setting keeps it connected. The setting's exact name is not verified. Telegram needs no VPN, so it is the fallback.

Rejected: putting the dashboard on a public URL. It trusts loopback and holds children's records.

### 2. One agent turn path

Add `agent_gateway.chat_local(agent, message, origin)`, which calls the existing `submit()` directly, in-process, at 0 executions.

- `/api/hub/chat` and `/api/agency/agents/chat` (the two the mobile app uses) and the box Telegram bot call it.
- `origin="dash"` returns tap cards inline, so the phone keeps its ✅ cards. `origin="telegram"` sends them to the business chat as today.
- If the gateway refuses with 429 (box or agent busy), fall back to the old path, so a message never dies.
- `FORGE_CHAT_GATEWAY=1` turns this on. Unset returns the old path.
- `/api/office/chat` and the older Marcus and agents chat routes stay as they are. Convert them after the first surfaces prove stable.

Rejected: sending dashboard messages through n8n. Every message would cost an execution for no benefit.

### 3. One brain

Edit `~/Desktop/Agentic-OS/brain-sync.sh` and the launchd plist:

1. Interval 21600 → 900 seconds.
2. Daycare mirror: `cp` → `cp -p`, so modified times stop churning.
3. New Mac-to-box leg after the mirror: `rsync -az --update`, never `--delete`, excluding `.git`, `.obsidian`, `*.env`, `Skills/` and `Reports/eco-ad-created-*`.
4. Commit on the box after a push that changed something, so every change can be undone from git.
5. Skip the ChatGPT export unless the vault changed.

Newest wins. If the same note changes on both sides within 15 minutes, the older edit leaves the live copy and stays in git history. A scan of the Mac vault for common key formats found 0 files, so the push is not carrying those. It does not prove the notes hold no secrets of other formats.

The 38 fake `eco-ad-created` notes stay on the Mac, excluded from sync. Deleting them needs the owner's OK.

Agents already can read `/api/brain/search` and `/api/brain/recent` in chat. Add the brain to the `CAN` text in `dash_live.py` so they use it unprompted, and add those routes to scheduled tasks. Tasks triggered by parent or lead text stay narrow.

### 4. Mac link

**Change from the handoff:** the handoff proposed a narrow SSH forced command. The owner chose full access, so this is a real shell, and the Mac still dials out rather than opening SSH.

A small stdlib Python worker runs as a launchd agent under the owner's own macOS user, keeps running, and asks the box for work every 5 seconds over the tailnet. Reasons to dial out:

- Remote Login stays off and nothing listens on the Mac.
- The poll hits the box, so it costs 0 n8n executions.
- Each poll doubles as a heartbeat, so "Mac offline, last seen 3:42 PM" is exact.

| Side | Job |
|---|---|
| Box | `mac_link.py`, `GET /api/mac/next`, `POST /api/mac/result`, one Mac key stored as SHA-256 like the gateway keys, `mac_run` tool |
| Mac | `mac_worker.py` plus a launchd plist. Runs one command at a time from `/Volumes/AgentDrive/claude`, 120-second limit, 20,000-character output cap, `TMPDIR` on AgentDrive |

`mac_run` takes any shell command. What happens to a command depends on the turn:

| Turn | Command | Result |
|---|---|---|
| Clean owner chat | Normal command | Runs right away |
| Clean owner chat | Risky pattern | Tap card showing the exact command |
| Has read parent, seller, lead or email text (existing taint check) | Any command | Tap card showing the exact command |
| Workflow job or teammate consult | Any | Tool not offered |

The tap keeps full capability. Only the owner's tap runs a command that outside text could have shaped.

Risky patterns, checked on the box: `sudo`, `rm`, `git push`, `ssh`, `scp`, `rsync` to a remote, `curl` or `wget` sending data, `osascript`, `security`, `launchctl`, `vercel`, and any mention of `master.env`, `.ssh` or `.agent-keys`. This is a speed bump against model mistakes, and a shell can get around it. The project rule still stands: no send, spend, deploy or delete without the owner's yes.

Rules:

- Every command, its origin and its exit code goes to a log on both sides. Output is not logged.
- `mac_run` is offered only on Sonnet turns (see section 7).
- No heartbeat within 30 seconds means an immediate "Mac offline" answer. Jobs are not queued for later.
- AgentDrive not mounted is reported as such.
- Kill switches: `FORGE_MAC=0` on the box, or `launchctl bootout` on the Mac. `forge_ops` clock-out stops it too.

macOS will block the worker from Desktop, Documents and removable drives until the owner grants Python Full Disk Access in System Settings → Privacy & Security. Automation prompts may appear once per app. Both are not tested.

The Mac only answers while awake. Plugged in with `sudo pmset -c sleep 0` covers the lid-open case. A closed lid still sleeps, and that stays acceptable because nothing depends on the Mac.

**For MCPs from the phone:** use Claude Code Remote Control. `--remote-control` is in the installed CLI, not yet tested from the phone.

### 5. n8n as manager

No new schedules. n8n keeps schedules, the DM webhook and event pings.

Add a read-only `GET /api/system/n8n` using the existing `agency_workflows_io` client, so Orion and the dashboard can show recent runs, failures and the month's run count. REST reads run no workflow. The monthly count is counted from the execution list, so check it once against n8n's usage page.

Results from jobs n8n starts go back to n8n as they do today. Box-started turns log on the box, because reporting them to n8n would spend an execution each.

### 6. Wider reads

A rough name search of `connector.py` found no route naming Supabase, Vercel, Retell, DocuSign or Apify. That search undercounts, since Meta also shows 0 yet ad routes exist under other names. Build the real gap list first. Add a read route only when a real question goes unanswered, and don't add direct Supabase reads, since that database holds children's records. The owner picks from the list.

### 7. Models and reply style

**Models.** Set `FAST_MODEL` to `claude-haiku-5-5`. `SMART_MODEL` stays `claude-sonnet-5-5`. Add a hard allowlist of exactly those two IDs at `review_agent`'s request choke point, so no env var or call site can reach Opus or Fable. Extend `test_model_policy.py` to prove it.

| Work | Model |
|---|---|
| Scoring, triage, screening, parsing, summaries, follow-up bumps, plain chat lookups | Haiku 5.5, effort `low` |
| Seller and parent reply drafts, underwriting, plans, briefs, anything using `mac_run` | Sonnet 5.5, effort `low` |

Chat starts on Haiku with an `escalate` tool. When a request needs judgment, writing, planning or the Mac, Haiku calls it and the turn restarts on Sonnet from the original message. No keyword list, and a wasted Haiku start is cheap. Haiku 5.5 is $0.10 / $0.50 per million tokens against Sonnet 5.5's $2 / $10, so anything that holds up on Haiku costs one twentieth.

The 65 `SMART_MODEL` sites are audited one by one with this rule: Sonnet stays if the output reaches a parent, seller or client, or drives a money decision. Everything else moves to Haiku.

Haiku 5.5 is not a drop-in change. Thinking is on by default, thinking blocks can come first, and they count toward `max_tokens`. So:

- Add Haiku 5.5 to `_ADAPTIVE` in `review_agent.py`, so it gets adaptive thinking, explicit `low` effort and headroom. It is missing today.
- Pass thinking blocks back unchanged in every tool loop. Check each loop.
- Update `cost_tracker.py`, which prices all Haiku at $1 / $5, and add the higher rate above 100K prompt tokens.
- A grep of non-test code found no position-based content reads and no sampling parameters. Confirm with real calls.
- Update the old assertion in `test_model_policy.py` that Haiku runs with no thinking.

**Replies.** `caveman.py` already covers operator chat. Keep it at level `full`, confirm every chat path runs it, and tighten `_TEXT` if real replies still carry filler. Target: answer first, no opener, no sign-off. SMS drafts, scoring jobs and the creed stay out of it.

## Security position

**The risk the owner is accepting.** Agents read text written by outsiders: parents, sellers, leads and email senders. With a shell on the Mac, a successful injected message, or a stolen box or Mac key, reaches everything the owner's macOS user can reach. That includes `~/.agent-keys/master.env` with every business key, the root SSH key to the box, signed-in browser sessions and client files. Stolen keys could send texts, charge cards or spend ad money with no tap card anywhere in the path.

**What limits it.** Any turn that read outside text needs a tap. Workflow jobs have no Mac tool. Every command is logged. Two kill switches exist. The tap is the main wall; the pattern list is not a security boundary. A person tapping fast can still approve a bad command, so a card must show the exact command and read like a warning.

## Build order and estimates

| Phase | Work | Estimate |
|---|---|---|
| 0 | Owner: DM test. iPhone is done | 1 minute |
| 1 | Models and reply style | 60 minutes |
| 2 | Brain both ways | 45 minutes |
| 3 | One turn path, hub and mobile first, then box Telegram | 90 minutes |
| 4 | Mac link with `mac_run` | 75 minutes, plus owner's 2-minute Full Disk Access grant |
| 5 | Brain use unprompted, n8n status route, gap list | 45 minutes |

About 5 hours total (estimate). Each phase ships alone. Models go first because they cut cost from the first deploy and depend on nothing else. Avoid deploying between 02:00 and 02:05 UTC.

## Test plan

Every test reads run logs, not a reply that looks right.

| Phase | Pass means |
|---|---|
| 0 | A Telegram run appears on `tEvB32PbQepvq9gl` |
| 1 | Policy test blocks an Opus and a Fable ID set by env. Real calls on both tiers return text, with cost logged at the right price. A tool-loop chat works on Haiku 5.5. A planning question escalates to Sonnet; a lookup does not. Reply length measured before and after. Full test suite passes |
| 2 | A note made on each side appears on the other within 15 minutes. `Skills/` and the fake notes did not move. Daycare notes stop showing as newer. Box git shows the commit |
| 3 | Owner sends one real message from the phone. Job log shows the agent's folder files with sha256. Tap card shows on the phone. Forced 429 falls back to the old path. Full test suite passes |
| 4 | A harmless command runs from an owner chat on the phone. A risky pattern gives a card. A tainted turn gives a card with the exact command, and it runs only after a tap. Workflow job has no `mac_run`. Worker stopped gives "Mac offline" within 30 seconds. Both kill switches work. Both logs hold the command and no output |
| 5 | An agent uses the brain without being told to. Monthly count matches n8n's usage page |

No test sends a parent or seller SMS, taps a live business card, or writes to Meta. Mac tests use harmless commands in a scratch folder on AgentDrive.

## Rollback

| Change | How |
|---|---|
| Models | `git revert`. `FORGE_FAST_MODEL` can't reach beyond the allowlist, so revert is the path |
| Turn path | Unset `FORGE_CHAT_GATEWAY`, restart |
| Mac link | `launchctl bootout` the worker, or `FORGE_MAC=0`. Box answers "Mac offline" |
| Brain sync | Restore the plist and script from the Agentic-OS repo. Box notes revert through vault git |
| Box code | `git revert`, push |

## Left to the builder

- Exact card return format for `origin="dash"`.
- Where `mac_run` plugs into `dash_live.tools` and the tap card flow.
- Auth exemption for the two `/api/mac/*` routes.
- Which scheduled tasks get brain routes.
- The full call-site list for the Haiku and Sonnet audit.

## Calls made without the owner's input

- Mac worker dials out, instead of SSH.
- Commands shaped by outside text need a tap, and workflow jobs get no Mac tool. Full capability stays, through the tap.
- Risky pattern list on clean owner turns.
- Haiku starts every chat and escalates through a tool. `mac_run` is Sonnet only.
- Models ship first.
- Seller and parent drafts stay on Sonnet and out of caveman style.
- `Skills/` never moves from Mac to box.
- 5-second polling, 120-second command limit, 20,000-character output cap, 30-second offline window.
