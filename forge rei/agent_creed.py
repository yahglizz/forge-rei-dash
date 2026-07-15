"""agent_creed.py — the CREED: each business's evidence discipline, injected into every
agent's prompt ahead of its playbook.

Three businesses, three creeds — each written in the language of the work it governs:

    wholesale  → Scout, Marcus, Atlas   (sellers, threads, offers, comps)
    agency     → Dyson, Eco             (clients, ad metrics, scope, deploys)
    daycare    → Solomon                (families, ratios, licensing, billing)

Why this is a MODULE and not just another entry in each agent's ``_load_skills()``:
every agent's ``learn()`` does ``current = self._load_skills()`` → "output the FULL
UPDATED playbook" → overwrite. Anything reachable through ``_load_skills`` is therefore
something self-improvement will eventually swallow and rewrite. The creed is the one
thing that must NOT drift — so it is injected straight into the system prompt and is
never visible to ``learn()``. A self-rewriting constitution is no constitution.

Seed copies live in the agents' ``forge-*/skills/`` folders (shipped to the box by
deploy-pull.sh, which rsyncs every forge-* folder). The vault copy, if present, wins —
so the operator can edit the creed in Obsidian and every agent picks it up on the next
run via the mtime cache.

Read-only. Never truncated: the creed is short on purpose so it always fits.
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent

CREED_FILE = {
    "wholesale": "wholesale-evidence-discipline.md",
    "agency": "agency-evidence-discipline.md",
    "daycare": "daycare-evidence-discipline.md",
    "dropship": "dropship-evidence-discipline.md",
}

# Every sibling agent folder + the brain. The vault is searched LAST so its copy wins
# (see _load: later hits overwrite earlier ones).
_SEED_DIRS = [
    HERE.parent / "forge-scout" / "skills",
    HERE.parent / "forge-marcus" / "skills",
    HERE.parent / "forge-agency" / "skills",
    HERE.parent / "forge-solomon" / "skills",
    HERE.parent / "forge-daycare" / "skills",
    HERE.parent / "forge-dropship" / "skills",
]

_cache = {}   # business -> (mtime_sig, text)


def _dirs():
    dirs = list(_SEED_DIRS)
    try:
        import brain_io
        dirs.append(brain_io.VAULT / "Skills")   # vault last → operator's edit wins
    except Exception:
        pass
    return dirs


def _load(business):
    """The creed text for a business, mtime-cached. "" when the file is absent."""
    fname = CREED_FILE.get(business)
    if not fname:
        return ""
    hits = []
    for d in _dirs():
        try:
            p = d / fname
            if p.is_file():
                hits.append((p, p.stat().st_mtime))
        except Exception:
            continue
    if not hits:
        return ""
    sig = tuple((str(p), m) for p, m in hits)
    cached = _cache.get(business)
    if cached and cached[0] == sig:
        return cached[1]
    text = hits[-1][0].read_text(errors="ignore")   # last dir wins (vault > seed)
    _cache[business] = (sig, text)
    return text


def block(business):
    """The system-prompt fragment. Injected BEFORE the playbook and never truncated —
    when the creed and a learned playbook disagree, the creed wins, and it can only win
    if it is actually in the prompt in full."""
    text = _load(business).strip()
    if not text:
        return ""
    return ("\n\n=== YOUR CREED (evidence discipline — this OUTRANKS your playbook "
            "below; when they conflict, THIS wins) ===\n" + text)


def loaded(business):
    """True when the creed for this business is actually on disk — so a console can show
    what the agent is really running on instead of assuming it loaded."""
    return bool(_load(business).strip())


def status():
    return {b: loaded(b) for b in CREED_FILE}
