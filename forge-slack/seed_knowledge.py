#!/usr/bin/env python3
"""Seed Slack #forge-knowledge with the FORGE knowledge files (owner list, 2026-11-12).

  1. ATOB master info, sections 1-6 (identity, locations, programs, pricing, CCIS, licensing). The
     technical sections (app, website, CRM) stay out. Section 2 becomes one note per site
     (921, 2318 & 3, A Mother's Touch — the AMT note is labeled as a separate entity).
  2. Parent FAQ + reply rules: forge-daycare/skills/daycare-parent-reply.md
  3. Agent playbooks: <vault>/Skills/{solomon,marcus,dyson,orion}-playbook.md

Every chunk is scrubbed (phones, emails, key-shaped strings -> [removed]) before it leaves this Mac.
Run the preview first and READ it: playbooks are learned from real conversations.

  python3 forge-slack/seed_knowledge.py --dry-run     # writes the preview, posts nothing
  python3 forge-slack/seed_knowledge.py               # posts facts, site notes, parent FAQ
  add --with-playbooks to include the learned playbooks (only after reading them in the preview:
  they are learned from real conversations and may carry a name the scrub can't see)

Reads SLACK_BOT_TOKEN from slack.env and SLACK_CHANNEL_KNOWLEDGE from slack-channels.env in
FORGE_SLACK_CONFIG_DIR (default forge-slack/config). Remembers posted chunks in knowledge-seeded.json
there (hash only). Override sources with ATOB_MASTER_INFO and FORGE_VAULT.
"""
import hashlib
import json
import os
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
DIR = pathlib.Path(os.environ.get("FORGE_SLACK_CONFIG_DIR") or HERE / "config")
HOME = pathlib.Path.home()
MASTER = pathlib.Path(os.environ.get("ATOB_MASTER_INFO") or
                      HOME / "Desktop" / "A Touch of Blessings — Brand Kit" / "brand" / "ATOB-MASTER-INFO.md")
VAULT = pathlib.Path(os.environ.get("FORGE_VAULT") or HOME / "Desktop" / "Agentic-OS" / "vault")
PARENT = HERE.parent / "forge-daycare" / "skills" / "daycare-parent-reply.md"
PLAYBOOKS = ("solomon", "marcus", "dyson", "orion")
CHUNK = 2800
WITH_PLAYBOOKS = "--with-playbooks" in sys.argv
PREVIEW = pathlib.Path(os.environ.get("TMPDIR") or "/tmp") / "forge-knowledge-preview.md"

_SCRUB = (re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)"),
          re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
          re.compile(r"xox[abposr]-\S+|\bsk-[A-Za-z0-9_-]{16,}|ghp_\S+|github_pat_\S+|AKIA[0-9A-Z]{12,}|eyJ[\w-]{10,}\.\S+|"
                     r"\b[A-Fa-f0-9]{32,}\b|\b(?=[A-Za-z0-9+/_]*\d)[A-Za-z0-9+/_]{40,}\b"))


def scrub(text):
    for rx in _SCRUB:
        text = rx.sub("[removed]", text)
    text = re.sub(r"@(channel|here|everyone)\b", "", text)
    # Slack control sequences (<!here>, <@U…>, <!subteam^…>) only exist with a raw "<": escape it
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def sections(md, level):
    """[(heading, body)] split on headings of exactly this level."""
    out, head, buf = [], None, []
    for line in md.splitlines():
        m = re.match(r"^(#{%d})\s+(.*)" % level, line)
        if m:
            if head is not None or buf:
                out.append((head, "\n".join(buf).strip()))
            head, buf = m.group(2).strip(), []
        else:
            buf.append(line)
    out.append((head, "\n".join(buf).strip()))
    return out


def chunks(text):
    parts, cur = [], ""
    for para in text.split("\n\n"):
        while len(para) > CHUNK:
            parts.append(para[:CHUNK])
            para = para[CHUNK:]
        if len(cur) + len(para) + 2 > CHUNK:
            parts.append(cur.strip())
            cur = ""
        cur += para + "\n\n"
    if cur.strip():
        parts.append(cur.strip())
    return parts


def notes():
    """-> [(title, text)] in posting order. Missing files are reported, not invented."""
    out, missing = [], []
    if MASTER.exists():
        for head, body in sections(MASTER.read_text(), 2):
            m = re.match(r"(\d+)\.", head or "")
            if not m or not 1 <= int(m.group(1)) <= 6:
                continue
            if int(m.group(1)) == 2:          # one note per site
                for sub, sbody in sections(body, 3):
                    if not sub:
                        continue
                    label = ("A Mother's Touch (AMT, 1923) — SEPARATE legal entity, not ATOB"
                             if re.search(r"Mother|1923", sub, re.I) else sub)
                    out.append((f"Site note · {label}", sbody))
            else:
                out.append((f"ATOB facts · {head}", body))
    else:
        missing.append(str(MASTER))
    if PARENT.exists():
        out.append(("Parent FAQ + reply rules", PARENT.read_text()))
    else:
        missing.append(str(PARENT))
    for a in (PLAYBOOKS if WITH_PLAYBOOKS else ()):
        p = VAULT / "Skills" / f"{a}-playbook.md"
        if p.exists():
            out.append((f"{a.title()} playbook (learned)", p.read_text()))
        else:
            missing.append(str(p))
    return out, missing


def load(name):
    out, p = {}, DIR / name
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


def main(dry):
    items, missing = notes()
    posts = []
    for title, text in items:
        parts = chunks(scrub(text))
        for i, part in enumerate(parts):
            head = f"📚 *{title}*" + (f" ({i + 1}/{len(parts)})" if len(parts) > 1 else "")
            posts.append(f"{head}\n{part}")
    for m in missing:
        print(f"missing (skipped): {m}")
    if dry:
        PREVIEW.write_text("\n\n---\n\n".join(posts))
        os.chmod(PREVIEW, 0o600)
        print(f"preview: {len(posts)} messages from {len(items)} notes -> {PREVIEW}")
        return
    token = load("slack.env").get("SLACK_BOT_TOKEN", "")
    channel = load("slack-channels.env").get("SLACK_CHANNEL_KNOWLEDGE", "")
    if not token.startswith("xoxb-") or not channel:
        sys.exit("need SLACK_BOT_TOKEN (slack.env) and SLACK_CHANNEL_KNOWLEDGE (slack-channels.env)")
    seen_p = DIR / "knowledge-seeded.json"
    seen = set(json.loads(seen_p.read_text())) if seen_p.exists() else set()
    sent = 0
    for text in posts:
        h = hashlib.sha256(text.encode()).hexdigest()[:24]
        if h in seen:
            continue
        r = call(token, "chat.postMessage", channel=channel, text=text, unfurl_links="false", mrkdwn="true")
        if not r.get("ok"):
            sys.exit(f"post failed: {r.get('error')} (posted {sent} before this)")
        seen.add(h)
        seen_p.write_text(json.dumps(sorted(seen)))
        sent += 1
        time.sleep(1.2)                       # chat.postMessage: ~1 message a second per channel
    print(f"posted {sent} new messages ({len(posts) - sent} already there)")


if __name__ == "__main__":
    main("--dry-run" in sys.argv)
