"""Merge forge-slack/slash-commands.yaml into App A's manifest via the Slack manifest API.

Needs an App Configuration Token (api.slack.com/apps -> "Your App Configuration Tokens" ->
Generate) saved as SLACK_CONFIG_TOKEN=... in forge-slack/config/slack-config-token.env (gitignored).
Keeps every existing manifest field and command; only adds missing commands. Validates first.
Run: python3 forge-slack/add_slash_commands.py [--dry-run]. Never prints a token.
"""
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP_ID = "A0CGH3MHL15"                      # App A "claude" (Socket Mode)


def token():
    for line in (HERE / "config" / "slack-config-token.env").read_text().splitlines():
        if line.strip().startswith("SLACK_CONFIG_TOKEN="):
            return line.split("=", 1)[1].strip().strip("'\"")
    sys.exit("SLACK_CONFIG_TOKEN missing in forge-slack/config/slack-config-token.env")


def api(method, tok, **params):
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(f"https://slack.com/api/{method}", data=data,
                                 headers={"Authorization": f"Bearer {tok}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def wanted():
    text = (HERE / "slash-commands.yaml").read_text()
    pairs = re.findall(r'- command: (/[a-z]+)\n\s+description: "([^"]*)"', text)
    return [{"command": c, "description": d[:100], "should_escape": False} for c, d in pairs]


def main(dry):
    tok = token()
    out = api("apps.manifest.export", tok, app_id=APP_ID)
    if not out.get("ok"):
        sys.exit(f"export failed: {out.get('error')}")
    man = out["manifest"]
    cmds = man.setdefault("features", {}).setdefault("slash_commands", [])
    have = {c.get("command") for c in cmds}
    add = [c for c in wanted() if c["command"] not in have]
    cmds.extend(add)
    print(f"existing {len(have)}: {' '.join(sorted(have))}")
    print(f"adding {len(add)}: {' '.join(c['command'] for c in add)}")
    print("bot_events:", (man.get("settings", {}).get("event_subscriptions") or {}).get("bot_events"))
    print("socket_mode:", man.get("settings", {}).get("socket_mode_enabled"))
    v = api("apps.manifest.validate", tok, app_id=APP_ID, manifest=json.dumps(man))
    if not v.get("ok"):
        sys.exit(f"validate failed: {v.get('error')} {json.dumps(v.get('errors'))[:800]}")
    print("validate ok")
    if dry or not add:
        return
    u = api("apps.manifest.update", tok, app_id=APP_ID, manifest=json.dumps(man))
    if not u.get("ok"):
        sys.exit(f"update failed: {u.get('error')} {json.dumps(u.get('errors'))[:800]}")
    print("update ok; permissions_updated =", u.get("permissions_updated"))


if __name__ == "__main__":
    main("--dry-run" in sys.argv)
