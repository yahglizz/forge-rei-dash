#!/usr/bin/env python3
"""Slack smoke test: auth -> post -> edit -> react -> delete. Stdlib only, never prints the token.

Run: python3 forge-slack/smoke_test.py
Reads forge-slack/config/slack.env (SLACK_BOT_TOKEN, SLACK_TEST_CHANNEL_ID).
Only touches the one message it posts, then deletes it.
"""
import json, pathlib, sys, time, urllib.parse, urllib.request

ENV = pathlib.Path(__file__).parent / "config" / "slack.env"


def load():
    out = {}
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip("'\"")
    return out


def call(token, method, **params):
    req = urllib.request.Request(
        f"https://slack.com/api/{method}",
        data=urllib.parse.urlencode(params).encode(),
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def step(name, res):
    ok = res.get("ok")
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  -> {res.get('error')} {res.get('needed', '')}"))
    if not ok:
        sys.exit(1)
    return res


def main():
    env = load()
    token, chan = env.get("SLACK_BOT_TOKEN", ""), env.get("SLACK_TEST_CHANNEL_ID", "")
    if not token.startswith("xoxb-"):
        sys.exit("SLACK_BOT_TOKEN missing or not xoxb- in slack.env")
    if not chan:
        sys.exit("SLACK_TEST_CHANNEL_ID missing in slack.env")
    who = step("auth.test (token valid)", call(token, "auth.test"))
    print(f"      workspace={who.get('team')} bot={who.get('user')}")
    m = step("chat.postMessage (add)", call(token, "chat.postMessage", channel=chan, text="FORGE smoke test: message 1 of 1"))
    ch, ts = m["channel"], m["ts"]
    time.sleep(1)
    step("chat.update (edit)", call(token, "chat.update", channel=ch, ts=ts, text="FORGE smoke test: edited"))
    step("reactions.add", call(token, "reactions.add", channel=ch, timestamp=ts, name="white_check_mark"))
    time.sleep(1)
    step("chat.delete (remove)", call(token, "chat.delete", channel=ch, ts=ts))
    print("ALL PASS: add, edit, react, remove work.")


if __name__ == "__main__":
    main()
