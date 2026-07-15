"""graphify_io.py — read the global knowledge graph (~/.graphify/global-graph.json).

Used by:
  - connector.py  → /api/graphify/{graph,search,stats}  (Brain tab UI)
  - agents        → import graphify_io; graphify_io.search("ghl") for cross-project context

The graph is rebuilt on the box by `graphify_build.py` — a native stdlib builder
that runs as a connector daemon thread (box only) every FORGE_GRAPHIFY_EVERY_MIN
minutes, scanning the live repo (code) + vault (docs) into this same JSON schema.
(Historically it came from a Mac-only launchd job, which left the box stale.)
Reads here are cached for 60 s so rapid UI polls don't stat the file repeatedly.
"""
from __future__ import annotations
import json
import os
import time
import threading
from pathlib import Path
from typing import Optional

GRAPH_PATH = Path.home() / ".graphify" / "global-graph.json"

_lock   = threading.Lock()
_cache  = None          # {"nodes": [...], "links": [...], "loaded_at": float}
_TTL    = 60            # seconds


def _load() -> dict:
    global _cache
    with _lock:
        now = time.time()
        if _cache and now - _cache["loaded_at"] < _TTL:
            return _cache
        try:
            raw = json.loads(GRAPH_PATH.read_text())
        except Exception as exc:
            return {"nodes": [], "links": [], "error": str(exc)}
        _cache = {"nodes": raw.get("nodes", []),
                  "links": raw.get("links", []),
                  "loaded_at": now}
        return _cache


# ── public API ────────────────────────────────────────────────────────────────

def graph() -> dict:
    """Brain-compatible graph for the force-graph renderer.
    Nodes: {id, title, folder(=repo), file_type, community, source_file, deg}
    Links: {source, target, kind}
    """
    d = _load()
    if d.get("error"):
        return {"ok": False, "error": d["error"], "nodes": [], "links": [], "folders": []}

    nodes = [
        {
            "id":          n["id"],
            "title":       n.get("label", n["id"]),
            "folder":      n.get("repo", "unknown"),
            "file_type":   n.get("file_type", ""),
            "community":   n.get("community"),
            "source_file": n.get("source_file", ""),
            "repo":        n.get("repo", ""),
            "deg":         0,
        }
        for n in d["nodes"]
    ]
    links = [
        {
            "source": l["source"],
            "target": l["target"],
            "kind":   l.get("relation", "relates"),
            "weight": l.get("weight", 1.0),
        }
        for l in d["links"]
    ]

    deg: dict = {}
    for l in links:
        deg[l["source"]] = deg.get(l["source"], 0) + 1
        deg[l["target"]] = deg.get(l["target"], 0) + 1
    for n in nodes:
        n["deg"] = deg.get(n["id"], 0)

    repos = sorted({n["repo"] for n in nodes if n["repo"]})
    return {"ok": True, "nodes": nodes, "links": links, "folders": repos}


def search(query: str, *, repo: str | None = None, limit: int = 25) -> dict:
    """Search nodes by label / source_file substring. Optional repo filter."""
    d = _load()
    if d.get("error"):
        return {"ok": False, "error": d["error"], "hits": []}

    q = query.lower()
    results = []
    for n in d["nodes"]:
        if repo and n.get("repo") != repo:
            continue
        if q in (n.get("label") or "").lower() or q in (n.get("source_file") or "").lower():
            results.append({
                "id":          n["id"],
                "label":       n.get("label", n["id"]),
                "repo":        n.get("repo", ""),
                "file_type":   n.get("file_type", ""),
                "source_file": n.get("source_file", ""),
                "community":   n.get("community"),
            })
        if len(results) >= limit:
            break

    return {"ok": True, "hits": results}


def stats() -> dict:
    """Node/link/community counts by repo."""
    d = _load()
    if d.get("error"):
        return {"ok": False, "error": d["error"]}

    by_repo: dict = {}
    communities: set = set()
    for n in d["nodes"]:
        r = n.get("repo") or "?"
        by_repo[r] = by_repo.get(r, 0) + 1
        c = n.get("community")
        if c is not None:
            communities.add(c)

    return {
        "ok":          True,
        "nodes":       len(d["nodes"]),
        "links":       len(d["links"]),
        "communities": len(communities),
        "byRepo":      by_repo,
    }


def get_node(node_id: str) -> dict | None:
    """Return one node dict by id, or None."""
    d = _load()
    for n in d["nodes"]:
        if n["id"] == node_id:
            return n
    return None


def neighbors(node_id: str) -> list:
    """Return list of {node, relation, direction} dicts for a given node."""
    d = _load()
    node_map = {n["id"]: n for n in d["nodes"]}
    out = []
    for l in d["links"]:
        if l["source"] == node_id and l["target"] in node_map:
            out.append({"node": node_map[l["target"]], "relation": l.get("relation", ""), "dir": "→"})
        elif l["target"] == node_id and l["source"] in node_map:
            out.append({"node": node_map[l["source"]], "relation": l.get("relation", ""), "dir": "←"})
    return out


def context_for(query: str, k: int = 8) -> str:
    """Return a compact text block agents can paste into their prompt for cross-project context.
    Usage:  ctx = graphify_io.context_for("ghl integration")
    """
    res = search(query, limit=k)
    if not res.get("hits"):
        return ""
    lines = [f"# Graphify context for '{query}'"]
    for h in res["hits"]:
        lines.append(f"- [{h['repo']}] {h['label']}  ({h['file_type']}) — {h['source_file']}")
    return "\n".join(lines)
