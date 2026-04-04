"""Deterministic fast paths for obvious local agent requests.

This keeps narrowly-scoped local actions out of the full ReAct loop when the
request can be executed safely and predictably from the API boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .agent import _blocked_tool_event, _tool_evidence_source
from .agent_file_actions import _direct_agent_action, _looks_like_commit_request
from .agent_toolspecs import AgentRuntimeDeps


@dataclass(frozen=True)
class FastPathResult:
    events: list[dict[str, Any]]
    final_text: str = ""


def fast_path_commit_eligible(
    user_message: str,
    *,
    workspace_path: str = "",
    resource_ids: list[int] | None = None,
    resume_session_id: str = "",
    continue_task: str = "",
    composer_options: dict[str, Any] | None = None,
) -> bool:
    if not str(workspace_path or "").strip():
        return False
    if list(resource_ids or []):
        return False
    if str(resume_session_id or "").strip():
        return False
    if str(continue_task or "").strip():
        return False
    options = dict(composer_options or {})
    if str(options.get("agent_role") or "").strip().lower() == "auto":
        return False
    return _looks_like_commit_request(user_message)


def maybe_run_fast_commit_path(
    user_message: str,
    *,
    deps: AgentRuntimeDeps,
    workspace_path: str,
    project_name: str | None = None,
    workspace_id: int | None = None,
    resource_ids: list[int] | None = None,
    resume_session_id: str = "",
    continue_task: str = "",
    composer_options: dict[str, Any] | None = None,
) -> FastPathResult | None:
    if not fast_path_commit_eligible(
        user_message,
        workspace_path=workspace_path,
        resource_ids=resource_ids,
        resume_session_id=resume_session_id,
        continue_task=continue_task,
        composer_options=composer_options,
    ):
        return None

    direct = _direct_agent_action(
        user_message,
        history=[],
        project_name=project_name,
        workspace_path=workspace_path,
        deps=deps,
    )
    if not direct:
        return None

    tool_name, tool_args, tool_result, answer = direct
    evidence_source = _tool_evidence_source(tool_name, str(tool_result))
    events: list[dict[str, Any]] = [
        {"type": "tool_call", "name": tool_name, "args": dict(tool_args or {})},
        {
            "type": "tool_result",
            "name": tool_name,
            "result": str(tool_result)[:2500],
            "evidence_source": evidence_source,
        },
    ]
    blocked = _blocked_tool_event(
        tool_name,
        dict(tool_args or {}),
        str(tool_result),
        workspace_id=workspace_id,
        workspace_path=workspace_path,
    )
    if blocked:
        events.append(blocked)
        return FastPathResult(events=events, final_text="")

    result_text = str(tool_result or "")
    if result_text.startswith("ERROR:"):
        events.append({"type": "error", "message": result_text})
        return FastPathResult(events=events, final_text="")

    events.append({"type": "text", "chunk": answer, "evidence_source": evidence_source})
    events.append({"type": "done", "iterations": 1, "fast_path": True})
    return FastPathResult(events=events, final_text=answer)
