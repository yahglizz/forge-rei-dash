#!/usr/bin/env python3
"""get_shopify_token.py — mint a durable Shopify Admin API token for Everaly.

Why this exists: this store has no legacy "custom app" flow, so there is no
`shpat_` token to reveal in the admin. Dev Dashboard apps expose only a Client ID,
a Secret, and a CI/CD automation token (`atkn_`) — none of which authenticate
against /admin/api. The supported path is a one-time OAuth authorization-code
exchange, which returns an OFFLINE access token that does not expire. That token
is what `SHOPIFY_ADMIN_TOKEN` wants.

The secret is read from an env var or a hidden prompt, never from argv (argv shows
up in shell history and process lists). The resulting token is written straight
into dropship.env and is never printed.

Stdlib only, to match dropship_env.py.

--- Before running, in the Dev Dashboard (dev.shopify.com) for your app ---

  1. Configuration -> Admin API access scopes, tick:
       read_products, read_inventory, read_orders,
       read_fulfillments, read_customers, read_locations
  2. Configuration -> Redirect URLs, add exactly:
       http://localhost:3456/callback
  3. Release a new version so the config is live.
  4. Settings -> copy the Client ID, and reveal the Secret.

--- Run ---

    cd forge-dropship/scripts
    python get_shopify_token.py --client-id <CLIENT_ID>

  It opens your browser, you click Install, and it writes SHOPIFY_ADMIN_TOKEN
  into ../config/dropship.env. Re-running overwrites the line.
"""
from __future__ import annotations

import argparse
import getpass
import http.server
import json
import os
import re
import secrets
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV_PATH = HERE.parent / "config" / "dropship.env"

PORT = 3456
REDIRECT_URI = f"http://localhost:{PORT}/callback"

SCOPES = ",".join([
    "read_products",
    "read_inventory",
    "read_orders",
    "read_fulfillments",
    "read_customers",
    "read_locations",
])

_result: dict = {}


def read_env(path: Path) -> dict:
    cfg = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg


def write_token(path: Path, token: str) -> None:
    """Replace the SHOPIFY_ADMIN_TOKEN line in place, preserving everything else."""
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    line = f"SHOPIFY_ADMIN_TOKEN={token}"
    if re.search(r"(?m)^[ \t]*SHOPIFY_ADMIN_TOKEN[ \t]*=.*$", original):
        updated = re.sub(r"(?m)^[ \t]*SHOPIFY_ADMIN_TOKEN[ \t]*=.*$", line, original, count=1)
    else:
        updated = original.rstrip("\n") + "\n" + line + "\n"
    path.write_text(updated, encoding="utf-8")


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        q = urllib.parse.parse_qs(parsed.query)
        _result["code"] = (q.get("code") or [""])[0]
        _result["state"] = (q.get("state") or [""])[0]
        _result["shop"] = (q.get("shop") or [""])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"<html><body style='font:16px system-ui;padding:40px'>"
            b"<h2>Done.</h2><p>Token captured. You can close this tab and go back to the terminal.</p>"
            b"</body></html>"
        )
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def log_message(self, *args):  # silence access logging
        return


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client-id", required=True, help="Dev Dashboard app Client ID")
    ap.add_argument("--shop", default="", help="myshopify domain (defaults to the one in dropship.env)")
    args = ap.parse_args()

    cfg = read_env(ENV_PATH)
    shop = args.shop or cfg.get("SHOPIFY_STORE_DOMAIN", "")
    if not shop:
        print("No shop domain. Pass --shop <store>.myshopify.com", file=sys.stderr)
        return 1
    if not shop.endswith(".myshopify.com"):
        print(f"Shop must be the myshopify domain, got {shop!r}", file=sys.stderr)
        return 1

    # Secret from env or hidden prompt. Never from argv.
    secret = os.environ.get("SHOPIFY_CLIENT_SECRET", "")
    if not secret:
        secret = getpass.getpass("Paste the app's Client Secret (input hidden): ").strip()
    if not secret:
        print("No client secret given.", file=sys.stderr)
        return 1

    state = secrets.token_urlsafe(24)
    auth_url = (
        f"https://{shop}/admin/oauth/authorize?"
        + urllib.parse.urlencode({
            "client_id": args.client_id,
            "scope": SCOPES,
            "redirect_uri": REDIRECT_URI,
            "state": state,
            # offline == a token that does not expire, which is what a daemon needs
            "grant_options[]": "",
        })
    )

    print(f"\nStore : {shop}")
    print(f"Scopes: {SCOPES}\n")
    print("Opening your browser. Approve the install there.")
    print(f"If it does not open, paste this in manually:\n\n{auth_url}\n")

    server = http.server.HTTPServer(("localhost", PORT), Handler)
    threading.Thread(target=webbrowser.open, args=(auth_url,), daemon=True).start()
    server.serve_forever()  # Handler shuts this down once the callback lands

    if not _result.get("code"):
        print("No authorization code came back.", file=sys.stderr)
        return 1
    if _result.get("state") != state:
        print("State mismatch — aborting rather than trusting that callback.", file=sys.stderr)
        return 1

    body = json.dumps({
        "client_id": args.client_id,
        "client_secret": secret,
        "code": _result["code"],
    }).encode()
    req = urllib.request.Request(
        f"https://{shop}/admin/oauth/access_token",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        print(f"Token exchange failed: HTTP {e.code} {e.read().decode()[:300]}", file=sys.stderr)
        return 1

    token = payload.get("access_token", "")
    if not token:
        print(f"No access_token in the response: {list(payload)}", file=sys.stderr)
        return 1

    write_token(ENV_PATH, token)
    print(f"\nWrote SHOPIFY_ADMIN_TOKEN to {ENV_PATH}")
    print(f"  length {len(token)}, prefix {token[:6]}…")
    print(f"  granted scopes: {payload.get('scope', '?')}")
    print("\nThe token was not printed. Copy the same line to the box at")
    print("  /opt/forge/forge-dropship/config/dropship.env")
    print("then: systemctl restart forge-reios")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
