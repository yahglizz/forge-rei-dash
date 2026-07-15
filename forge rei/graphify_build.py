"""graphify_build.py — build the Graphify knowledge graph ON THE BOX.

The graph `graphify_io.py` serves (`~/.graphify/global-graph.json`) was rebuilt
by a Mac-only launchd job, so on the Linux box it was a frozen snapshot (a
month stale). This rebuilds it natively from the live repo + vault, in the exact
JSON schema `graphify_io.py` reads, so Graphify stays fresh 24/7.

Scope vs. the old Mac tool (stdlib only, on purpose):
  - Python files → real `ast` extraction: file + top-level symbol nodes,
    `contains` (file→symbol), `method` (class→method), `imports` (file→file),
    `calls` (function→symbol).
  - .jsx/.js → regex top-level symbol extraction (no stdlib JS AST) + `contains`.
  - vault markdown → `document` nodes + `[[wikilink]]` `references` links.
  - community = one cluster per FILE (a file + its symbols share a community) so
    the force graph renders as clean per-file clusters.
Not byte-identical to the Mac tool's AST depth, but LIVE, same schema, and it
covers real code structure + doc links.

Runs as a daemon thread in the connector (box only, gated by the caller like the
other loops), rebuilding every FORGE_GRAPHIFY_EVERY_MIN minutes. Best-effort
throughout: a bad file never kills the build; a failed build leaves the last
good graph in place (atomic write).
"""
import ast
import json
import os
import re
import time
import threading
from pathlib import Path

GRAPH_PATH = Path(os.environ.get(
    "FORGE_GRAPHIFY_PATH", str(Path.home() / ".graphify" / "global-graph.json")))
REBUILD_EVERY = int(os.environ.get("FORGE_GRAPHIFY_EVERY_MIN", "30")) * 60

_SKIP_DIRS = {".git", ".obsidian", ".trash", "node_modules", "__pycache__",
              ".graphify", "uploads", "marcus_state", "deploy", ".vscode", "dist"}
_CODE_EXT = {".py", ".jsx", ".js"}

_lock = threading.Lock()
_status = {"builtAt": None, "nodes": 0, "links": 0, "error": None, "byRepo": {}}

_JSX_SYM = re.compile(
    r"^\s{0,4}(?:export\s+)?(?:function\s+([A-Za-z_$][\w$]*)"
    r"|const\s+([A-Za-z_$][\w$]*)\s*="
    r"|class\s+([A-Za-z_$][\w$]*))", re.M)
_WIKILINK = re.compile(r"\[\[([^\]|#]+)")


def _norm(s):
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")


def _roots():
    """(repo, root, kind) list — only for roots that actually exist on this host.
    kind: 'code' scans .py/.jsx/.js; 'docs' scans .md."""
    out = []
    code_root = os.environ.get("FORGE_GRAPHIFY_CODE_ROOT", "/opt/forge/repo")
    vault = os.environ.get("FORGE_VAULT", "/opt/forge/vault")
    if Path(code_root).is_dir():
        out.append(("forge-rei-os", Path(code_root), "code"))
    if Path(vault).is_dir():
        out.append(("agentic-os", Path(vault), "docs"))
    return out


def _walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            yield Path(dirpath) / fn


class _Builder:
    """Accumulates nodes/links across all roots for one build pass."""

    def __init__(self):
        self.nodes = []
        self.links = []
        self._node_ids = set()
        self._comm = {}          # file id -> community int
        self._comm_next = 0
        self.sym_index = {}      # norm(label) -> node id  (top-level py symbols, for calls)
        self.stem_to_fid = {}    # py module stem -> file node id (for imports)
        self.pending_calls = []  # (func_id, [called norm names])
        self.pending_imports = []  # (file_id, module stem)
        self.doc_stem_to_id = {}   # doc stem -> node id (for wikilinks)
        self.pending_wiki = []     # (doc_id, [target stems])

    def _community(self, file_id):
        c = self._comm.get(file_id)
        if c is None:
            c = self._comm_next
            self._comm[file_id] = c
            self._comm_next += 1
        return c

    def _add_node(self, node):
        if node["id"] in self._node_ids:
            return False
        self._node_ids.add(node["id"])
        self.nodes.append(node)
        return True

    def _add_link(self, source, target, relation, weight=1.0, src_file="", loc=""):
        if source == target:
            return
        self.links.append({
            "relation": relation, "confidence": "EXTRACTED",
            "source_file": src_file, "source_location": loc,
            "weight": weight, "confidence_score": 1.0,
            "source": source, "target": target,
        })

    # -- python -----------------------------------------------------------------
    def scan_py(self, repo, root, path):
        rel = path.relative_to(root).as_posix()
        floc = _norm(rel.rsplit(".", 1)[0])
        fid = f"{repo}::{floc}"
        comm = self._community(fid)
        self._add_node({
            "label": path.name, "file_type": "code", "source_file": rel,
            "source_location": "L1", "_origin": "ast", "community": comm,
            "norm_label": _norm(path.name), "repo": repo,
            "local_id": floc, "id": fid,
        })
        self.stem_to_fid[path.stem] = fid
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return  # file node stands even if the body won't parse
        for stmt in tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                sloc = f"{floc}_{_norm(stmt.name)}"
                sid = f"{repo}::{sloc}"
                self._add_node({
                    "label": stmt.name, "file_type": "code", "source_file": rel,
                    "source_location": f"L{stmt.lineno}", "_origin": "ast",
                    "community": comm, "norm_label": _norm(stmt.name),
                    "repo": repo, "local_id": sloc, "id": sid,
                })
                self._add_link(fid, sid, "contains", src_file=rel, loc=f"L{stmt.lineno}")
                self.sym_index.setdefault(_norm(stmt.name), sid)
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.pending_calls.append((sid, _called_names(stmt)))
                if isinstance(stmt, ast.ClassDef):
                    for m in stmt.body:
                        if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            mloc = f"{sloc}_{_norm(m.name)}"
                            mid = f"{repo}::{mloc}"
                            self._add_node({
                                "label": m.name, "file_type": "code", "source_file": rel,
                                "source_location": f"L{m.lineno}", "_origin": "ast",
                                "community": comm, "norm_label": _norm(m.name),
                                "repo": repo, "local_id": mloc, "id": mid,
                            })
                            self._add_link(sid, mid, "method", src_file=rel, loc=f"L{m.lineno}")
                            self.pending_calls.append((mid, _called_names(m)))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.pending_imports.append((fid, a.name.split(".")[0], rel))
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    self.pending_imports.append((fid, node.module.split(".")[0], rel))

    # -- jsx / js ---------------------------------------------------------------
    def scan_jsx(self, repo, root, path):
        rel = path.relative_to(root).as_posix()
        floc = _norm(rel.rsplit(".", 1)[0])
        fid = f"{repo}::{floc}"
        comm = self._community(fid)
        self._add_node({
            "label": path.name, "file_type": "code", "source_file": rel,
            "source_location": "L1", "_origin": "regex", "community": comm,
            "norm_label": _norm(path.name), "repo": repo, "local_id": floc, "id": fid,
        })
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return
        seen = set()
        for m in _JSX_SYM.finditer(text):
            name = m.group(1) or m.group(2) or m.group(3)
            if not name or name in seen:
                continue
            seen.add(name)
            line = text.count("\n", 0, m.start()) + 1
            sloc = f"{floc}_{_norm(name)}"
            sid = f"{repo}::{sloc}"
            if self._add_node({
                "label": name, "file_type": "code", "source_file": rel,
                "source_location": f"L{line}", "_origin": "regex", "community": comm,
                "norm_label": _norm(name), "repo": repo, "local_id": sloc, "id": sid,
            }):
                self._add_link(fid, sid, "contains", src_file=rel, loc=f"L{line}")

    # -- markdown docs ----------------------------------------------------------
    def scan_md(self, repo, root, path):
        rel = path.relative_to(root).as_posix()
        floc = _norm(rel.rsplit(".", 1)[0])
        fid = f"{repo}::{floc}"
        comm = self._community(fid)
        self._add_node({
            "label": path.name, "file_type": "document", "source_file": rel,
            "source_location": "L1", "_origin": "vault", "community": comm,
            "norm_label": _norm(path.name), "repo": repo, "local_id": floc, "id": fid,
        })
        self.doc_stem_to_id[path.stem.lower()] = fid
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return
        targets = {m.group(1).strip().lower() for m in _WIKILINK.finditer(text)}
        if targets:
            self.pending_wiki.append((fid, targets, rel))

    # -- resolve cross-file edges after every node exists -----------------------
    def resolve(self):
        for fid, stem, rel in self.pending_imports:
            tgt = self.stem_to_fid.get(stem)
            if tgt and tgt != fid:
                self._add_link(fid, tgt, "imports", src_file=rel)
        seen_calls = set()
        for src, names in self.pending_calls:
            for nm in names:
                tgt = self.sym_index.get(nm)
                if tgt and tgt != src and (src, tgt) not in seen_calls:
                    seen_calls.add((src, tgt))
                    self._add_link(src, tgt, "calls")
        for did, stems, rel in self.pending_wiki:
            for st in stems:
                tgt = self.doc_stem_to_id.get(st)
                if tgt and tgt != did:
                    self._add_link(did, tgt, "references", src_file=rel)


# Generic names resolve by bare name to the wrong symbol and become giant noise
# hubs (every `.get()`/`str()` collapses onto one node). Skip them for `calls`.
_CALL_STOP = {
    "get", "set", "str", "int", "len", "list", "dict", "print", "format", "join",
    "append", "keys", "items", "values", "strip", "lower", "upper", "split", "add",
    "pop", "sort", "sorted", "map", "filter", "range", "open", "read", "write",
    "float", "bool", "type", "super", "isinstance", "getattr", "setattr", "hasattr",
    "min", "max", "sum", "abs", "round", "enumerate", "zip", "any", "all", "next",
    "encode", "decode", "dumps", "loads", "replace", "find", "update", "extend",
    "startswith", "endswith", "group", "match", "search", "compile", "sub",
}


def _called_names(func_node):
    """Norm names a function body calls (Name id / Attribute attr), minus generic
    noise. Short (<4 char) and stoplisted names are dropped so `calls` stays signal."""
    out = set()
    for n in ast.walk(func_node):
        if isinstance(n, ast.Call):
            f = n.func
            nm = _norm(f.id) if isinstance(f, ast.Name) else (
                _norm(f.attr) if isinstance(f, ast.Attribute) else None)
            if nm and len(nm) >= 4 and nm not in _CALL_STOP:
                out.add(nm)
    return list(out)


def build_graph():
    """Scan all roots, build the graph dict, write it atomically. Returns status."""
    b = _Builder()
    for repo, root, kind in _roots():
        for path in _walk(root):
            try:
                if kind == "docs":
                    if path.suffix.lower() == ".md":
                        b.scan_md(repo, root, path)
                elif path.suffix.lower() == ".py":
                    b.scan_py(repo, root, path)
                elif path.suffix.lower() in (".jsx", ".js"):
                    b.scan_jsx(repo, root, path)
            except Exception:
                continue  # one bad file never kills the build
    b.resolve()
    by_repo = {}
    for n in b.nodes:
        r = n.get("repo") or "?"
        by_repo[r] = by_repo.get(r, 0) + 1
    graph = {
        "directed": True, "multigraph": False,
        "graph": {"generated_at": int(time.time()),
                  "generator": "graphify_build (box-native)"},
        "nodes": b.nodes, "links": b.links,
    }
    GRAPH_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = GRAPH_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(graph), encoding="utf-8")
    os.replace(tmp, GRAPH_PATH)
    with _lock:
        _status.update({"builtAt": int(time.time() * 1000), "nodes": len(b.nodes),
                        "links": len(b.links), "error": None, "byRepo": by_repo})
    return dict(_status)


def status():
    with _lock:
        return dict(_status)


def run_forever(interval=None):
    """Rebuild loop. Gate the CALLER on the box (FORGE_MARCUS) like the other loops."""
    every = interval or REBUILD_EVERY
    while True:
        try:
            build_graph()
        except Exception as e:  # noqa: BLE001
            with _lock:
                _status["error"] = str(e)
        try:
            import forge_heartbeat
            forge_heartbeat.beat("graphify", every, "Graphify graph builder",
                                 error=_status.get("error"))
        except Exception:
            pass
        time.sleep(every)


if __name__ == "__main__":
    print(json.dumps(build_graph(), indent=2))
