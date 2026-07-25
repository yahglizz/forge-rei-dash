"""agent_context.py — pull LIVE knowledge into an agent's Claude prompt at work time.

Until now the agents only loaded their own static playbook file. The brain (Obsidian vault:
past screening reports, closing-plays, seller-psychology notes, missed-lead lessons) and the
graphify code-graph were written to constantly but never READ back into the actual scoring /
screening / underwriting calls. So every lead was judged blind to everything the system had
already learned about similar situations.

This module closes that loop. Given a short query built from THIS lead (name, situation,
Scout's read), it searches the brain and returns a compact context block the agent pastes
into its prompt — so Marcus/Atlas reason WITH the accumulated playbook history, not just the
frozen rubric. graphify_context does the same for the code-graph (Dyson's world).

Both are best-effort and never raise: no brain / no results / any error → empty string, and
the agent proceeds exactly as before. Purely additive.
"""

_STOP = {"the", "a", "an", "and", "or", "to", "of", "for", "is", "in", "on", "it",
         "seller", "unknown", "none", "not", "mentioned", "property"}


def _keywords(*parts, limit=12):
    """Squeeze a few free-text fields into a short keyword query (dedup, drop stopwords)."""
    import re
    seen, out = set(), []
    for p in parts:
        for w in re.findall(r"[a-zA-Z][a-zA-Z0-9'-]{2,}", str(p or "").lower()):
            if w in _STOP or w in seen:
                continue
            seen.add(w)
            out.append(w)
            if len(out) >= limit:
                return " ".join(out)
    return " ".join(out)


def brain_context(query, k=4, max_chars=1600, header="RELEVANT NOTES FROM YOUR BRAIN"):
    """Search the vault for notes relevant to `query`; return a compact block or "".

    `query` may be raw text or already-built keywords — either works. The block is titled so
    the model knows it's retrieved history (past screenings, closing plays, lessons), not new
    instructions."""
    try:
        import brain_io
        q = (query or "").strip()
        if not q or not brain_io.available():
            return ""
        res = brain_io.search(q) or {}
        hits = res.get("results") or []
        if not hits:
            return ""
        lines = [f"=== {header} (retrieved history — apply what fits, ignore what doesn't) ==="]
        used = len(lines[0])
        for h in hits[:k]:
            title = (h.get("title") or h.get("path") or "note").strip()
            snip = " ".join(str(h.get("snippet") or "").split())[:280]
            line = f"- {title}: {snip}" if snip else f"- {title}"
            if used + len(line) > max_chars:
                break
            lines.append(line)
            used += len(line)
        return "\n".join(lines) if len(lines) > 1 else ""
    except Exception:
        return ""


def graphify_context(query, k=6):
    """Cross-project CODE-graph context (repos/files/symbols) for the build agents (Dyson).
    Empty string if graphify has nothing or errors."""
    try:
        import graphify_io
        return graphify_io.context_for((query or "").strip(), k=k) or ""
    except Exception:
        return ""


def seller_query(name="", *extra):
    """Convenience: build a lead query from a seller name + any situation text fields."""
    return _keywords(name, *extra)


# --- the WHOLESALE business brief --------------------------------------------
# Agency, daycare and dropship each read a business brief first (agency-context.md,
# daycare_context.py, dropship_context.py). Wholesale was the only side whose brief
# (forge-scout/skills/wholesale-context.md) existed but was never loaded. It lives
# here rather than in a fourth near-identical *_context.py module.
_WS_CACHE = {}      # str(path) -> (mtime, text)


def _wholesale_path():
    from pathlib import Path
    here = Path(__file__).resolve().parent
    for p in (here.parent / "forge-scout" / "skills" / "wholesale-context.md",
              Path.home() / "Desktop" / "forge-scout" / "skills" / "wholesale-context.md",
              Path("/opt/forge/forge-scout/skills/wholesale-context.md")):
        try:
            if p.is_file():
                return p
        except OSError:
            continue
    return None


def wholesale_context(limit=3000):
    """Prompt-ready wholesale business brief (mtime-cached). "" when absent, so callers
    can concatenate unconditionally."""
    try:
        p = _wholesale_path()
        if p is None:
            return ""
        mtime = p.stat().st_mtime
        cached = _WS_CACHE.get(str(p))
        if not cached or cached[0] != mtime:
            _WS_CACHE[str(p)] = (mtime, p.read_text(errors="ignore"))
        text = (_WS_CACHE[str(p)][1] or "").strip()
        if not text:
            return ""
        return ("\n\n=== WHOLESALE BUSINESS CONTEXT (read this FIRST — source of truth "
                "for the business; never contradict its market, buy-box, or process "
                "facts) ===\n" + text[:limit])
    except Exception:
        return ""
