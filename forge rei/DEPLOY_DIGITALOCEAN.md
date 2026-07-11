# Deploy FORGE REI OS to DigitalOcean

Two paths. **Path A (systemd) is what's live today and is recommended.** Path B
(Docker + nginx + HTTPS) is only if you want public internet access — and it has a
hard prerequisite: **add authentication first.**

Current live box: droplet `forge-reios`, public IP `24.199.81.124` (SSH only),
private dashboard `http://<tailscale-ip>:7799`.

---

## Path A — systemd + Tailscale (LIVE, recommended)

This is already running. These are the exact commands to (re)create or update it.

### A1. One-time: from your Mac, deploy everything
```bash
cd "/Users/yg4st/forge rei dash/forge rei"
./deploy/push.sh root@24.199.81.124
```
`push.sh` rsyncs the app (excluding `deploy/keys`, state, db), pushes `ghl.env` +
classifier + vault over SSH, then runs `deploy/setup_droplet.sh` on the box which:
installs `python3`/`requests`, writes the systemd unit, enables + restarts it, and
sets the firewall (deny inbound except SSH + tailnet).

### A2. One-time: finish Tailscale on the box
```bash
ssh -i ~/.ssh/forge_droplet root@24.199.81.124
tailscale up          # click the printed URL, log in
tailscale ip -4       # note the 100.x.x.x address
```
Open the dashboard from any device on your tailnet: `http://<that-ip>:7799`.

### A3. Arm the schedulers (NOT done by setup — do this once)
The daily voice-learn and weekly review do nothing on the box until you add timers.
Run on the box:
```bash
# --- daily voice learning, 02:00 box time ---
cat >/etc/systemd/system/forge-learn.service <<'EOF'
[Unit]
Description=FORGE daily voice learning
[Service]
Type=oneshot
ExecStart=/usr/bin/curl -s -X POST http://127.0.0.1:7799/api/style/run -H "Content-Type: application/json" -d '{"days":1}'
EOF
cat >/etc/systemd/system/forge-learn.timer <<'EOF'
[Unit]
Description=Run FORGE voice learning daily
[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true
[Install]
WantedBy=timers.target
EOF

# --- weekly review, Monday 08:00 box time ---
cat >/etc/systemd/system/forge-review.service <<'EOF'
[Unit]
Description=FORGE weekly review
[Service]
Type=oneshot
ExecStart=/usr/bin/curl -s -X POST http://127.0.0.1:7799/api/review/run -H "Content-Type: application/json" -d '{"days":7}'
EOF
cat >/etc/systemd/system/forge-review.timer <<'EOF'
[Unit]
Description=Run FORGE weekly review on Mondays
[Timer]
OnCalendar=Mon *-*-* 08:00:00
Persistent=true
[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now forge-learn.timer forge-review.timer
systemctl list-timers | grep forge      # verify
```

### A4. One-time: backups (don't skip)
- DigitalOcean console → your droplet → **Backups** → enable weekly ($1.20/mo), **or**
- Snapshot now: `doctl compute droplet-action snapshot 575784922 --snapshot-name forge-$(date +%F)`
- And/or push the vault to a private git remote so the brain survives a droplet loss.

### A5. Stop the Mac from double-texting
Only one machine may run Marcus. The box is it. On your Mac, run the connector
UI-only (no poller):
```bash
FORGE_MARCUS=0 ./start.sh
```
(Or just don't run the Mac connector while the box is live.)

### Updating later
Edit files on your Mac → `./deploy/push.sh root@24.199.81.124`. It re-rsyncs and
restarts the service. (Static `.jsx`/`.css` changes are live on browser reload;
Python changes apply on the restart push.sh performs.)

---

## Path B — Docker + nginx + Let's Encrypt (ONLY for public access)

> ⛔ **Prerequisite:** there is NO login in the app. If you expose it publicly,
> anyone can send SMS from your number and toggle your agents. **Do B3 (Basic Auth)
> in the same step you open ports 80/443. Not later.**

### B1. Droplet prep
```bash
ssh -i ~/.ssh/forge_droplet root@<ip>
apt-get update && apt-get install -y docker.io docker-compose-plugin nginx certbot python3-certbot-nginx
```

### B2. Bring up the app container
```bash
mkdir -p /opt/forge-docker/{secrets,state,vault}
# put your real ghl.env at /opt/forge-docker/secrets/ghl.env
# copy app code here, then:
cd /opt/forge-docker && docker compose up -d --build
curl localhost:7799/api/health     # expect {"ok": true ...}
```
(Compose binds to `127.0.0.1:7799` — not public yet. nginx will front it.)

### B3. nginx reverse proxy WITH Basic Auth (the gate)
```bash
apt-get install -y apache2-utils
htpasswd -c /etc/nginx/.htpasswd forge        # set a strong password

cat >/etc/nginx/sites-available/forge <<'EOF'
server {
    listen 80;
    server_name your.domain.com;
    location / {
        auth_basic "FORGE";
        auth_basic_user_file /etc/nginx/.htpasswd;
        proxy_pass http://127.0.0.1:7799;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
EOF
ln -sf /etc/nginx/sites-available/forge /etc/nginx/sites-enabled/forge
nginx -t && systemctl reload nginx
```

### B4. HTTPS via Let's Encrypt
```bash
# point your domain's A record at the droplet IP first, then:
certbot --nginx -d your.domain.com --redirect -m you@example.com --agree-tos -n
# certbot installs the cert + auto-renew timer. Verify:
systemctl status certbot.timer
```

### B5. Open the firewall for web (only after B3 + B4)
```bash
ufw allow 80/tcp && ufw allow 443/tcp && ufw reload
```

> Schedulers (A3) and backups (A4) still apply in the Docker path.
