"""
Permission guard scaffolding for Axon.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PermissionScope(str, Enum):
    LOCAL_READ = "local_read"
    LOCAL_WRITE = "local_write"
    NETWORK = "network"
    CLOUD_MODEL = "cloud_model"
    SYSTEM_ACTION = "system_action"
    VAULT = "vault"
    BROWSER_INSPECT = "browser_inspect"
    BROWSER_ACT = "browser_act"


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    scope: PermissionScope
    reason: str
    requires_confirmation: bool = False


def evaluate_permission(
    scope: PermissionScope,
    *,
    vault_unlocked: bool = False,
    cloud_enabled: bool = False,
    allow_system_actions: bool = False,
) -> GuardDecision:
    if scope == PermissionScope.CLOUD_MODEL and not cloud_enabled:
        return GuardDecision(False, scope, "Cloud adapters are disabled by default.", True)
    if scope == PermissionScope.SYSTEM_ACTION and not allow_system_actions:
        return GuardDecision(False, scope, "System actions require explicit confirmation.", True)
    if scope == PermissionScope.VAULT and not vault_unlocked:
        return GuardDecision(False, scope, "Secure Vault is locked.", True)
    return GuardDecision(True, scope, "Allowed")


def default_permission_cards() -> list[dict]:
    return [
        {"scope": PermissionScope.LOCAL_READ.value, "label": "Local Read", "description": "Inspect files, directories, and repository state."},
        {"scope": PermissionScope.LOCAL_WRITE.value, "label": "Local Write", "description": "Write changes only after an explicit operator action."},
        {"scope": PermissionScope.NETWORK.value, "label": "Network", "description": "Used for optional integrations and tunnel connectivity."},
        {"scope": PermissionScope.BROWSER_INSPECT.value, "label": "Browser Inspect", "description": "Read live page state, DOM summaries, and screenshots without mutating the page."},
        {"scope": PermissionScope.BROWSER_ACT.value, "label": "Browser Actions", "description": "Navigation, typing, clicking, and submit-like actions require approval before execution."},
        {"scope": PermissionScope.CLOUD_MODEL.value, "label": "Cloud Models", "description": "External adapters remain disabled until enabled."},
        {"scope": PermissionScope.SYSTEM_ACTION.value, "label": "System Actions", "description": "Restart or reboot actions always require confirmation."},
        {"scope": PermissionScope.VAULT.value, "label": "Secure Vault", "description": "Secrets unlock only for approved actions."},
    ]
