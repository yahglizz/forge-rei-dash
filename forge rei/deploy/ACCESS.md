# FORGE REI OS — Access & Keys (KEEP PRIVATE)

⚠️ This folder holds live secrets (SSH key, API keys). Do NOT commit to git,
upload, or share. It is your master access record for the 24/7 server.

## The 24/7 server (DigitalOcean droplet)
- Name:        forge-reios
- Plan:        Basic $6/mo (1 vCPU / 1 GB), Ubuntu 24.04, region NYC1
- Public IP:   24.199.81.124   (SSH only)
- Tailscale IP: 100.87.232.91  (private — dashboard lives here)

## Open the dashboard (Mac or phone, must be on Tailscale)
    http://100.87.232.91:7799

## SSH into the server (from this Mac)
    ssh -i ~/.ssh/forge_droplet root@24.199.81.124
(backup copy of the key is in deploy/keys/forge_droplet)

## Edit the dashboard, then push changes live
Edit files on this Mac, then:
    cd "/Users/yg4st/forge rei dash/forge rei"
    ./deploy/push.sh root@24.199.81.124
JSX changes show on browser reload; Python changes apply on the auto-restart.
DO NOT edit files directly on the server — the next push overwrites them.

## Service control on the server (over SSH)
    systemctl status forge-reios      # is it running?
    systemctl restart forge-reios     # restart Marcus + dashboard
    tail -f /opt/forge/connector.err.log   # live logs

## Keys (also in deploy/keys/)
- forge_droplet / .pub  — SSH keypair for the server
- ghl.env.backup        — GHL token + ANTHROPIC + RETELL keys (the API keys)
  Live copy on the server: /opt/forge/marcus-wholesale-agent/config/ghl.env
  Live copy on this Mac:  ~/Desktop/marcus-wholesale-agent/config/ghl.env

## Tailscale
- Server + this Mac are both joined to your tailnet (account: yahjair@).
- Phone: install Tailscale, log in same account -> open the dashboard URL above.

## DigitalOcean API token
- Used once to create the droplet. Stored at ~/.config/forge_do_token
- Safe to delete/rotate now (deploys use SSH, not the token).

## Server layout (for reference)
    /opt/forge/forge-rei/                 dashboard (connector.py, *.jsx)
    /opt/forge/marcus-wholesale-agent/    ghl.env + classifier scripts
    /opt/forge/vault/                     brain (git repo, learned skills)
