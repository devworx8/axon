"""
Axon multi-agent registry scaffolding.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AgentPhase(str, Enum):
    OBSERVE = "observe"
    PLAN = "plan"
    EXECUTE = "execute"
    VERIFY = "verify"
    RECOVER = "recover"


class AgentRole(str, Enum):
    PLANNER = "planner"
    CODER = "coder"
    SCANNER = "scanner"
    REVIEWER = "reviewer"
    REPAIR = "repair"


@dataclass(frozen=True)
class AgentSpec:
    role: AgentRole
    label: str
    description: str
    preferred_model_role: str


AGENT_SPECS: tuple[AgentSpec, ...] = (
    AgentSpec(AgentRole.PLANNER, "Planner Agent", "Builds multi-step plans and execution sequences.", "reasoning"),
    AgentSpec(AgentRole.CODER, "Coder Agent", "Implements code changes and technical fixes.", "code"),
    AgentSpec(AgentRole.SCANNER, "Scanner Agent", "Inspects workspaces, file trees, and local health signals.", "general"),
    AgentSpec(AgentRole.REVIEWER, "Reviewer Agent", "Checks quality, regressions, and readiness.", "reasoning"),
    AgentSpec(AgentRole.REPAIR, "Repair Agent", "Recovers from broken runs and degraded runtime states.", "reasoning"),
)


def lifecycle_phases() -> list[str]:
    return [phase.value for phase in AgentPhase]


def registered_agents() -> list[dict]:
    return [
        {
            "role": spec.role.value,
            "label": spec.label,
            "description": spec.description,
            "preferred_model_role": spec.preferred_model_role,
        }
        for spec in AGENT_SPECS
    ]


def active_agents_count(runtime_ready: bool = True) -> int:
    return len(AGENT_SPECS) if runtime_ready else 0
