"""agency_dyson.py — "Dyson", the Forge AI Agency EDIT agent.

Dyson takes a client edit request and produces a DRAFT implementation plan:
  - affected files / pages / workflows
  - a risk level + why
  - step-by-step implementation
…then waits in the Approval Center. Nothing goes live until you approve.

M1: draft generation uses a real Claude call grounded on Dyson's brain playbook
(vault Skills/dyson-playbook.md, mtime-cached). Falls back to _PLAYBOOK heuristics
when no key or the Claude call/parse fails — so the dashboard never errors.

M3: apply(draft) fires on operator approval → calls agency_deploy.ship(client, draft).
Returns {ok, detail, url?}. On no-key/failure: {ok:False, detail:"queued, needs key"}.

Store: marcus_state/agency_dyson.json
"""
import forge_atomic
import json
import os
import threading
import time
from pathlib import Path

import agency_requests_io
import agency_approvals_io
import review_agent  # _claude(key, system, user, max_tokens), MODEL, _api_key()

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "agency_dyson.json"
_LOCK = threading.Lock()

# --- Anthropic key (mirrors agency_agents._agency_key) -----------------------
_AGENCY_ENV_CANDIDATES = [
    HERE.parent / "forge-agency" / "config" / "agency.env",
    Path.home() / "Desktop" / "forge-agency" / "config" / "agency.env",
]


def _agency_key():
    """Return (key, source). Agency key wins; falls back to wholesale."""
    k = os.environ.get("AGENCY_ANTHROPIC_API_KEY")
    if k:
        return k, "agency-env"
    for p in _AGENCY_ENV_CANDIDATES:
        if p.exists():
            for line in p.read_text().splitlines():
                s = line.strip()
                if s.startswith("ANTHROPIC_API_KEY=") and not s.startswith("#"):
                    v = s.split("=", 1)[1].strip()
                    if v and not v.startswith("sk-ant-..."):
                        return v, "agency"
    wholesale = review_agent._api_key()
    if wholesale:
        return wholesale, "wholesale"
    return None, None


# --- brain skills (mtime-cached playbook, mirrors agency_agents._load_skills) -
_SEED_SKILLS_DIRS = [
    HERE.parent / "forge-agency" / "skills",
    Path.home() / "Desktop" / "forge-agency" / "skills",
]
_SK_CACHE = {}  # agent_id -> (mtime_sig_tuple, text)
_DYSON_PLAYBOOK_REL = "Skills/dyson-playbook.md"


def _load_skills():
    """Load Dyson's playbook: seed + brain vault version, mtime-cached.
    Returns "" if neither source exists."""
    try:
        import brain_io
        parts, sig = [], []
        srcs = []
        for d in _SEED_SKILLS_DIRS:
            p = d / "dyson-playbook.md"
            if p.is_file():
                srcs.append(p)
                break
        srcs.append(brain_io.VAULT / _DYSON_PLAYBOOK_REL)
        for p in srcs:
            if p.is_file():
                parts.append(p.read_text(errors="ignore"))
                sig.append(p.stat().st_mtime)
        sig_key = tuple(sig)
        cached = _SK_CACHE.get("dyson")
        if not cached or cached[0] != sig_key:
            text = "\n\n".join(parts)
            _SK_CACHE["dyson"] = (sig_key, text)
            return text
        return cached[1]
    except Exception:
        cached = _SK_CACHE.get("dyson")
        return cached[1] if cached else ""

STATUSES = ["draft", "approved", "revision", "rejected"]

# Heuristic playbook per request type → (risk, affected-kinds, steps).
# This is the mock "intelligence". Replace generate_draft() body with a real
# Claude call that reads the live codebase to make this genuinely smart.
_PLAYBOOK = {
    "Website Edit": {
        "risk": "low",
        "affected": [("page", "target page"), ("file", "index.html / styles.css")],
        "steps": [
            "Locate the section the client referenced",
            "Back up the current markup/styles",
            "Apply copy / image / layout change",
            "Preview on a staging URL",
            "Publish after approval",
        ],
    },
    "New Page": {
        "risk": "medium",
        "affected": [("file", "new page file"), ("file", "nav / sitemap"),
                     ("workflow", "form/booking integration")],
        "steps": [
            "Scaffold the new page from the site template",
            "Wire nav links + sitemap entry",
            "Connect any forms/booking to the client's tool",
            "SEO: title, meta, OG tags",
            "Preview, QA on mobile, publish",
        ],
    },
    "Bug Fix": {
        "risk": "medium",
        "affected": [("file", "suspect module"), ("workflow", "delivery webhook")],
        "steps": [
            "Reproduce the reported bug",
            "Trace root cause (logs / network / config)",
            "Apply the smallest safe fix",
            "Add a guard / test so it can't regress",
            "Verify end-to-end, then close",
        ],
    },
    "Content Update": {
        "risk": "low",
        "affected": [("page", "content section")],
        "steps": [
            "Pull the new copy from the request",
            "Update the section, keep formatting consistent",
            "Proofread + check links",
            "Publish after approval",
        ],
    },
    "SEO": {
        "risk": "low",
        "affected": [("file", "meta tags"), ("file", "sitemap.xml / robots.txt")],
        "steps": [
            "Audit current titles / meta / headings",
            "Apply target keywords naturally",
            "Add schema markup where useful",
            "Resubmit sitemap to Search Console",
        ],
    },
    "Integration": {
        "risk": "high",
        "affected": [("workflow", "third-party API"), ("file", "config / env"),
                     ("workflow", "n8n automation")],
        "steps": [
            "Confirm credentials + scopes (env placeholders only)",
            "Build the integration behind a feature flag",
            "Test with sandbox / test data",
            "Add error handling + retries",
            "Enable for the client after approval",
        ],
    },
    "Design Change": {
        "risk": "medium",
        "affected": [("file", "styles.css / theme"), ("page", "affected pages")],
        "steps": [
            "Capture before screenshots",
            "Apply the design change in CSS/theme tokens",
            "Check responsive breakpoints",
            "Side-by-side review, then publish",
        ],
    },
    "AI Agent": {
        "risk": "high",
        "affected": [("workflow", "agent config"), ("file", "prompt / playbook"),
                     ("workflow", "GHL / channel hookup")],
        "steps": [
            "Define the agent's job + guardrails",
            "Draft the prompt + voice from the client's brand",
            "Wire channels (chat / SMS / voice) in test mode",
            "Dry-run on sample conversations",
            "Go live after approval, monitor first 24h",
        ],
    },
    "Other": {
        "risk": "medium",
        "affected": [("page", "TBD — Dyson will scope on review")],
        "steps": [
            "Clarify scope with the client",
            "Identify affected files/pages/workflows",
            "Draft the change",
            "Review + approve + ship",
        ],
    },
}

_PRIORITY_BUMP = {"urgent": 1, "high": 1}  # bump risk a notch for hot requests
_RISK_ORDER = ["low", "medium", "high"]


def _bump_risk(risk, priority):
    if priority in _PRIORITY_BUMP and risk in _RISK_ORDER:
        i = min(_RISK_ORDER.index(risk) + _PRIORITY_BUMP[priority],
                len(_RISK_ORDER) - 1)
        return _RISK_ORDER[i]
    return risk


def _load():
    if STATE.exists():
        try:
            d = json.loads(STATE.read_text())
            if isinstance(d, dict) and isinstance(d.get("drafts"), list):
                return d
        except Exception:
            pass
    return {"drafts": [], "seq": 0}


def _save(d):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    forge_atomic.atomic_write_json(STATE, d)


def list_drafts():
    with _LOCK:
        d = _load()
        drafts = sorted(d.get("drafts", []),
                        key=lambda x: x.get("createdAt") or 0, reverse=True)
        return {"drafts": drafts, "count": len(drafts)}


# Which request types the agent can typically handle end-to-end vs. hand to you.
_OPERATOR_TYPES = ("Integration", "AI Agent", "New Page")


def _reco_heuristic(rtype, risk):
    """Who should do it? Bigger / higher-risk → operator; quick + contained → agent."""
    if risk == "high" or rtype in _OPERATOR_TYPES:
        return ("operator",
                "Bigger or higher-risk job — recommend you take this one personally.")
    return ("agent",
            "Quick, contained change — the agent can do this and open a PR for you.")


def _heuristic_draft_fields(req):
    """Build draft fields from _PLAYBOOK heuristics. Returns a dict (same shape as
    the Claude path). No repo access here → files stays empty (plan only)."""
    rtype = req.get("type") or "Other"
    play = _PLAYBOOK.get(rtype, _PLAYBOOK["Other"])
    risk = _bump_risk(play["risk"], req.get("priority"))
    risk_reason = (f"{rtype} for {req.get('clientName')} at "
                   f"{req.get('priority')} priority. "
                   + {"low": "Isolated, easily reversible.",
                      "medium": "Touches shared files; needs QA before publish.",
                      "high": "External systems / live behavior — review carefully."}[risk])
    affected = [{"type": t, "name": n} for (t, n) in play["affected"]]
    summary = (f"Dyson drafted a {len(play['steps'])}-step plan for "
               f"this {rtype.lower()} ({risk} risk).")
    reco, reco_reason = _reco_heuristic(rtype, risk)
    return {
        "summary": summary, "risk": risk, "riskReason": risk_reason,
        "affected": affected, "steps": list(play["steps"]),
        "complexity": risk, "estimate": "",
        "recommendation": reco, "recommendationReason": reco_reason,
        "files": [],
    }


def _workspace_block(ws):
    """Human-readable client workspace context for the prompt (never secrets)."""
    if not isinstance(ws, dict) or not any(ws.values()):
        return "(no workspace on file — repo/site/brand unknown)"
    lines = []
    if ws.get("repo"):        lines.append(f"Repo: {ws['repo']} (edits open a PR → Vercel deploys on merge)")
    if ws.get("liveUrl"):     lines.append(f"Live URL: {ws['liveUrl']}")
    if ws.get("stack"):       lines.append(f"Stack: {ws['stack']}")
    if ws.get("brand"):       lines.append(f"Brand / design notes: {ws['brand']}")
    if ws.get("assets"):      lines.append(f"Assets: {ws['assets']}")
    if ws.get("accessNotes"): lines.append(f"Access notes: {ws['accessNotes']}")
    return "\n".join(lines) if lines else "(workspace mostly empty)"


def _files_block(repo_files):
    """Embed the current repo file contents Dyson may edit."""
    if not repo_files:
        return ("(no repo files available — either no repo is linked or it could "
                "not be read. Produce a PLAN only; do NOT invent file contents.)")
    parts = ["Current files from the repo (edit these — return the FULL new content "
             "of any file you change):"]
    for f in repo_files:
        parts.append(f"\n----- FILE: {f['path']} -----\n{f['content']}")
    return "\n".join(parts)


def _claude_draft_fields(req, workspace=None, repo_files=None):
    """Ask Claude to (1) assess who should do it and (2) — when repo files are
    available and it's agent-appropriate — WRITE the actual edited files.

    Returns a dict {summary, risk, riskReason, affected, steps, complexity,
    estimate, recommendation, recommendationReason, files}. Raises on failure so
    the caller falls back to the heuristic path."""
    key, _ = _agency_key()
    if not key:
        raise RuntimeError("no anthropic key")

    playbook = _load_skills()
    playbook_block = (f"\n\n=== DYSON PLAYBOOK ===\n{playbook[:2500]}"
                      if playbook else "")
    has_files = bool(repo_files)

    system = (
        "You are Dyson, the edit/build agent for Forge AI Agency. For each client "
        "website request you do TWO things:\n"
        "1) ASSESS who should do it — you (the agent) or the human operator. "
        "Recommend 'agent' for quick, contained, low-risk edits (copy/image/text/"
        "small style/section changes) where the intent is clear. Recommend "
        "'operator' for bigger, ambiguous, design-heavy, or higher-risk work "
        "(new pages, integrations, agents, brand redesigns, anything touching live "
        "external systems or needing judgment/assets you don't have).\n"
        "2) If — and ONLY if — you recommend 'agent' AND the current file contents "
        "are provided, WRITE the change: return the FULL new content of each file "
        "you edit, matching the site's existing style and the client's brand. Keep "
        "the diff minimal and safe. If you recommend 'operator', or no files are "
        "provided, return files: [] and give a clear plan instead.\n\n"
        "Return ONLY valid JSON (no markdown) with EXACTLY these keys: "
        "{\"summary\": str, \"risk\": \"low\"|\"medium\"|\"high\", \"riskReason\": str, "
        "\"complexity\": \"low\"|\"medium\"|\"high\", \"estimate\": str, "
        "\"recommendation\": \"agent\"|\"operator\", \"recommendationReason\": str, "
        "\"affectedFiles\": [str], \"affectedPages\": [str], \"steps\": [str], "
        "\"files\": [{\"path\": str, \"content\": str}]}. "
        "files carries the FULL new file content for each edited file (never a diff, "
        "never a snippet). recommendationReason: one plain sentence to the operator."
        + playbook_block
    )

    user = (
        f"CLIENT REQUEST\n"
        f"Client: {req.get('clientName', 'Unknown')}\n"
        f"Type: {req.get('type', 'Other')} · Priority: {req.get('priority', 'normal')}\n"
        f"Title: {req.get('title', '')}\n"
        f"Page/URL: {req.get('pageUrl', '') or '(not specified)'}\n"
        f"Details: {req.get('detail', '') or req.get('description', '')}\n"
        f"Desired outcome: {req.get('outcome', '') or '(not specified)'}\n"
        f"Reference links: {req.get('references', '') or '(none)'}\n\n"
        f"CLIENT WORKSPACE\n{_workspace_block(workspace)}\n\n"
        f"{_files_block(repo_files)}"
    )

    raw = review_agent._claude(key, system, user, max_tokens=4096)

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.rsplit("```", 1)[0].strip()
    parsed = json.loads(cleaned)

    affected = []
    for name in (parsed.get("affectedFiles") or []):
        affected.append({"type": "file", "name": name})
    for name in (parsed.get("affectedPages") or []):
        affected.append({"type": "page", "name": name})
    if not affected:
        affected.append({"type": "page", "name": "TBD"})

    risk = parsed.get("risk", "medium")
    if risk not in _RISK_ORDER:
        risk = "medium"
    complexity = parsed.get("complexity", risk)
    if complexity not in _RISK_ORDER:
        complexity = risk
    reco = parsed.get("recommendation", "")
    if reco not in ("agent", "operator"):
        reco = "operator" if risk == "high" else "agent"

    # Validate + sanitize the files Dyson wants to write. Only keep well-formed
    # {path, content} entries that target the files we actually gave it (guard
    # against hallucinated paths), and only when it recommended 'agent'.
    allowed_paths = {f["path"] for f in (repo_files or [])}
    files = []
    if has_files and reco == "agent":
        for f in (parsed.get("files") or []):
            if not isinstance(f, dict):
                continue
            path = str(f.get("path") or "").strip()
            content = f.get("content")
            if path and isinstance(content, str) and content and path in allowed_paths:
                files.append({"path": path, "content": content})

    return {
        "summary": parsed.get("summary", ""),
        "risk": risk,
        "riskReason": parsed.get("riskReason", ""),
        "affected": affected,
        "steps": [str(s) for s in (parsed.get("steps") or [])],
        "complexity": complexity,
        "estimate": parsed.get("estimate", ""),
        "recommendation": reco,
        "recommendationReason": parsed.get("recommendationReason", ""),
        "files": files,
    }


def _resolve_repo_context(req):
    """Load the client's workspace + the current repo files most relevant to this
    request, so Dyson can write a real change. Best-effort → ({}, [], '')."""
    workspace, repo_files, repo = {}, [], ""
    try:
        import agency_io
        import agency_deploy
        workspace = agency_io.get_workspace(req.get("clientId")) or {}
        repo = agency_deploy.resolve_repo(
            {"id": req.get("clientId"), "workspace": workspace})
        if repo:
            hints = [h for h in (req.get("pageUrl", ""), req.get("title", "")) if h]
            repo_files = agency_deploy.read_repo_context(repo, hint_paths=hints)
    except Exception:
        pass
    return workspace, repo_files, repo


def generate_draft(request_id):
    """Assess a request, and — when a repo is linked and it's agent-appropriate —
    WRITE the actual file changes, then queue it for approval (one-tap PR → deploy).

    Tries the real Claude path (grounded on the playbook + the client's repo);
    falls back to _PLAYBOOK heuristics on no key / read / parse failure. Never
    raises out — a failure just yields a plan-only draft.
    """
    req = agency_requests_io.get_request(request_id)
    if not req:
        return {"error": "request not found"}

    workspace, repo_files, repo = _resolve_repo_context(req)

    try:
        fields = _claude_draft_fields(req, workspace=workspace, repo_files=repo_files)
        source = "claude"
    except Exception:
        fields = _heuristic_draft_fields(req)
        source = "heuristic"

    files = fields.get("files") or []
    reco = fields.get("recommendation") or "operator"

    with _LOCK:
        d = _load()
        now = int(time.time() * 1000)
        d["seq"] = d.get("seq", 0) + 1
        draft = {
            "id": f"d{d['seq']}_{now}",
            "requestId": request_id,
            "clientId": req.get("clientId"),
            "clientName": req.get("clientName"),
            "title": f"Plan: {req.get('title')}",
            "summary": fields.get("summary", ""),
            "affected": fields.get("affected", []),
            "risk": fields.get("risk", "medium"),
            "riskReason": fields.get("riskReason", ""),
            "steps": fields.get("steps", []),
            "complexity": fields.get("complexity", ""),
            "estimate": fields.get("estimate", ""),
            "recommendation": reco,
            "recommendationReason": fields.get("recommendationReason", ""),
            "repo": repo,
            "files": files,                       # staged edits — ship() commits these
            "filesCount": len(files),
            "status": "draft",
            "source": source,
            "createdAt": now,
        }
        d.setdefault("drafts", []).append(draft)
        _save(d)

    # Hand off to the human-in-the-loop Approval Center. Note who Dyson thinks
    # should do it + whether the change is already written (filesCount).
    who = ("🤖 Agent can handle" if reco == "agent" else "👤 Recommend you do this")
    staged = (f" · {len(files)} file(s) written, ready to ship"
              if files else (" · no repo linked" if not repo else " · plan only"))
    agency_approvals_io.add(
        "dyson", draft["id"], draft["title"],
        f"{who}. {fields.get('summary', '')}{staged}",
        client=req.get("clientName", ""), risk=draft["risk"],
        payload={"affected": [a["name"] for a in draft["affected"]],
                 "steps": draft["steps"], "requestId": request_id,
                 "recommendation": reco, "filesCount": len(files),
                 "changedFiles": [f["path"] for f in files]})

    # Announce the plan on the agent bus → Telegram offers Approve & ship / Reject.
    try:
        import agent_bus
        agent_bus.send(
            "dyson", "all", "note",
            f"🛠 Dyson assessed {req.get('clientName', 'a client')}: {req.get('title')}",
            {"type": "dyson_plan", "draftId": draft["id"], "requestId": request_id,
             "client": req.get("clientName", ""), "title": req.get("title", ""),
             "risk": draft["risk"], "summary": draft["summary"],
             "recommendation": reco,
             "recommendationReason": draft["recommendationReason"],
             "filesCount": len(files),
             "changedFiles": [f["path"] for f in files][:6],
             "steps": [str(s) for s in draft["steps"]][:6]},
        )
    except Exception:
        pass

    return {"ok": True, "draft": draft}


def apply(draft):
    """M3 execute: ship an approved draft via agency_deploy.ship(client, draft).

    Called by the Approvals Center dispatcher (agency_approvals_io.decide) on
    kind="dyson" + action="approve". Wave-2 wires the dispatch call.

    Returns {ok, detail, url?}. On no deploy-key or any failure:
    {ok: False, detail: "queued, needs GITHUB_TOKEN"} — never silent, never throws.
    """
    client = {"id": draft.get("clientId"), "name": draft.get("clientName", "")}
    if not client["id"]:
        client = draft.get("clientName", "")
    draft_id = draft.get("id", "")

    # Idempotency guard: two routes (Approvals Center + Dyson tab) can both call
    # apply() for the same draft. Atomically claim it so the live deploy fires once.
    # Released below if the ship fails, so the operator can retry after adding a key.
    if draft_id:
        with _LOCK:
            d = _load()
            cur = next((x for x in d.get("drafts", []) if x.get("id") == draft_id), None)
            if cur is not None:
                if cur.get("appliedAt"):
                    return {"ok": True, "detail": "already shipped (idempotent)"}
                cur["appliedAt"] = int(time.time() * 1000)
                _save(d)

    commit_url = None
    pr_url = None
    try:
        import agency_deploy  # Lane E creates this (frozen name from plan §4 M4)
        result = agency_deploy.ship(client, draft)
        ok = bool(result.get("ok"))
        detail = result.get("detail", "shipped" if ok else "deploy failed")
        commit_url = result.get("commitUrl")
        pr_url = result.get("prUrl")
        url = pr_url or commit_url
    except ImportError:
        ok = False
        detail = "queued, needs GITHUB_TOKEN (agency_deploy not yet available)"
        url = None
    except Exception as exc:
        ok = False
        detail = f"queued, needs GITHUB_TOKEN ({exc})"
        url = None

    # Persist the ship result onto the draft so the UI can show the operator a
    # permanent "View PR" link (not just in the one-time POST response).
    if ok and draft_id:
        with _LOCK:
            d = _load()
            cur = next((x for x in d.get("drafts", []) if x.get("id") == draft_id), None)
            if cur is not None:
                cur["deploy"] = {"ok": True, "detail": detail, "commitUrl": commit_url,
                                 "prUrl": pr_url, "shippedAt": int(time.time() * 1000)}
                if pr_url:
                    cur["prUrl"] = pr_url
                if commit_url:
                    cur["commitUrl"] = commit_url
                _save(d)

    # Write result note to the brain (best-effort).
    note_text = (f"Dyson apply: draft {draft_id} for {draft.get('clientName', '')} — "
                 f"{'shipped' if ok else 'queued'}: {detail}")
    try:
        import brain_io
        stamp = time.strftime("%Y-%m-%d %H:%M")
        brain_io.write_note(
            f"Log/dyson-apply-{draft_id}.md",
            f"---\nagent: dyson\nts: {stamp}\nok: {ok}\n---\n\n{note_text}",
            reason=f"Dyson apply {draft_id} {stamp}",
        )
    except Exception:
        pass

    # Broadcast on the agent bus (best-effort).
    try:
        import agent_bus
        agent_bus.send(
            "dyson", "all", "status", note_text,
            {"draftId": draft_id, "client": draft.get("clientName", ""), "ok": ok},
        )
    except Exception:
        pass

    # Release the idempotency claim on failure so a retry is possible.
    if not ok and draft_id:
        with _LOCK:
            d = _load()
            cur = next((x for x in d.get("drafts", []) if x.get("id") == draft_id), None)
            if cur is not None and cur.get("appliedAt"):
                cur.pop("appliedAt", None)
                _save(d)

    out = {"ok": ok, "detail": detail}
    if url:
        out["url"] = url
    return out


def decision(draft_id, action, note=None):
    """Approve / revise / reject a Dyson draft (mirrors Approval Center).

    On "approve": status is flipped to 'approved' AND apply() is called so the
    live deploy fires immediately when this entry point is used directly.
    The canonical M3 path is agency_approvals_io.decide → apply() (Wave-2 wires
    the dispatch); this guard ensures correctness when decision() is called directly.
    """
    state_map = {"approve": "approved", "revise": "revision", "reject": "rejected"}
    if action not in state_map:
        return {"error": f"action must be one of {list(state_map)}"}
    with _LOCK:
        d = _load()
        dr = next((x for x in d.get("drafts", []) if x.get("id") == draft_id), None)
        if not dr:
            return {"error": "draft not found"}
        dr["status"] = state_map[action]
        _save(d)
        draft_snapshot = dict(dr)

    result = {"ok": True, "draft": draft_snapshot}
    if action == "approve":
        result["apply"] = apply(draft_snapshot)
    return result
