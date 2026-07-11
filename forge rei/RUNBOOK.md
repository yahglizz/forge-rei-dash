# FORGE REI OS — Runbook

Operating the live 24/7 box. Droplet `forge-reios`, SSH `24.199.81.124`,
dashboard `http://<tailscale-ip>:7799`.

SSH in:
```bash
ssh -i ~/.ssh/forge_droplet root@24.199.81.124
```

---

## Is it live? (30-second health check)
```bash
# from the box:
systemctl is-active forge-reios            # -> active
curl -s localhost:7799/api/health          # -> {"ok": true, "locationId": "...", ...}

# from your Mac/phone on Tailscale:
curl -s http://<tailscale-ip>:7799/api/health
```
`ok:true` means the GHL connection is good. Open the dashboard in a browser to
confirm the UI renders and KPIs load.

Check Marcus is polling:
```bash
curl -s localhost:7799/api/marcus/status | python3 -m json.tool
# look at: "online": true, "lastPoll" (recent epoch-ms), "lastError": null
```

---

## Restart
```bash
systemctl restart forge-reios              # graceful restart
systemctl stop forge-reios                 # stop
systemctl start forge-reios                # start
```
Toggle state (enabled / auto_send / auto_send_nrn) survives restarts — it's saved
in `marcus_state/config.json`.

---

## Logs
```bash
# live application output:
tail -f /opt/forge/connector.out.log
tail -f /opt/forge/connector.err.log

# systemd's own view (crashes, restarts, boot):
journalctl -u forge-reios -n 100 --no-pager
journalctl -u forge-reios -f               # follow

# scheduler runs (if armed):
journalctl -u forge-learn.service -n 20 --no-pager
journalctl -u forge-review.service -n 20 --no-pager
```
What to grep for: `lastError`, `429` (GHL rate limit), `AI draft failed` (Anthropic),
`Quiet hours — held` (auto-reply deferred to morning).

---

## Update the code
From your **Mac** (not the box):
```bash
cd "/Users/yg4st/forge rei dash/forge rei"
# edit files...
./deploy/push.sh root@24.199.81.124        # rsync + restart
```
Then verify with the health check above. Front-end-only edits (`.jsx`/`.css`) show
on a browser hard-reload; backend edits take effect on the restart push.sh runs.

---

## Common operations

**Pause Marcus (stop all seller replies):** dashboard → Marcus toggle off, or:
```bash
curl -s -X POST localhost:7799/api/marcus/toggle -H "Content-Type: application/json" -d '{"enabled":false}'
```

**Turn full auto-send on/off** (NRN referral auto-send is separate, defaults on):
```bash
curl -s -X POST localhost:7799/api/marcus/toggle -H "Content-Type: application/json" -d '{"autoSend":true}'
```

**Force a poll now:**
```bash
curl -s -X POST localhost:7799/api/marcus/poll
```

**Widen/disable quiet hours** (edit the systemd unit env, then restart):
```bash
systemctl edit forge-reios     # add: Environment=FORGE_QUIET_HOURS=0
systemctl restart forge-reios
```

---

## Troubleshooting

| Symptom | Check | Fix |
|---|---|---|
| Dashboard won't load | `systemctl is-active forge-reios` | `systemctl restart forge-reios`; read `connector.err.log` |
| `health` returns `ok:false` | GHL key present? | `grep GHL_API_KEY /opt/forge/marcus-wholesale-agent/config/ghl.env`; re-push from Mac |
| Sellers texted twice | two pollers running | ensure Mac runs with `FORGE_MARCUS=0`; only the box polls |
| Replies sound robotic | `marcus/status` → `draftMode` | if `templates`, the Anthropic key isn't loading — check `ghl.env` |
| Nothing auto-sent at night | expected | quiet hours hold auto-replies as pending; approve in the morning or set `FORGE_QUIET_HOURS=0` |
| Learning/review never runs | `systemctl list-timers \| grep forge` | arm the timers (DEPLOY_DIGITALOCEAN.md §A3) |
| Box rebooted | `systemctl is-enabled forge-reios` | should be `enabled` (auto-starts); run `tailscale up` is persistent across reboots |

---

## Disaster recovery
State that matters: `/opt/forge/forge-rei/marcus_state/` (Marcus memory) and
`/opt/forge/vault/` (brain + learned voice).
- Restore a droplet from a DigitalOcean snapshot (console → Backups/Snapshots).
- Or rebuild: create Ubuntu droplet → add SSH key → `./deploy/push.sh root@<new-ip>` →
  `tailscale up` → re-arm timers (§A3). Then restore `marcus_state/` + vault from backup.
