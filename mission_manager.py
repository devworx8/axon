"""
Mission scaffolding for Axon.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MissionStatus(str, Enum):
    QUEUED = "queued"
    ACTIVE = "active"
    BLOCKED = "blocked"
    DONE = "done"


@dataclass(frozen=True)
class MissionSuggestion:
    title: str
    rationale: str
    priority: str
    workspace_name: str | None = None


def empty_state_copy() -> dict:
    return {
        "title": "No active missions",
        "body": "Axon can create missions from workspace health, recent activity, or your goals.",
        "primary_action": "Create mission",
        "secondary_action": "Suggest missions",
    }


def suggest_from_runtime(workspaces: list[dict], tasks: list[dict], activity: list[dict]) -> list[dict]:
    suggestions: list[dict] = []
    for workspace in sorted(workspaces, key=lambda item: item.get("health", 100))[:3]:
        if (workspace.get("health") or 100) < 65:
            suggestions.append(
                {
                    "title": f"Inspect {workspace.get('name', 'workspace')} health drift",
                    "rationale": "Low health score suggests stale work or unresolved debt.",
                    "priority": "high",
                    "workspace_name": workspace.get("name"),
                }
            )
    if not suggestions and tasks:
        suggestions.append(
            {
                "title": "Close one lingering mission",
                "rationale": "A quick win keeps Axon's queue healthy.",
                "priority": "medium",
                "workspace_name": tasks[0].get("project_name"),
            }
        )
    if not suggestions and activity:
        suggestions.append(
            {
                "title": "Review latest runtime activity",
                "rationale": "Recent events can reveal a hidden blocker or recovery need.",
                "priority": "low",
                "workspace_name": None,
            }
        )
    return suggestions
