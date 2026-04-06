"""Action-auth resolution for Expo / EAS project operations."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from axon_api.services.expo_cli_runtime import (
    ExpoControlError,
    parse_whoami_profile,
    resolve_expo_cli_runtime,
    whoami_has_project_access,
)


async def resolve_project_action_auth(
    db,
    project: Any,
    *,
    expo_token_state_fn: Callable[..., Awaitable[dict[str, Any]]],
    run_eas_cli_async_fn: Callable[..., Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    token_state = await expo_token_state_fn(db, owner=project.owner)
    token = str(token_state.get("value") or "").strip()
    if token:
        return {
            "token": token,
            "source": str(token_state.get("source") or ""),
            "authenticated_account": "",
            "authenticated_email": "",
            "accessible_accounts": [],
        }

    cli_runtime = resolve_expo_cli_runtime(project.project_root)
    if not cli_runtime.available:
        raise ExpoControlError(
            cli_runtime.summary,
            outcome="expo_cli_missing",
            result_payload={
                "project_root": str(project.project_root),
                "project_name": project.app_name,
                "owner": project.owner,
                "command_preview": cli_runtime.command_preview,
                "cli_source": cli_runtime.source,
            },
        )

    try:
        session_probe = await run_eas_cli_async_fn(
            project_root=project.project_root,
            token="",
            command=["whoami"],
            timeout=120,
            expect_json=False,
        )
        session_profile = parse_whoami_profile(str(session_probe.get("stdout") or ""))
    except ExpoControlError as exc:
        if token_state.get("locked"):
            raise ExpoControlError(
                "EXPO_ACCESS_TOKEN exists in the Axon vault, but the vault is currently locked. Unlock the vault or rely on an authenticated local Expo CLI session.",
                outcome="vault_locked",
                result_payload={
                    "project_root": str(project.project_root),
                    "project_name": project.app_name,
                    "owner": project.owner,
                    "vault_locked": True,
                    "command_preview": str((exc.result_payload or {}).get("command_preview") or cli_runtime.command_preview),
                    "cli_source": str((exc.result_payload or {}).get("cli_source") or cli_runtime.source),
                },
            ) from exc
        raise ExpoControlError(
            "Expo / EAS actions need either a matching Expo token or an authenticated local Expo CLI session.",
            outcome=str(exc.outcome or "missing_expo_token"),
            result_payload={
                "project_root": str(project.project_root),
                "project_name": project.app_name,
                "owner": project.owner,
                "vault_locked": False,
                "command_preview": str((exc.result_payload or {}).get("command_preview") or cli_runtime.command_preview),
                "cli_source": str((exc.result_payload or {}).get("cli_source") or cli_runtime.source),
            },
        ) from exc

    if not str(session_profile.get("username") or "").strip():
        raise ExpoControlError(
            "Expo / EAS actions need either a matching Expo token or an authenticated local Expo CLI session.",
            outcome="missing_expo_token",
            result_payload={
                "project_root": str(project.project_root),
                "project_name": project.app_name,
                "owner": project.owner,
                "vault_locked": bool(token_state.get("locked")),
                "command_preview": cli_runtime.command_preview,
                "cli_source": cli_runtime.source,
            },
        )
    if not whoami_has_project_access(session_profile, required_owner=project.owner):
        raise ExpoControlError(
            (
                f"Expo CLI is authenticated as {session_profile.get('username') or 'an unrelated account'}, "
                f"which does not include access to the owner '{project.owner}'."
            ),
            outcome="expo_account_mismatch",
            result_payload={
                "project_root": str(project.project_root),
                "project_name": project.app_name,
                "owner": project.owner,
                "required_owner": project.owner,
                "authenticated_as": session_profile.get("username") or "",
                "authenticated_email": session_profile.get("email") or "",
                "accessible_accounts": list(session_profile.get("account_names") or []),
                "command_preview": cli_runtime.command_preview,
                "cli_source": cli_runtime.source,
            },
        )
    return {
        "token": "",
        "source": "local_cli_session",
        "authenticated_account": str(session_profile.get("username") or "").strip(),
        "authenticated_email": str(session_profile.get("email") or "").strip(),
        "accessible_accounts": list(session_profile.get("account_names") or []),
    }
