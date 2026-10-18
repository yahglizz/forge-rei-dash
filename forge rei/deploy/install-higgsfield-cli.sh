#!/usr/bin/env bash
# install-higgsfield-cli.sh — install the official Higgsfield CLI (hf v1.2.2) on the FORGE box,
# SHA-256 pinned. The box has node but no npm, so we take the release tarball straight from
# GitHub (the same archive @higgsfield/cli's postinstall downloads, same pinned checksum).
#
#   On the box, as root:   bash install-higgsfield-cli.sh [--dry-run] [--prefix DIR] [--arch amd64|arm64]
#   --dry-run   print the plan + the env lines, touch nothing, no network
#
# Idempotent: an existing $PREFIX/hf that already reports v1.2.2 is left alone.
# Never logs in, never reads or prints a token. After it: add the env lines it prints to
# /etc/default/forge-reios, `systemctl restart forge-reios`, then run
# deploy/higgsfield-login-box.sh FROM THE MAC (browser OAuth through an SSH tunnel).
set -euo pipefail

VERSION="1.2.2"
SHA_AMD64="6a642f61f409a00d724de3079c1a7a25777eb1e49a2e0c3814e8a6ea3f49bb51"
SHA_ARM64="8f38897cccf31d517566a0a8b698e0955328d03b7755cac6ff4e050b9828ec79"
PREFIX="/opt/forge/bin"
DRY=0
ARCH=""

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --prefix) PREFIX="${2:?--prefix needs a dir}"; shift ;;
    --arch) ARCH="${2:?--arch needs amd64|arm64}"; shift ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

OS="$(uname -s)"
if [ "$OS" != "Linux" ] && [ "$DRY" -eq 0 ]; then
  echo "This installs the LINUX binary for the box (this machine is $OS). Use --dry-run to preview." >&2
  exit 2
fi
if [ -z "$ARCH" ]; then
  case "$(uname -m)" in
    x86_64|amd64) ARCH="amd64" ;;
    aarch64|arm64) ARCH="arm64" ;;
    *) echo "unsupported CPU $(uname -m) — only amd64/arm64 releases exist" >&2; exit 2 ;;
  esac
fi
case "$ARCH" in
  amd64) SHA="$SHA_AMD64" ;;
  arm64) SHA="$SHA_ARM64" ;;
  *) echo "--arch must be amd64 or arm64" >&2; exit 2 ;;
esac

TARBALL="hf_${VERSION}_linux_${ARCH}.tar.gz"
URL="https://github.com/higgsfield-ai/cli/releases/download/v${VERSION}/${TARBALL}"

env_lines() {
  cat <<EOF

── add to /etc/default/forge-reios (then: systemctl restart forge-reios) ──
HIGGSFIELD_CLI_BIN=${PREFIX}/hf
# The service runs with NO \$HOME (verified 2026-10-17: only PATH + USER). The CLI keeps its login
# in \$HOME/.config/higgsfield/ — pin it to root's home so the service finds the SSH login.
HIGGSFIELD_HOME=/root
# Optional caps (defaults shown): HIGGSFIELD_DAILY_CREDITS=100  HIGGSFIELD_AUTO_CREDITS=25
EOF
}

echo "Higgsfield CLI v${VERSION} → ${PREFIX}/hf (+ ${PREFIX}/higgsfield symlink)"
echo "  release : ${URL}"
echo "  sha256  : ${SHA}"

if [ -x "${PREFIX}/hf" ] && "${PREFIX}/hf" version 2>/dev/null | grep -q "higgsfield ${VERSION}"; then
  echo "Already installed: $("${PREFIX}/hf" version 2>/dev/null | head -1) — nothing to do."
  ln -sfn "${PREFIX}/hf" "${PREFIX}/higgsfield" 2>/dev/null || true
  env_lines
  exit 0
fi

if [ "$DRY" -eq 1 ]; then
  echo "DRY RUN — would: download with curl, verify sha256 (refuse on mismatch), extract,"
  echo "  install -m 755 to ${PREFIX}/hf, symlink ${PREFIX}/higgsfield, run 'hf version'."
  env_lines
  exit 0
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
curl -fsSL --retry 3 --connect-timeout 20 -o "$TMP/$TARBALL" "$URL"

if command -v sha256sum >/dev/null 2>&1; then
  GOT="$(sha256sum "$TMP/$TARBALL" | awk '{print $1}')"
else
  GOT="$(shasum -a 256 "$TMP/$TARBALL" | awk '{print $1}')"
fi
if [ "$GOT" != "$SHA" ]; then
  echo "SHA-256 MISMATCH — refusing to install." >&2
  echo "  expected $SHA" >&2
  echo "  got      $GOT" >&2
  exit 3
fi
echo "sha256 OK"

mkdir -p "$TMP/x"
tar -xzf "$TMP/$TARBALL" -C "$TMP/x"
BIN="$(find "$TMP/x" -type f -name hf | head -1)"
if [ -z "$BIN" ]; then
  echo "no 'hf' binary inside $TARBALL — refusing" >&2
  exit 4
fi
install -d -m 755 "$PREFIX"
install -m 755 "$BIN" "$PREFIX/hf"
ln -sfn "$PREFIX/hf" "$PREFIX/higgsfield"
"$PREFIX/hf" version
echo "Installed. Next: add the env lines below, restart, then from the Mac: bash deploy/higgsfield-login-box.sh"
env_lines
