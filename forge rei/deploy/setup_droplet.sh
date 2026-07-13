#!/usr/bin/env bash
# setup_droplet.sh — turn a fresh Ubuntu droplet into the FORGE REI OS 24/7 box.
# Runs ON the droplet (as root). Idempotent: safe to re-run after a redeploy.
#
# Expects this layout already rsynced to the box (sibling dirs — the app finds
# ghl.env + the classifier via HERE.parent):
#   /opt/forge/forge-rei/                 (the dashboard: connector.py, *.jsx, ...)
#   /opt/forge/marcus-wholesale-agent/    (config/ghl.env + scripts/scan_missed_replies.py)
#   /opt/forge/vault/                     (the brain — git repo, learned skills)
set -euo pipefail

ROOT="/opt/forge"
APP="$ROOT/forge-rei"
VAULT="$ROOT/vault"
PORT="${FORGE_PORT:-7799}"
BUSINESS_TZ="${FORGE_TZ:-America/New_York}"
DAYCARE_FLAGS="/etc/default/forge-reios"

echo "==> swap (1G — the 1GB-RAM droplet has no buffer for the OOM killer)"
if [ ! -f /swapfile ]; then
  fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "==> apt deps"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-pip git ufw curl rsync
# scan_missed_replies.py (the real Marcus classifier) needs requests.
pip3 install --quiet --break-system-packages requests || pip3 install --quiet requests

echo "==> brain vault as a git repo (writes are git-committed)"
mkdir -p "$VAULT/Skills" "$VAULT/Log"
# SYSTEM-level git config (/etc/gitconfig) so the connector — which runs as root with NO
# HOME and over vault files owned by the rsync uid — can still commit. Without these, git
# throws "detected dubious ownership" + "Author identity unknown" and every learn write
# silently fails to commit (writes land, history doesn't). System config survives vault
# re-syncs and deploys (it is NOT inside the vault).
git config --system --get-all safe.directory 2>/dev/null | grep -qx "$VAULT" || git config --system --add safe.directory "$VAULT" 2>/dev/null || true
git config --system --get-all safe.directory 2>/dev/null | grep -qx "$ROOT"  || git config --system --add safe.directory "$ROOT"  2>/dev/null || true
git config --system user.name  "FORGE Brain" 2>/dev/null || true
git config --system user.email "brain@forge.local" 2>/dev/null || true
if [ ! -d "$VAULT/.git" ]; then
  git init -q "$VAULT"
  git -C "$VAULT" add -A && git -C "$VAULT" commit -q -m "brain: seed vault" || true
fi

echo "==> systemd service (24/7, auto-restart, starts on boot)"
# Cutover switches live outside the app and survive redeploys. The live Supabase
# hardening migrations, two-location role matrix, self-escalation guard, and
# cross-location participant checks passed before this write gate was enabled.
if [ ! -f "$DAYCARE_FLAGS" ]; then
  cat > "$DAYCARE_FLAGS" <<EOF
FORGE_DAYCARE_LIVE=1
FORGE_DAYCARE_WRITES=1
EOF
  chmod 600 "$DAYCARE_FLAGS"
else
  grep -q '^FORGE_DAYCARE_LIVE=' "$DAYCARE_FLAGS" \
    && sed -i 's/^FORGE_DAYCARE_LIVE=.*/FORGE_DAYCARE_LIVE=1/' "$DAYCARE_FLAGS" \
    || echo 'FORGE_DAYCARE_LIVE=1' >> "$DAYCARE_FLAGS"
  grep -q '^FORGE_DAYCARE_WRITES=' "$DAYCARE_FLAGS" \
    && sed -i 's/^FORGE_DAYCARE_WRITES=.*/FORGE_DAYCARE_WRITES=1/' "$DAYCARE_FLAGS" \
    || echo 'FORGE_DAYCARE_WRITES=1' >> "$DAYCARE_FLAGS"
fi
cat > /etc/systemd/system/forge-reios.service <<EOF
[Unit]
Description=FORGE REI OS connector (dashboard + Marcus 24/7)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP
EnvironmentFile=-$DAYCARE_FLAGS
Environment=FORGE_PORT=$PORT
Environment=FORGE_HOST=0.0.0.0
Environment=FORGE_VAULT=$VAULT
Environment=FORGE_MARCUS=1
Environment=FORGE_TZ=$BUSINESS_TZ
Environment=TZ=$BUSINESS_TZ
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 -u $APP/connector.py
Restart=always
RestartSec=3
StandardOutput=append:$ROOT/connector.out.log
StandardError=append:$ROOT/connector.err.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable forge-reios
systemctl restart forge-reios

echo "==> daily end-of-day learning sweep (8pm America/New_York -> brain)"
chmod +x "$APP/deploy/daily_learn.sh" 2>/dev/null || true
cat > /etc/systemd/system/forge-daily-learn.service <<EOF
[Unit]
Description=FORGE REI OS — daily end-of-day learning sweep (all agents -> brain)
After=forge-reios.service
[Service]
Type=oneshot
ExecStart=/bin/bash $APP/deploy/daily_learn.sh
EOF
cat > /etc/systemd/system/forge-daily-learn.timer <<EOF
[Unit]
Description=Run the FORGE daily learning sweep at 8pm Eastern (DST-aware)
[Timer]
OnCalendar=*-*-* 20:00:00 America/New_York
Persistent=true
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now forge-daily-learn.timer
# retire the old 02:00 UTC voice-only learn — folded into the 8pm full sweep
systemctl disable --now forge-learn.timer 2>/dev/null || true

echo "==> log rotation (connector + learn logs — keep the 1GB disk from filling)"
# copytruncate is MANDATORY: systemd holds the append fd (StandardOutput=append:), so a
# rename-then-create rotation would leave the service writing to the orphaned old inode and
# the new file would stay empty. copytruncate copies then truncates in place — the held fd
# keeps writing to the same (now-empty) file. Idempotent: re-running setup overwrites this.
apt-get install -y logrotate >/dev/null 2>&1 || true
cat > /etc/logrotate.d/forge-reios <<EOF
$ROOT/connector.out.log $ROOT/connector.err.log $APP/marcus_state/daily-learn.log {
    weekly
    rotate 4
    size 20M
    missingok
    notifempty
    compress
    delaycompress
    copytruncate
}
EOF
# validate the config now so a syntax slip is caught at deploy, not silently weeks later
logrotate -d /etc/logrotate.d/forge-reios >/dev/null 2>&1 || echo "   !! logrotate config check failed — review /etc/logrotate.d/forge-reios"

echo "==> firewall: SSH only on the public side; dashboard stays private to Tailscale"
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
# Tailscale interface gets full trust; :$PORT is reachable ONLY over the tailnet.
ufw allow in on tailscale0 || true
ufw --force enable

echo "==> Tailscale (private access from your Mac + phone, free)"
if ! command -v tailscale >/dev/null 2>&1; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi

echo "==> Tailscale Serve HTTPS (private tailnet reverse proxy)"
# --bg persists across reboots. connector.py trusts forwarded HTTPS only from
# this loopback proxy, never from a direct tailnet request to :$PORT.
if tailscale status >/dev/null 2>&1; then
  if timeout 20s tailscale serve --yes --bg --https=443 "http://127.0.0.1:$PORT"; then
    tailscale serve status || true
  else
    echo "   !! Tailscale Serve still needs the one-time tailnet approval shown above."
    echo "   !! Daycare authentication and writes remain HTTPS-only and fail closed until approved."
  fi
else
  echo "   (Tailscale is not authenticated yet — run 'tailscale up', then rerun setup)"
fi

echo
echo "============================================================"
echo " Service:  systemctl status forge-reios"
echo " Logs:     tail -f $ROOT/connector.err.log"
echo
echo " LAST STEP (interactive — run it yourself once if not connected):"
echo "   tailscale up"
echo " Then rerun setup and open: https://forge-reios.tail0a2dda.ts.net"
echo " Daycare reads + writes: enabled (Supabase security matrix passed)."
echo "============================================================"
