#!/usr/bin/env bash
# backup_state.sh — nightly tarball of the box's ONLY copies of state (P0-6).
# Installed on the box as /usr/local/sbin/forge-backup-state.sh by setup_droplet.sh and run by
# forge-backup.timer (03:30 America/New_York). A copy outside the live tree on purpose: a bad
# code deploy can't break the backup. Keeps the 7 newest. Exits non-zero on any failure.
# ponytail: on-box only — the box dying takes these with it. Off-box copy / DO backups = owner call.
set -euo pipefail
umask 077

DEST="${FORGE_BACKUP_DIR:-/root/backups}"
KEEP="${FORGE_BACKUP_KEEP:-7}"
OUT="$DEST/forge-state-$(date +%F).tgz"
mkdir -p "$DEST" && chmod 700 "$DEST"

cd /
# Live files change under us (heartbeats every ~30 s, atomic tmp+rename writes). GNU tar exits 1
# for "file changed / removed as we read it" — that's a usable snapshot. 2+ is a real failure.
rc=0
tar czf "$OUT.tmp" --warning=no-file-changed --warning=no-file-removed \
  opt/forge/forge-rei/marcus_state opt/forge/forge-rei/uploads opt/forge/vault \
  opt/forge/*/config etc/default/forge-reios || rc=$?
[ "$rc" -le 1 ] || { echo "backup: tar failed rc=$rc" >&2; rm -f "$OUT.tmp"; exit 1; }

# Prove the archive reads back and actually holds the state before it replaces anything.
# (grep without -q: -q exits early, tar takes SIGPIPE, pipefail would call a good archive bad)
tar tzf "$OUT.tmp" | grep '^opt/forge/forge-rei/marcus_state/' >/dev/null \
  || { echo "backup: archive unreadable or missing marcus_state" >&2; rm -f "$OUT.tmp"; exit 1; }
chmod 600 "$OUT.tmp" && mv -f "$OUT.tmp" "$OUT"

# Rotation: date-stamped names sort chronologically; drop everything past the newest $KEEP.
ls -1 "$DEST"/forge-state-*.tgz | sort -r | tail -n +"$((KEEP + 1))" | xargs -r rm -f
echo "backup: $OUT $(du -h "$OUT" | cut -f1) ($(ls -1 "$DEST"/forge-state-*.tgz | wc -l) kept)"
