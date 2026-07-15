"""agency_deploy.py — GitHub → Vercel deploy connector (Lane E, M4).

Operator decision: Dyson commits changes to GitHub; Vercel auto-deploys via its
git integration. No direct Vercel API call is needed — the GitHub push triggers it.

Frozen public API (§4 M4):
  ship(client, draft) -> {ok, commitUrl, prUrl?, detail}
  status(client_id=None) -> {connected, repo, lastDeploy}

Credential guard: GITHUB_TOKEN missing → returns {ok: False, detail: ...}.
NEVER throws. NEVER prints secret values.
"""
import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Env helpers
# ---------------------------------------------------------------------------
_GH_API = "https://api.github.com"
_UA = "ForgeREI-Deploy/1.0"


def _token() -> Optional[str]:
    return os.environ.get("GITHUB_TOKEN") or None


def _deploy_map() -> dict:
    raw = os.environ.get("GITHUB_DEPLOY_MAP", "")
    if not raw:
        return {}
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def _client_id(client) -> str:
    if isinstance(client, dict):
        return client.get("id") or ""
    return str(client)


def resolve_repo(client) -> str:
    """Find the 'owner/repo' for a client. Order: the client's own workspace
    record (agency_io) → the GITHUB_DEPLOY_MAP env fallback. Returns '' if none."""
    # 1. inline on the passed client dict
    if isinstance(client, dict):
        ws = client.get("workspace") or {}
        if isinstance(ws, dict) and ws.get("repo"):
            return str(ws["repo"]).strip()
    cid = _client_id(client)
    # 2. look it up in the client book
    if cid:
        try:
            import agency_io  # deferred to avoid import cycle
            ws = agency_io.get_workspace(cid) or {}
            if ws.get("repo"):
                return str(ws["repo"]).strip()
        except Exception:
            pass
    # 3. env fallback
    return _deploy_map().get(cid, "")


# ---------------------------------------------------------------------------
# GitHub REST (urllib — mirrors GHLClient._req style)
# ---------------------------------------------------------------------------
def _gh_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
        "User-Agent": _UA,
    }


def _http_error_detail(e, limit=500):
    try:
        raw = e.read().decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        raw = ""
    detail = raw.strip()
    try:
        parsed = json.loads(detail)
        if isinstance(parsed, dict):
            detail = (parsed.get("message") or parsed.get("error_description")
                      or parsed.get("error") or parsed.get("detail") or detail)
            if isinstance(detail, (dict, list)):
                detail = json.dumps(detail)
    except Exception:  # noqa: BLE001
        pass
    return str(detail or getattr(e, "reason", "") or "")[:limit]


def _gh_req(method: str, path: str, token: str, body=None) -> dict:
    url = f"{_GH_API}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=_gh_headers(token), method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GitHub {e.code}: {_http_error_detail(e)}")


def _gh_get(path: str, token: str) -> dict:
    return _gh_req("GET", path, token)


def _gh_post(path: str, token: str, body: dict) -> dict:
    return _gh_req("POST", path, token, body)


def _gh_put(path: str, token: str, body: dict) -> dict:
    return _gh_req("PUT", path, token, body)


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------
def _default_branch(owner: str, repo: str, token: str) -> str:
    try:
        info = _gh_get(f"/repos/{owner}/{repo}", token)
        return info.get("default_branch") or "main"
    except Exception:
        return "main"


def _branch_sha(owner: str, repo: str, branch: str, token: str) -> str:
    ref = _gh_get(f"/repos/{owner}/{repo}/git/ref/heads/{branch}", token)
    return ref["object"]["sha"]


def _create_branch(owner: str, repo: str, branch: str, from_sha: str, token: str) -> None:
    _gh_post(f"/repos/{owner}/{repo}/git/refs", token,
             {"ref": f"refs/heads/{branch}", "sha": from_sha})


def _commit_files(owner: str, repo: str, branch: str,
                  files: list, message: str, token: str) -> str:
    """Commit one or more files onto branch; returns the commit HTML URL."""
    # For each file we upsert via the contents API (handles create + update).
    last_url = ""
    for f in files:
        path = f.get("path", "")
        content_bytes = (f.get("content") or "").encode("utf-8")
        content_b64 = base64.b64encode(content_bytes).decode()
        body: dict = {
            "message": message,
            "content": content_b64,
            "branch": branch,
        }
        # If the file already exists we need its current SHA to overwrite.
        try:
            existing = _gh_get(f"/repos/{owner}/{repo}/contents/{path}"
                               + f"?ref={urllib.parse.quote(branch)}", token)
            if isinstance(existing, dict) and existing.get("sha"):
                body["sha"] = existing["sha"]
        except Exception:
            pass  # new file — no sha needed
        result = _gh_put(f"/repos/{owner}/{repo}/contents/{path}", token, body)
        commit = result.get("commit") or {}
        last_url = commit.get("html_url") or last_url
    return last_url


def _open_pr(owner: str, repo: str, head: str, base: str,
             title: str, body_text: str, token: str) -> str:
    try:
        pr = _gh_post(f"/repos/{owner}/{repo}/pulls", token, {
            "title": title,
            "head": head,
            "base": base,
            "body": body_text,
        })
        return pr.get("html_url") or ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Brain + bus (mirroring agency_agents.py pattern)
# ---------------------------------------------------------------------------
def _brain_note(client_id: str, repo: str, commit_url: str, pr_url: str) -> None:
    try:
        import brain_io  # type: ignore
        stamp = time.strftime("%Y-%m-%d %H:%M")
        text = (f"---\nagent: dyson\nupdated: {stamp}\nsource: deploy\n---\n\n"
                f"Deploy triggered for client `{client_id}` → `{repo}`.\n"
                f"Commit: {commit_url}\n"
                + (f"PR: {pr_url}\n" if pr_url else "")
                + "\nVercel auto-deploys from the GitHub push.\n")
        brain_io.write_note(f"Deploys/{client_id}-{stamp[:10]}.md", text,
                            reason=f"Dyson deploy {client_id} {stamp}")
    except Exception:
        pass


def _bus_msg(client_id: str, repo: str, commit_url: str, pr_url: str) -> None:
    try:
        import agent_bus  # type: ignore
        detail = f"shipped to {repo}"
        if pr_url:
            detail += " (PR opened for operator merge)"
        agent_bus.send("dyson", "all", "status",
                       f"Dyson deployed {client_id}: {detail}",
                       {"clientId": client_id, "repo": repo,
                        "commitUrl": commit_url, "prUrl": pr_url})
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def ship(client, draft) -> dict:
    """Commit draft changes to GitHub and open a PR for operator merge.

    Args:
        client: dict with at least {"id": str} OR a plain client_id string.
        draft:  dict with optional keys:
                  files        – list of {path, content} dicts to commit
                  message      – commit message override
                  title        – PR title override
                  autoMerge    – bool; if True, commit directly to deploy branch
                                 instead of opening a PR
                  summary      – human text for PR body

    Returns:
        {ok: bool, commitUrl: str, prUrl?: str, detail: str}
    """
    token = _token()
    if not token:
        return {"ok": False, "detail": "needs GITHUB_TOKEN"}

    cid = _client_id(client)
    if not cid:
        return {"ok": False, "detail": "client id required"}

    repo_full = resolve_repo(client)
    if not repo_full or "/" not in repo_full:
        return {"ok": False,
                "detail": f"no repo linked for client {cid!r} — add it in the "
                          f"client's Workspace (repo = owner/repo)"}

    owner, repo = repo_full.split("/", 1)
    files = draft.get("files") if isinstance(draft, dict) else []
    if not files:
        return {"ok": False, "detail": "draft.files is empty — nothing to commit"}

    auto_merge = bool((draft or {}).get("autoMerge"))
    summary = (draft or {}).get("summary") or ""
    commit_msg = (draft or {}).get("message") or f"Dyson: apply client edit for {cid}"
    pr_title = (draft or {}).get("title") or f"[Dyson] Client update — {cid}"
    stamp = time.strftime("%Y%m%d-%H%M%S")

    try:
        default_br = _default_branch(owner, repo, token)

        if auto_merge:
            # Commit directly to a dedicated deploy branch (no PR).
            deploy_br = "deploy"
            try:
                head_sha = _branch_sha(owner, repo, deploy_br, token)
            except Exception:
                # deploy branch doesn't exist yet — branch off default.
                base_sha = _branch_sha(owner, repo, default_br, token)
                _create_branch(owner, repo, deploy_br, base_sha, token)
                head_sha = base_sha  # noqa: F841 (unused but kept for clarity)
            commit_url = _commit_files(owner, repo, deploy_br, files, commit_msg, token)
            pr_url = ""
            detail = ("Committed directly to 'deploy' branch. "
                      "Vercel auto-deploys from the GitHub push — no PR needed.")
        else:
            # Branch + commit + PR (safest default).
            feature_br = f"dyson/{cid}-{stamp}"
            base_sha = _branch_sha(owner, repo, default_br, token)
            _create_branch(owner, repo, feature_br, base_sha, token)
            commit_url = _commit_files(owner, repo, feature_br, files, commit_msg, token)
            body_text = (f"Auto-generated by Dyson for client `{cid}`.\n\n"
                         + (f"{summary}\n\n" if summary else "")
                         + "Vercel will auto-deploy once this PR is merged.")
            pr_url = _open_pr(owner, repo, feature_br, default_br,
                              pr_title, body_text, token)
            detail = ("Branch created and PR opened for operator merge. "
                      "Vercel auto-deploys from the GitHub push on merge — "
                      "no separate Vercel API call needed.")

    except Exception as exc:
        return {"ok": False, "detail": f"GitHub API error: {exc}"}

    _brain_note(cid, repo_full, commit_url, pr_url)
    _bus_msg(cid, repo_full, commit_url, pr_url)

    result: dict = {"ok": True, "commitUrl": commit_url, "detail": detail}
    if pr_url:
        result["prUrl"] = pr_url
    return result


def status(client_id=None) -> dict:
    """Report deploy config state from env.

    Returns:
        {connected: bool, repo: str|None, lastDeploy: None}
    """
    token = _token()
    connected = bool(token)
    repo = None
    if client_id:
        repo = resolve_repo(client_id)
    return {"connected": connected, "repo": repo, "lastDeploy": None}


# ---------------------------------------------------------------------------
# Repo READ helpers — so Dyson can see the current code before it edits it.
# All best-effort: return "" / [] on any failure (no token, no repo, API error).
# ---------------------------------------------------------------------------
# File types worth sending to Claude as editable context (text/source only).
_TEXT_EXT = (".html", ".htm", ".css", ".js", ".jsx", ".ts", ".tsx", ".json",
             ".md", ".txt", ".svg", ".vue", ".astro", ".mjs", ".cjs")
_SKIP_DIRS = ("node_modules/", ".git/", "dist/", "build/", ".next/", ".vercel/",
              "package-lock.json", "yarn.lock", "pnpm-lock.yaml")


def list_repo_files(repo_full: str, limit: int = 400) -> list:
    """Return a flat list of text-file paths in the repo's default branch."""
    token = _token()
    if not token or "/" not in (repo_full or ""):
        return []
    owner, repo = repo_full.split("/", 1)
    try:
        branch = _default_branch(owner, repo, token)
        head = _branch_sha(owner, repo, branch, token)
        tree = _gh_get(f"/repos/{owner}/{repo}/git/trees/{head}?recursive=1", token)
    except Exception:
        return []
    out = []
    for node in (tree.get("tree") or []):
        if node.get("type") != "blob":
            continue
        path = node.get("path", "")
        low = path.lower()
        if any(s in low for s in _SKIP_DIRS):
            continue
        if not low.endswith(_TEXT_EXT):
            continue
        out.append(path)
        if len(out) >= limit:
            break
    return out


def read_repo_file(repo_full: str, path: str, max_bytes: int = 24000) -> str:
    """Return the decoded text content of one repo file (default branch), or ''."""
    token = _token()
    if not token or "/" not in (repo_full or "") or not path:
        return ""
    owner, repo = repo_full.split("/", 1)
    try:
        info = _gh_get(f"/repos/{owner}/{repo}/contents/{urllib.parse.quote(path)}", token)
        if isinstance(info, dict) and info.get("encoding") == "base64" and info.get("content"):
            raw = base64.b64decode(info["content"])
            if len(raw) > max_bytes:
                raw = raw[:max_bytes]
            return raw.decode("utf-8", "ignore")
    except Exception:
        return ""
    return ""


def read_repo_context(repo_full: str, hint_paths=None, max_files: int = 6,
                      per_file_bytes: int = 8000) -> list:
    """Return [{path, content}] for the files most relevant to an edit.

    hint_paths: paths/keywords Claude or the request pointed at. Falls back to
    common entry files. Caps count + size so the Claude prompt stays lean."""
    files = list_repo_files(repo_full)
    if not files:
        return []
    hint_paths = [h.lower() for h in (hint_paths or []) if h]
    scored = []
    _ENTRY = ("index.html", "app.jsx", "app.tsx", "app.js", "index.jsx",
              "index.tsx", "home", "page.tsx", "page.jsx")
    for p in files:
        low = p.lower()
        score = 0
        for h in hint_paths:
            if h and (h in low or low in h):
                score += 5
        if any(low.endswith(e) or ("/" + e) in ("/" + low) for e in _ENTRY):
            score += 2
        if low.endswith((".html", ".htm")):
            score += 1
        depth = low.count("/")
        score -= depth  # prefer shallow/top-level files
        scored.append((score, p))
    scored.sort(key=lambda t: t[0], reverse=True)
    picked = [p for s, p in scored[:max_files]]
    out = []
    for p in picked:
        content = read_repo_file(repo_full, p, max_bytes=per_file_bytes)
        if content:
            out.append({"path": p, "content": content})
    return out
