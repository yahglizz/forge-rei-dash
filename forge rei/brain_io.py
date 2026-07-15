"""brain_io.py — read/write the Agentic-OS Obsidian vault for FORGE REI OS.

The "brain" is the existing vault at ~/Desktop/Agentic-OS/vault (override with
FORGE_VAULT). We read/write the markdown directly so FORGE does not depend on the
brain's :7878 server being up; when it IS up we proxy its semantic search.

All paths are jailed inside the vault root.
"""

import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

VAULT = Path(os.environ.get(
    "FORGE_VAULT", str(Path.home() / "Desktop" / "Agentic-OS" / "vault"))).resolve()
BRAIN_URL = os.environ.get("BRAIN_URL", "http://localhost:7878")
SKIP_DIRS = {".obsidian", ".git", ".trash"}
AGENT_SKILLS = {
    "marcus_sms": ("marcus-playbook.md", "yahjair-voice.md", "wholesale-seller-texter.md"),
    "marcus_screening": ("marcus-screening-playbook.md", "marcus-lead-agent.md"),
    "scout": ("scout-playbook.md",),
    "dyson": ("dyson-playbook.md",),
    "eco": ("eco-playbook.md",),
    # Daycare — Solomon (head agent) reads/writes his operating playbook; the daycare
    # enrollment engine reads the same learned strategy the brain holds.
    "solomon": ("solomon-playbook.md",),
    # Dropship — Midas (head) + the specialist crew each keep a learned playbook.
    "midas": ("midas-playbook.md",),
    "hawk": ("hawk-playbook.md",),
    "blaze": ("blaze-playbook.md",),
    "otto": ("otto-playbook.md",),
}


def _safe(rel):
    """Resolve a vault-relative path, refusing traversal outside the vault."""
    p = (VAULT / rel).resolve()
    # Check path components, not characters: ``vault-backup`` is not inside
    # ``vault`` even though its string starts with the same prefix.
    try:
        p.relative_to(VAULT)
    except ValueError:
        raise ValueError("path escapes vault")
    return p


def available():
    return VAULT.is_dir()


def skill_status():
    """Observable proof that each live agent has at least one brain playbook to load."""
    consumers = {}
    newest = 0
    for agent, names in AGENT_SKILLS.items():
        files = []
        for name in names:
            p = VAULT / "Skills" / name
            if p.is_file():
                try:
                    mt = int(p.stat().st_mtime * 1000)
                    newest = max(newest, mt)
                    files.append({"path": f"Skills/{name}", "mtime": mt})
                except Exception:
                    files.append({"path": f"Skills/{name}", "mtime": None})
        consumers[agent] = {"ready": bool(files), "files": files}
    ready = sum(1 for c in consumers.values() if c["ready"])
    return {"live": available() and ready == len(consumers), "ready": ready,
            "total": len(consumers), "newestSkillMtime": newest,
            "consumers": consumers}


def tree():
    if not VAULT.is_dir():
        return {"vault": str(VAULT), "available": False, "folders": []}
    folders = []
    root_files = []
    for entry in sorted(VAULT.iterdir()):
        if entry.name in SKIP_DIRS or entry.name.startswith("."):
            continue
        if entry.is_dir():
            files = []
            for f in sorted(entry.rglob("*.md")):
                files.append({"path": str(f.relative_to(VAULT)), "title": f.stem})
            folders.append({"name": entry.name, "count": len(files), "files": files})
        elif entry.suffix == ".md":
            root_files.append({"path": entry.name, "title": entry.stem})
    if root_files:
        folders.insert(0, {"name": "/", "count": len(root_files), "files": root_files})
    return {"vault": str(VAULT), "available": True, "folders": folders}


def read_note(rel):
    if not rel:
        return {"error": "path required"}
    try:
        p = _safe(rel)
    except ValueError as e:
        return {"error": str(e)}
    if not p.is_file():
        return {"error": "not found", "path": rel}
    return {"path": rel, "title": p.stem, "content": p.read_text(errors="ignore")}


def _proxy_search(q, k=8):
    url = f"{BRAIN_URL}/api/brain/search?" + urllib.parse.urlencode({"q": q, "k": k})
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=3) as r:
        data = json.loads(r.read().decode())
    res = data.get("results", data) if isinstance(data, dict) else data
    out = []
    for x in res or []:
        out.append({"path": x.get("path"), "title": x.get("title") or x.get("path"),
                    "snippet": x.get("snippet", ""), "score": x.get("score")})
    return out


def search(q):
    q = (q or "").strip()
    if not q:
        return {"results": [], "mode": "empty"}
    # Prefer the brain's semantic search if its server is up.
    try:
        return {"results": _proxy_search(q), "mode": "semantic"}
    except Exception:
        pass
    # Fallback: substring scan over titles + bodies.
    ql = q.lower()
    hits = []
    for f in VAULT.rglob("*.md"):
        if any(part in SKIP_DIRS for part in f.parts):
            continue
        try:
            text = f.read_text(errors="ignore")
        except Exception:
            continue
        tl = text.lower()
        if ql in f.stem.lower() or ql in tl:
            idx = tl.find(ql)
            snip = text[max(0, idx - 40): idx + 80].replace("\n", " ") if idx >= 0 else text[:120]
            hits.append({"path": str(f.relative_to(VAULT)), "title": f.stem,
                         "snippet": snip.strip(), "score": None})
        if len(hits) >= 20:
            break
    return {"results": hits, "mode": "text"}


def recent(n=20):
    if not VAULT.is_dir():
        return {"items": []}
    files = []
    for f in VAULT.rglob("*.md"):
        if any(part in SKIP_DIRS for part in f.parts):
            continue
        try:
            files.append((f.stat().st_mtime, f))
        except Exception:
            continue
    files.sort(reverse=True)
    items = [{"path": str(f.relative_to(VAULT)), "title": f.stem,
              "mtime": int(mt * 1000)} for mt, f in files[:n]]
    return {"items": items}


def write_note(rel, content, reason="FORGE update"):
    """Write/overwrite a vault note and git-commit if the vault is a repo."""
    p = _safe(rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    committed = False
    if (VAULT / ".git").exists() or (VAULT.parent / ".git").exists():
        repo = VAULT if (VAULT / ".git").exists() else VAULT.parent
        try:
            subprocess.run(["git", "-C", str(repo), "add", str(p)],
                           check=True, capture_output=True, timeout=15)
            subprocess.run(["git", "-C", str(repo), "commit", "-m", f"brain: {reason}"],
                           check=True, capture_output=True, timeout=15)
            committed = True
        except Exception:
            committed = False
    return {"ok": True, "path": rel, "committed": committed}


def read_playbook():
    """The living Marcus playbook the weekly review maintains (or '' if none)."""
    p = VAULT / "Skills" / "marcus-playbook.md"
    if p.is_file():
        return p.read_text(errors="ignore")
    return ""


# ---------------------------------------------------------------------------
# Graph — notes as nodes, [[wikilinks]] as edges (powers the visual brain).
# ---------------------------------------------------------------------------
def graph(limit=90):
    if not VAULT.is_dir():
        return {"vault": str(VAULT), "nodes": [], "links": []}
    files = [f for f in VAULT.rglob("*.md")
             if not any(part in SKIP_DIRS for part in f.parts)]
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    files = files[:limit]
    stem_to_id, nodes, texts = {}, [], {}
    for f in files:
        rel = f.relative_to(VAULT)
        sid = str(rel)
        stem_to_id.setdefault(f.stem.lower(), sid)
        folder = rel.parts[0] if len(rel.parts) > 1 else "/"
        try:
            texts[sid] = f.read_text(errors="ignore")
        except Exception:
            texts[sid] = ""
        nodes.append({"id": sid, "title": f.stem, "folder": folder,
                      "mtime": int(f.stat().st_mtime * 1000)})
    node_ids = {n["id"] for n in nodes}
    links = []
    for sid, txt in texts.items():
        for m in re.findall(r"\[\[([^\]|]+)", txt):
            tgt = stem_to_id.get(m.strip().lower())
            if tgt and tgt != sid and tgt in node_ids:
                links.append({"source": sid, "target": tgt})
    deg = defaultdict(int)
    for l in links:
        deg[l["source"]] += 1
        deg[l["target"]] += 1
    for n in nodes:
        n["deg"] = deg.get(n["id"], 0)
    return {"vault": str(VAULT), "nodes": nodes, "links": links}


# ---------------------------------------------------------------------------
# Activity + undo — show (and reverse) what the brain learned/updated.
# ---------------------------------------------------------------------------
def _repo():
    if (VAULT / ".git").exists():
        return VAULT
    if (VAULT.parent / ".git").exists():
        return VAULT.parent
    return None


def activity(n=30):
    """Recent brain writes (git commits), newest first, so the UI can show what
    skills/notes were learned or updated and offer an undo."""
    repo = _repo()
    if not repo:
        return {"hasGit": False, "items": []}
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "log", f"-n{n}", "--name-only",
             "--format=%x01%H%x02%ct%x02%s"],
            capture_output=True, text=True, timeout=15).stdout
    except Exception as e:  # noqa: BLE001
        return {"hasGit": True, "items": [], "error": str(e)}
    items = []
    for block in out.split("\x01"):
        block = block.strip("\n")
        if not block:
            continue
        head, _, rest = block.partition("\n")
        parts = head.split("\x02")
        if len(parts) < 3:
            continue
        h, ct, subj = parts[0], parts[1], parts[2]
        files = [ln.strip() for ln in rest.splitlines() if ln.strip()]
        # Only surface brain writes + only the vault-side files.
        if not subj.startswith("brain:") and not any("Skills/" in f or "Log/" in f for f in files):
            continue
        vault_files = []
        for f in files:
            # normalize to vault-relative (repo may be the vault's parent)
            vf = f.split("vault/", 1)[1] if "vault/" in f else f
            if vf.endswith(".md"):
                vault_files.append(vf)
        if not vault_files:
            continue
        try:
            ts = int(ct) * 1000
        except ValueError:
            ts = 0
        items.append({
            "hash": h[:8],
            "when": ts,
            "reason": subj.replace("brain:", "").strip() or "update",
            "files": vault_files,
        })
    return {"hasGit": True, "items": items}


def undo_note(rel):
    """Restore a note to its previous committed version (or delete it if it was
    brand new). Returns what happened so the UI can confirm."""
    if not rel:
        return {"ok": False, "error": "path required"}
    try:
        p = _safe(rel)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    repo = _repo()
    if not repo:
        return {"ok": False, "error": "vault is not a git repo — cannot undo"}
    rp = str(p.relative_to(repo))
    try:
        hashes = subprocess.run(
            ["git", "-C", str(repo), "log", "-n2", "--format=%H", "--", rp],
            capture_output=True, text=True, timeout=15).stdout.split()
        if len(hashes) >= 2:
            subprocess.run(["git", "-C", str(repo), "checkout", hashes[1], "--", rp],
                           check=True, capture_output=True, timeout=15)
            subprocess.run(["git", "-C", str(repo), "add", rp],
                           check=True, capture_output=True, timeout=15)
            subprocess.run(["git", "-C", str(repo), "commit", "-m", f"brain: undo {rel}"],
                           check=True, capture_output=True, timeout=15)
            return {"ok": True, "restored": rel, "toCommit": hashes[1][:8]}
        if len(hashes) == 1:
            subprocess.run(["git", "-C", str(repo), "rm", rp],
                           check=True, capture_output=True, timeout=15)
            subprocess.run(["git", "-C", str(repo), "commit", "-m", f"brain: undo (remove) {rel}"],
                           check=True, capture_output=True, timeout=15)
            return {"ok": True, "removed": rel}
        return {"ok": False, "error": "no git history for this note"}
    except subprocess.CalledProcessError as e:
        return {"ok": False, "error": (e.stderr or b"").decode()[:200] or str(e)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
