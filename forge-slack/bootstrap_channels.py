#!/usr/bin/env python3
"""Create the FORGE Slack channels (private), invite the owner, write ids to slack-channels.env.

Run: python3 forge-slack/bootstrap_channels.py [--dry-run]
Reads SLACK_BOT_TOKEN + SLACK_ALLOWED_USER_IDS from forge-slack/config/slack.env
(override dir with FORGE_SLACK_CONFIG_DIR). Writes SLACK_CHANNEL_<NAME>=<id> lines to
slack-channels.env in the same dir (gitignored, mode 600). Idempotent: existing channels are reused.
Needs bot scopes groups:write, groups:read (and channels:read for the lookup).
"""
import json, os, pathlib, sys, urllib.parse, urllib.request

CHANNELS = {"HQ": "forge-hq", "DAYCARE": "forge-daycare", "AGENCY": "forge-agency", "WHOLESALE": "forge-wholesale",
            # daycare rooms (slack_io.TOPICS): one channel per kind of enrollment news
            "DAYCARE_ALERTS": "daycare-alerts", "DAYCARE_TOURS": "daycare-tours", "DAYCARE_QUOTES": "daycare-quotes",
            "DAYCARE_STARTING": "daycare-starting", "DAYCARE_ENROLLED": "daycare-enrolled",
            # one channel per daycare site (slack_rooms.site_of). AMT = separate legal entity.
            "DAYCARE_ATOB_ONE": "daycare-921", "DAYCARE_ATOB_TWO": "daycare-2318", "DAYCARE_AMT": "amt-1923",
            # each ATOB site's specifics (slack_rooms.site_target); the shared rooms above get briefs only
            "DAYCARE_ATOB_ONE_TOURS": "921-tours", "DAYCARE_ATOB_ONE_QUOTES": "921-quotes",
            "DAYCARE_ATOB_ONE_ENROLLED": "921-enrolled",
            "DAYCARE_ATOB_TWO_TOURS": "2318-tours", "DAYCARE_ATOB_TWO_QUOTES": "2318-quotes",
            "DAYCARE_ATOB_TWO_ENROLLED": "2318-enrolled",
            # the agents' knowledge base (slack_knowledge)
            "KNOWLEDGE": "forge-knowledge"}
PURPOSE = {"DAYCARE_ATOB_ONE": "A Touch of Blessings, 921 N 18th St: this site's leads, parent replies, tours, start dates.",
           "DAYCARE_ATOB_TWO": "A Touch of Blessings 2, 2318 Cecil B. Moore: this site's leads, parent replies, tours, start dates.",
           "DAYCARE_AMT": "A Mother's Touch, 1923 Cecil B. Moore (separate entity): its alerts only. No ATOB data here.",
           "DAYCARE_ATOB_ONE_TOURS": "ATOB 921 N 18th: tours booked and tour reminders.",
           "DAYCARE_ATOB_ONE_QUOTES": "ATOB 921 N 18th: application / tuition quote sent.",
           "DAYCARE_ATOB_ONE_ENROLLED": "ATOB 921 N 18th: new enrollments and start dates to confirm.",
           "DAYCARE_ATOB_TWO_TOURS": "ATOB 2318 Cecil B. Moore: tours booked and tour reminders.",
           "DAYCARE_ATOB_TWO_QUOTES": "ATOB 2318 Cecil B. Moore: application / tuition quote sent.",
           "DAYCARE_ATOB_TWO_ENROLLED": "ATOB 2318 Cecil B. Moore: new enrollments and start dates to confirm.",
           "KNOWLEDGE": "FORGE knowledge base: business facts, site notes, parent FAQ, agent playbooks and lessons. "
                        "Agents read and add notes. No names, phones, emails or keys."}
# The shared rooms become all-sites brief chats (slack_briefs): their purpose is reset on every run.
PURPOSE.update({"DAYCARE_ALERTS": "All sites: new-lead brief at 8 AM and 6 PM. Single leads go to each site's channel.",
                "DAYCARE_TOURS": "All sites: tours brief at 8 AM and 6 PM. Details in #921-tours / #2318-tours.",
                "DAYCARE_QUOTES": "All sites: quotes brief at 8 AM and 6 PM. Details in #921-quotes / #2318-quotes.",
                "DAYCARE_STARTING": "All sites: start-dates brief at 8 AM and 6 PM. Details in each site's -enrolled channel.",
                "DAYCARE_ENROLLED": "All sites: enrolled brief at 8 AM and 6 PM. Details in #921-enrolled / #2318-enrolled.",
                "DAYCARE": "Daycare main chat: the per-site brief at 8 AM and 6 PM, plus anything urgent or not tied to a site."})
DIR = pathlib.Path(os.environ.get("FORGE_SLACK_CONFIG_DIR") or pathlib.Path(__file__).parent / "config")


def load(name):
    out = {}
    p = DIR / name
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def call(token, method, **params):
    req = urllib.request.Request(f"https://slack.com/api/{method}", data=urllib.parse.urlencode(params).encode(),
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def existing(token):
    found, cursor = {}, ""
    while True:
        r = call(token, "conversations.list", types="public_channel,private_channel", exclude_archived="true",
                 limit="200", **({"cursor": cursor} if cursor else {}))
        if not r.get("ok"):
            sys.exit(f"conversations.list failed: {r.get('error')} {r.get('needed', '')}")
        found.update({c["name"]: c["id"] for c in r["channels"]})
        cursor = (r.get("response_metadata") or {}).get("next_cursor", "")
        if not cursor:
            return found


def untrusted_reason(token, cid, bot_id, owners):
    """Why an EXISTING channel must not be reused as a FORGE channel (name-squatting guard), or ''.
    Reuse only a channel this bot created, that is private and unshared, whose members are the
    owner(s) plus the bot. Fails closed on any API error."""
    r = call(token, "conversations.info", channel=cid)
    c = r.get("channel") or {}
    if not r.get("ok"):
        return f"cannot inspect ({r.get('error')})"
    if not c.get("is_private") or c.get("is_im") or c.get("is_mpim"):
        return "not a private channel"
    if any(c.get(k) for k in ("is_shared", "is_ext_shared", "is_org_shared", "is_pending_ext_shared")):
        return "shared outside the workspace"
    if c.get("creator") != bot_id:
        return "was not created by the FORGE bot"
    m = call(token, "conversations.members", channel=cid, limit="200")
    if not m.get("ok") or (m.get("response_metadata") or {}).get("next_cursor"):
        return "member list unavailable or too long"
    strangers = [u for u in m.get("members", []) if u != bot_id and u not in owners]
    return f"{len(strangers)} unexpected member(s)" if strangers else ""


def main(dry):
    env = load("slack.env")
    token, owners = env.get("SLACK_BOT_TOKEN", ""), [u.strip() for u in env.get("SLACK_ALLOWED_USER_IDS", "").split(",") if u.strip()]
    if not token.startswith("xoxb-") or not owners:
        sys.exit("need SLACK_BOT_TOKEN and SLACK_ALLOWED_USER_IDS in slack.env")
    auth = call(token, "auth.test")
    if not auth.get("ok"):
        sys.exit(f"auth.test failed: {auth.get('error')}")
    bot_id = auth["user_id"]
    have, ids = existing(token), {}
    for key, name in CHANNELS.items():
        if name in have:
            why = untrusted_reason(token, have[name], bot_id, owners)
            if why:
                sys.exit(f"REFUSING to reuse existing #{name}: {why}. Rename or archive it, then re-run.")
            ids[key] = have[name]
            print(f"exists   #{name} (verified: private, created by the bot, owner-only)")
            if key in PURPOSE and not dry:
                call(token, "conversations.setPurpose", channel=ids[key], purpose=PURPOSE[key])
            continue
        if dry:
            print(f"would create private #{name}")
            continue
        r = call(token, "conversations.create", name=name, is_private="true")
        if not r.get("ok"):
            sys.exit(f"create #{name} failed: {r.get('error')} {r.get('needed', '')}")
        ids[key] = r["channel"]["id"]
        print(f"created  #{name}")
        if key in PURPOSE:
            call(token, "conversations.setPurpose", channel=ids[key], purpose=PURPOSE[key])
    if dry:
        return
    for key, cid in ids.items():
        r = call(token, "conversations.invite", channel=cid, users=",".join(owners))
        if not r.get("ok") and r.get("error") not in ("already_in_channel", "cant_invite_self"):
            print(f"  invite #{CHANNELS[key]}: {r.get('error')}")
    out = DIR / "slack-channels.env"
    out.write_text("# FORGE Slack channel ids (private). Gitignored.\n" + "".join(f"SLACK_CHANNEL_{k}={v}\n" for k, v in ids.items()))
    os.chmod(out, 0o600)
    print(f"wrote {out.name}: {', '.join(sorted(ids))}")


if __name__ == "__main__":
    main("--dry-run" in sys.argv)
