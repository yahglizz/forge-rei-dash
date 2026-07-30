#!/usr/bin/env python3
"""Proof that every dropship skill is UTILIZED, not just present on disk.

A skill file that nothing loads is worse than no skill: it reads like capability
in the repo and contributes nothing to a prompt. This asserts the wiring end to
end, with no Claude call and no network:

  1. every .md in forge-dropship/skills/ reaches a prompt through exactly one path
  2. no orphans — a new skill that nobody loads FAILS this test
  3. the creed loads via agent_creed ONLY (never _load_skills), so learn() can't see it
  4. learn() sees the playbook and nothing above it (constitution isolation)
  5. the operator chat path carries the same top skills as the brief path

Run: cd "forge rei" && python3 test_dropship_skills.py
"""
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "forge-dropship" / "skills"

# The four documented load paths. Every file must be claimed by exactly one.
CREED = "dropship-evidence-discipline.md"   # agent_creed.block("dropship")
CONTEXT = "dropship-context.md"             # dropship_context.context_block()
PLAYBOOK = "midas-playbook.md"              # MidasEngine._playbook_only()
# everything else                           # MidasEngine._load_skills()


def _marker(path):
    """A distinctive slice of the file's BODY (past the frontmatter) to search for.

    Content-based rather than filename-based on purpose: it proves the file's text
    actually landed in the prompt, not merely that something with that name loaded.
    """
    body = path.read_text(errors="ignore")
    if body.startswith("---"):                      # skip YAML frontmatter
        end = body.find("\n---", 3)
        if end != -1:
            body = body[end + 4:]
    lines = [ln.strip() for ln in body.splitlines()
             if len(ln.strip()) > 40 and not ln.strip().startswith(("#", ">", "|", "-", "*"))]
    if not lines:
        lines = [ln.strip() for ln in body.splitlines() if len(ln.strip()) > 40]
    assert lines, f"{path.name}: no line long enough to use as a marker"
    return lines[len(lines) // 2][:60]              # middle of the file, 60 chars


def main():
    assert SKILLS.is_dir(), f"skills dir missing: {SKILLS}"
    files = sorted(p for p in SKILLS.glob("*.md"))
    assert files, "no skill files found"

    import dropship_director
    import dropship_context
    import agent_creed

    eng = dropship_director.MidasEngine()   # connector.py:959 builds the live one the same way

    core = eng._load_skills() or ""                 # the daily brief's budget
    lanes = {ln: (eng._load_skills(ln) or "")       # core + that lane's deep SOPs
             for ln in dropship_director.MidasEngine.LANE_SKILLS}
    chat = dropship_director.top_skills_text() or ""  # operator chat — everything
    playbook = eng._playbook_only() or ""
    creed = agent_creed.block("dropship") or ""
    context = dropship_context.context_block() or ""
    context_source = dropship_context.load_context()
    loaded_context_path = dropship_context.context_path()
    # "utilized" = reaches a real prompt through ANY path
    loaded = "\n".join([core, chat] + list(lanes.values()))

    assert creed.strip(), "creed block is EMPTY — agent_creed.block('dropship') loaded nothing"
    assert loaded.strip(), "_load_skills() returned nothing"
    assert playbook.strip(), "_playbook_only() returned nothing"
    assert context.strip(), "context_block() returned nothing"

    # --- 1 + 2: every file reaches a prompt, through the path it's supposed to ---
    orphans, misrouted = [], []
    for p in files:
        mark = _marker(p)
        in_loaded = mark in loaded
        in_playbook = mark in playbook
        in_creed = mark in creed
        in_context = mark in context

        if p.name == CREED:
            if not in_creed:
                misrouted.append(f"{p.name}: NOT in agent_creed.block('dropship')")
            if in_loaded:
                misrouted.append(f"{p.name}: creed leaked into _load_skills() — "
                                 "learn() must never be able to see it")
        elif p.name == CONTEXT:
            # context_block() deliberately budgets this living business brief to
            # 3,500 chars. Its midpoint moves as operators append status updates,
            # so prove the canonical file is the source and its budgeted prefix
            # reaches the prompt instead of relying on the generic middle marker.
            expected_source = p.read_text(encoding="utf-8")
            if (loaded_context_path is None
                    or loaded_context_path.resolve() != p.resolve()):
                misrouted.append(f"{p.name}: dropship_context.context_path() is not canonical")
            if context_source != expected_source:
                misrouted.append(f"{p.name}: NOT loaded by dropship_context.load_context()")
            if expected_source.strip()[:3500] not in context:
                misrouted.append(f"{p.name}: NOT in dropship_context.context_block()")
        elif p.name == PLAYBOOK:
            if not in_playbook:
                misrouted.append(f"{p.name}: NOT in _playbook_only()")
        else:
            if not in_loaded:
                orphans.append(p.name)

    assert not orphans, (
        "ORPHAN SKILLS — on disk but never loaded into any prompt:\n  "
        + "\n  ".join(orphans)
        + "\nA skill must be declared in MidasEngine.TOP_SKILLS (always on), in one of "
          "LANE_SKILLS (that lane only), or in ON_DEMAND_SKILLS (operator chat). A file "
          "in none of them is dead weight that reads like capability."
    )
    assert not misrouted, "MISROUTED SKILLS:\n  " + "\n  ".join(misrouted)

    # --- 3: constitution isolation — learn() rewrites the playbook and nothing above it
    creed_mark = _marker(SKILLS / CREED)
    assert creed_mark not in playbook, "creed is inside _playbook_only() — learn() could rewrite it"
    for name in dropship_director.MidasEngine.TOP_SKILLS:
        f = SKILLS / name
        if f.is_file():
            assert _marker(f) not in playbook, f"top skill {name} is inside _playbook_only()"

    # --- 4: the brief prompt carries all four layers, and each lane adds its own SOPs
    brief_prompt = "\n".join((context, creed, core, playbook))
    for name in dropship_director.MidasEngine.TOP_SKILLS:
        f = SKILLS / name
        if f.is_file():
            assert _marker(f) in brief_prompt, f"always-on skill {name} missing from the brief"
    for ln, txt in lanes.items():
        for name in dropship_director.MidasEngine.LANE_SKILLS[ln]:
            f = SKILLS / name
            if f.is_file():
                assert _marker(f) in txt, f"{name} missing from lane '{ln}'"
    assert eng._load_skills("no-such-lane"), "unknown lane must degrade to core, not empty"

    # --- 5: operator chat path carries EVERY skill (they were silently dropped entirely)
    assert chat.strip(), "top_skills_text() empty — chat-Midas would run without skills"
    for p in files:
        if p.name in (CREED, CONTEXT, PLAYBOOK):
            continue
        assert _marker(p) in chat, f"{p.name} missing from top_skills_text() (chat path)"

    hub = Path(__file__).resolve().parent / "agents_hub.py"
    src = hub.read_text(errors="ignore")
    assert "top_skills_text" in src, \
        "agents_hub._director_chat does not inject top_skills_text — chat-Midas is skill-less"

    print(f"dropship skills self-check OK — {len(files)} skills, 0 orphans")
    print(f"  creed      {len(creed):>7,} chars  (agent_creed, invisible to learn())")
    print(f"  context    {len(context):>7,} chars  (injected first)")
    print(f"  playbook   {len(playbook):>7,} chars  (only thing learn() rewrites)")
    print(f"  core       {len(core):>7,} chars  (_load_skills, always on)")
    for ln, txt in sorted(lanes.items()):
        print(f"    lane {ln:<22} {len(txt):>7,} chars")
    print(f"  chat       {len(chat):>7,} chars  (top_skills_text — every skill)")
    print(f"  BRIEF prompt {len(brief_prompt):,} chars "
          f"(~{len(brief_prompt)//4:,} tok) — this one runs unattended on a timer")
    for p in files:
        print(f"    - {p.name}")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
