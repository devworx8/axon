"""Fast local answers for companion voice turns."""

from __future__ import annotations

from typing import Any


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _looks_like_fast_candidate(message: str) -> bool:
    lowered = _clean(message).lower()
    if not lowered:
        return False
    if len(lowered.split()) > 32:
        return False
    if lowered.endswith("?"):
        return True
    return any(
        token in lowered
        for token in (
            "path",
            "branch",
            "structure today's work",
            "structure todays work",
            "plan my day",
            "what should i work on",
            "where should i start",
            "today's work",
            "workspace",
            "repo",
            "project",
            "attention",
            "needs attention",
            "waiting on me",
            "linked systems",
            "integrations",
        )
    )


def maybe_build_fast_voice_response(
    message: str,
    *,
    project: dict[str, Any] | None = None,
    relationships: list[dict[str, Any]] | None = None,
    attention: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    lowered = _clean(message).lower()
    if not _looks_like_fast_candidate(lowered):
        return None

    project = dict(project or {})
    relationships = [dict(item) for item in (relationships or []) if isinstance(item, dict)]
    counts = dict((attention or {}).get("counts") or {})
    lines: list[str] = []
    evidence_source = "workspace_snapshot"

    if project and any(token in lowered for token in ("path", "where is", "workspace path", "repo path", "root")):
        lines.append(f"Workspace: {_clean(project.get('name')) or 'Current workspace'}")
        lines.append(f"Path: {_clean(project.get('path')) or 'unknown'}")
        branch = _clean(project.get("git_branch"))
        if branch:
            lines.append(f"Branch: {branch}")
    elif project and any(token in lowered for token in ("branch", "git branch")):
        lines.append(f"Workspace: {_clean(project.get('name')) or 'Current workspace'}")
        lines.append(f"Branch: {_clean(project.get('git_branch')) or 'unknown'}")
        path = _clean(project.get("path"))
        if path:
            lines.append(f"Path: {path}")
    elif counts and any(token in lowered for token in ("attention", "needs attention", "urgent", "waiting on me", "watch")):
        lines.append("Attention summary:")
        lines.append(f"Now: {int(counts.get('now') or 0)}")
        lines.append(f"Waiting on me: {int(counts.get('waiting_on_me') or 0)}")
        lines.append(f"Watch: {int(counts.get('watch') or 0)}")
        evidence_source = "memory"
    elif project and any(
        token in lowered
        for token in (
            "structure today's work",
            "structure todays work",
            "plan my day",
            "what should i work on",
            "where should i start",
            "today's work",
        )
    ):
        lines.append(f"Focus workspace: {_clean(project.get('name')) or 'Current workspace'}")
        branch = _clean(project.get("git_branch"))
        if branch:
            lines.append(f"Branch: {branch}")
        now_count = int(counts.get("now") or 0)
        waiting_count = int(counts.get("waiting_on_me") or 0)
        watch_count = int(counts.get("watch") or 0)
        lines.append(f"Attention now: {now_count}")
        lines.append(f"Waiting on me: {waiting_count}")
        lines.append(f"Watch: {watch_count}")
        if now_count or waiting_count or watch_count:
            lines.append("Start with the highest-urgency attention item, then clear anything waiting on you.")
        else:
            lines.append("No urgent inbox items are flagged right now.")
            lines.append("Start with the highest-impact task already in motion for this workspace.")
        lines.append("Use a short follow-up if you want a tighter instant answer.")
        evidence_source = "memory"
    elif relationships and any(token in lowered for token in ("linked systems", "integrations", "github", "vercel", "sentry")):
        lines.append("Linked systems:")
        for relationship in relationships[:5]:
            system = _clean(relationship.get("external_system")) or "system"
            name = _clean(relationship.get("external_name")) or _clean(relationship.get("external_id")) or "linked"
            status = _clean(relationship.get("status"))
            line = f"- {system}: {name}"
            if status:
                line += f" [{status}]"
            lines.append(line)
        evidence_source = "resource"
    elif project and any(token in lowered for token in ("workspace", "project", "status", "what do you know")):
        lines.append(f"Workspace: {_clean(project.get('name')) or 'Current workspace'}")
        path = _clean(project.get("path"))
        if path:
            lines.append(f"Path: {path}")
        branch = _clean(project.get("git_branch"))
        if branch:
            lines.append(f"Branch: {branch}")
        stack = _clean(project.get("stack"))
        if stack:
            lines.append(f"Stack: {stack}")

    if not lines:
        return None
    return {
        "content": "\n".join(lines),
        "tokens_used": 0,
        "backend": "local",
        "evidence_source": evidence_source,
        "fast_path": True,
    }
