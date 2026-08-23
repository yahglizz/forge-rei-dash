#!/usr/bin/env python3
"""Keep agents/ honest.

The cards under ../agents/ are documentation, so nothing breaks at runtime when
they drift -- which is exactly why they need a check. This asserts:

  1. every agent in agents_hub.AGENTS has a card, filed under its business
  2. every card names an engine file that exists
  3. every relative link in the cards and the README resolves
  4. every `forge-*/skills/*.md` a card cites is really on disk

    python3 test_agents_docs.py      # exit 1 on failure
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DOCS = os.path.join(ROOT, "agents")

BUSINESS_DIR = {
    "wholesale": "wholesale",
    "agency": "agency",
    "daycare": "daycare",
    "dropship": "dropship",
}


def _cards():
    out = {}
    for dirpath, _dirs, files in os.walk(DOCS):
        for f in files:
            if f.endswith(".md") and f != "README.md":
                out[f[:-3]] = os.path.join(dirpath, f)
    return out


def test_every_roster_agent_has_a_card():
    sys.path.insert(0, HERE)
    import agents_hub
    cards = _cards()
    for agent in agents_hub.AGENTS:
        aid, biz = agent["id"], agent["business"]
        assert aid in cards, f"agent {aid!r} is in the roster but has no card in agents/"
        expected = BUSINESS_DIR.get(biz)
        if expected:
            got = os.path.basename(os.path.dirname(cards[aid]))
            assert got == expected, f"{aid}: card filed under {got!r}, roster says {biz!r}"
    # Orion is deliberately absent from the roster but must still be documented.
    assert "orion" in cards, "Orion runs (connector.py:1039) but has no card"


def test_cited_paths_exist():
    """Every `forge rei/x.py`, `forge-*/...`, and relative .md link must resolve."""
    missing = []
    for name, path in sorted({**_cards(), "README": os.path.join(DOCS, "README.md")}.items()):
        text = open(path, encoding="utf-8").read()

        # Backticked repo paths. Glob/placeholder forms (`forge-*/skills/*.md`)
        # are deliberate wildcards in the prose, not claims about one file.
        for cited in set(re.findall(r"`(forge[ -][^`]+?\.(?:py|md))`", text)):
            if "*" in cited or "<" in cited:
                continue
            if not os.path.exists(os.path.join(ROOT, cited)):
                missing.append(f"{name}: {cited}")

        # Markdown links to sibling docs (skip anchors and urls).
        for link in set(re.findall(r"\]\((?!https?:)([^)#]+)\)", text)):
            target = os.path.normpath(os.path.join(os.path.dirname(path), link))
            if not os.path.exists(target):
                missing.append(f"{name}: link -> {link}")

    assert not missing, "unresolvable paths in agents/:\n  " + "\n  ".join(missing)


def test_skill_names_resolve():
    """A card citing `some-skill.md` must match a real file in a forge-*/skills dir."""
    on_disk = set()
    for entry in os.listdir(ROOT):
        skills = os.path.join(ROOT, entry, "skills")
        if entry.startswith("forge-") and os.path.isdir(skills):
            on_disk |= {f for f in os.listdir(skills) if f.endswith(".md")}

    unknown = []
    for name, path in sorted(_cards().items()):
        text = open(path, encoding="utf-8").read()
        for cited in set(re.findall(r"`([a-z0-9-]+\.md)`", text)):
            if cited not in on_disk:
                unknown.append(f"{name}: {cited}")
    assert not unknown, ("cards cite skill files that do not exist:\n  "
                         + "\n  ".join(unknown))


if __name__ == "__main__":
    test_every_roster_agent_has_a_card()
    test_cited_paths_exist()
    test_skill_names_resolve()
    n = len(_cards())
    print(f"OK — {n} agent cards, every roster agent covered, every cited path resolves")
