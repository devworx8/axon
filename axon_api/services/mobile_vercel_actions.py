"""Vercel deployment actions for Axon Online mobile control."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from axon_api.services.vault_secret_lookup import vault_secret_status_by_name
from axon_api.services.workspace_relationships import list_workspace_relationships_for_workspace
from axon_data import get_project, get_setting


class MobileVercelActionError(Exception):
    def __init__(
        self,
        summary: str,
        *,
        outcome: str = "blocked",
        result_payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(summary)
        self.summary = summary
        self.outcome = outcome
        self.result_payload = result_payload or {}


def _row(row: Any) -> dict[str, Any]:
    return dict(row) if row else {}


def _parse_meta(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        loaded = json.loads(text)
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


async def _workspace_vercel_context(db, *, workspace_id: int) -> dict[str, Any]:
    workspace = _row(await get_project(db, workspace_id))
    if not workspace:
        raise MobileVercelActionError(
            "Workspace not found for the requested Vercel action.",
            outcome="missing_workspace",
            result_payload={"workspace_id": workspace_id},
        )
    relationships = await list_workspace_relationships_for_workspace(
        db,
        workspace_id=workspace_id,
        external_system="vercel",
        limit=10,
    )
    if not relationships:
        raise MobileVercelActionError(
            f"{workspace.get('name') or 'This workspace'} is not linked to a Vercel project yet.",
            outcome="missing_vercel_link",
            result_payload={"workspace_id": workspace_id, "workspace": workspace},
        )
    relationship = dict(relationships[0])
    meta = _parse_meta(relationship.get("meta_json"))
    project_id = str(relationship.get("external_id") or meta.get("project_id") or "").strip()
    team_id = str(meta.get("org_id") or "").strip()
    project_name = str(relationship.get("external_name") or meta.get("project_name") or workspace.get("name") or "").strip()
    workspace_path = str(workspace.get("path") or "").strip()
    if not project_id:
        raise MobileVercelActionError(
            "The Vercel link is missing a project ID.",
            outcome="missing_project_id",
            result_payload={"workspace_id": workspace_id, "relationship": relationship},
        )
    if not workspace_path:
        raise MobileVercelActionError(
            "The workspace path is missing, so Axon cannot run the Vercel CLI for this project.",
            outcome="missing_workspace_path",
            result_payload={"workspace_id": workspace_id, "workspace": workspace},
        )
    return {
        "workspace_id": workspace_id,
        "workspace": workspace,
        "workspace_path": workspace_path,
        "relationship": relationship,
        "project_id": project_id,
        "team_id": team_id,
        "project_name": project_name or project_id,
    }


async def _vercel_token(db) -> str:
    setting_token = str(await get_setting(db, "vercel_api_token") or "").strip()
    if setting_token:
        return setting_token

    env_token = str(os.environ.get("AXON_VERCEL_TOKEN") or os.environ.get("VERCEL_TOKEN") or "").strip()
    if env_token:
        return env_token

    status = await vault_secret_status_by_name(db, secret_names=("AXON_VERCEL_TOKEN",))
    return str(status.get("value") or "").strip()


async def _vercel_token_state(db) -> dict[str, Any]:
    setting_token = str(await get_setting(db, "vercel_api_token") or "").strip()
    if setting_token:
        return {"value": setting_token, "source": "setting", "present": True, "locked": False}

    env_token = str(os.environ.get("AXON_VERCEL_TOKEN") or os.environ.get("VERCEL_TOKEN") or "").strip()
    if env_token:
        return {"value": env_token, "source": "env", "present": True, "locked": False}

    status = await vault_secret_status_by_name(db, secret_names=("AXON_VERCEL_TOKEN",))
    return {
        "value": str(status.get("value") or "").strip(),
        "source": "vault" if str(status.get("value") or "").strip() else "",
        "present": bool(status.get("present")),
        "locked": bool(status.get("present")) and not bool(status.get("unlocked")),
    }


def _deployment_status(dep: dict[str, Any]) -> str:
    return str(dep.get("state") or dep.get("readyState") or "").strip().upper()


def _deployment_target(dep: dict[str, Any]) -> str:
    return str(dep.get("target") or dep.get("meta", {}).get("target") or "").strip().lower()


def _deployment_url(dep: dict[str, Any]) -> str:
    url = str(dep.get("url") or "").strip()
    if url and not url.startswith("http"):
        return f"https://{url}"
    return url


def _deployment_label(dep: dict[str, Any]) -> str:
    url = _deployment_url(dep)
    return url or str(dep.get("name") or dep.get("uid") or "deployment").strip()


def _vercel_api_get(path: str, *, token: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v not in (None, "")})
    url = f"https://api.vercel.com{path}"
    if query:
        url = f"{url}?{query}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        outcome = "vercel_auth_failed" if exc.code in {401, 403} else "vercel_api_failed"
        raise MobileVercelActionError(
            f"Vercel API request failed with HTTP {exc.code}.",
            outcome=outcome,
            result_payload={"status_code": exc.code, "body": body[:500]},
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive network failure path
        raise MobileVercelActionError(
            f"Vercel API request failed: {exc}",
            outcome="vercel_api_failed",
            result_payload={"error": str(exc)},
        ) from exc


def _list_project_deployments(*, token: str, project_id: str, team_id: str, limit: int = 20) -> list[dict[str, Any]]:
    payload = _vercel_api_get(
        "/v6/deployments",
        token=token,
        params={"projectId": project_id, "teamId": team_id, "limit": limit},
    )
    deployments = payload.get("deployments") or []
    return [dict(dep) for dep in deployments if isinstance(dep, dict)]


def _pick_promote_candidate(deployments: list[dict[str, Any]]) -> dict[str, Any] | None:
    for dep in deployments:
        if _deployment_status(dep) != "READY":
            continue
        if _deployment_target(dep) in {"production", "prod"}:
            continue
        return dep
    return None


def _pick_rollback_candidate(deployments: list[dict[str, Any]]) -> dict[str, Any] | None:
    production = [dep for dep in deployments if _deployment_status(dep) == "READY" and _deployment_target(dep) in {"production", "prod"}]
    return production[1] if len(production) > 1 else None


def _sanitized_cli_preview(command: list[str]) -> str:
    preview: list[str] = []
    skip_token_value = False
    for part in command:
        if skip_token_value:
            preview.append("***")
            skip_token_value = False
            continue
        if part in {"--token", "-t"}:
            preview.append(part)
            skip_token_value = True
            continue
        preview.append(part)
    return " ".join(preview)


def _run_vercel_cli(*, workspace_path: str, token: str, command: list[str]) -> dict[str, Any]:
    full_command = ["npx", "-y", "vercel@latest", "--cwd", workspace_path, "--token", token, "--non-interactive", *command]
    proc = subprocess.run(
        full_command,
        cwd=workspace_path,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    stdout = str(proc.stdout or "").strip()
    stderr = str(proc.stderr or "").strip()
    if proc.returncode != 0:
        raise MobileVercelActionError(
            "Vercel CLI could not complete the requested deployment action.",
            outcome="vercel_cli_failed",
            result_payload={
                "returncode": proc.returncode,
                "stdout": stdout[-1500:],
                "stderr": stderr[-1500:],
                "command_preview": _sanitized_cli_preview(full_command),
            },
        )
    return {
        "returncode": proc.returncode,
        "stdout": stdout[-2000:],
        "stderr": stderr[-2000:],
        "command_preview": _sanitized_cli_preview(full_command),
    }


async def prepare_vercel_action_request(
    db,
    *,
    action_type: str,
    workspace_id: int,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(payload or {})
    context = await _workspace_vercel_context(db, workspace_id=workspace_id)
    token_state = await _vercel_token_state(db)
    token = str(token_state.get("value") or "").strip()
    if not token:
        summary = "Vercel deploy actions need a Vercel access token. Set AXON_VERCEL_TOKEN in the Axon vault or environment, or set the Axon setting vercel_api_token first."
        outcome = "missing_vercel_token"
        if token_state.get("locked"):
            summary = "AXON_VERCEL_TOKEN exists in the Axon vault, but the vault is currently locked. Unlock the vault or set vercel_api_token / AXON_VERCEL_TOKEN in the environment first."
            outcome = "vault_locked"
        raise MobileVercelActionError(
            summary,
            outcome=outcome,
            result_payload={
                "workspace_id": workspace_id,
                "project_id": context["project_id"],
                "team_id": context["team_id"],
                "vault_secret_present": bool(token_state.get("present")),
                "vault_locked": bool(token_state.get("locked")),
            },
        )

    deployment_id = str(payload.get("deployment_id") or "").strip()
    deployment_url = str(payload.get("deployment_url") or "").strip()
    deployment_target = str(payload.get("deployment_target") or "").strip().lower()
    deployment_name = str(payload.get("deployment_name") or "").strip()

    deployments: list[dict[str, Any]] = []
    if not deployment_id and not deployment_url:
        deployments = _list_project_deployments(
            token=token,
            project_id=context["project_id"],
            team_id=context["team_id"],
            limit=20,
        )
        candidate = _pick_promote_candidate(deployments) if action_type == "vercel.deploy.promote" else _pick_rollback_candidate(deployments)
        if not candidate:
            if action_type == "vercel.deploy.promote":
                raise MobileVercelActionError(
                    "No ready preview deployment is available to promote right now.",
                    outcome="no_promote_candidate",
                    result_payload={"workspace_id": workspace_id, "project_id": context["project_id"]},
                )
            raise MobileVercelActionError(
                "No previous production deployment is available to roll back to right now.",
                outcome="no_rollback_candidate",
                result_payload={"workspace_id": workspace_id, "project_id": context["project_id"]},
            )
        deployment_id = str(candidate.get("uid") or "").strip()
        deployment_url = _deployment_url(candidate)
        deployment_target = _deployment_target(candidate)
        deployment_name = str(candidate.get("name") or "").strip()

    effective_payload = {
        **payload,
        "workspace_id": workspace_id,
        "project_id": context["project_id"],
        "team_id": context["team_id"],
        "project_name": context["project_name"],
        "workspace_path": context["workspace_path"],
        "deployment_id": deployment_id,
        "deployment_url": deployment_url,
        "deployment_name": deployment_name,
        "deployment_target": deployment_target,
    }

    target_label = deployment_url or deployment_id or deployment_name or "deployment"
    if action_type == "vercel.deploy.promote":
        summary = f"Promote {target_label} to production for {context['workspace'].get('name') or context['project_name']}."
        title = "Deploy"
    else:
        summary = f"Roll production back to {target_label} for {context['workspace'].get('name') or context['project_name']}."
        title = "Rollback"

    return {
        "payload": effective_payload,
        "title": title,
        "summary": summary,
        "workspace": context["workspace"],
        "project_id": context["project_id"],
        "team_id": context["team_id"],
    }


async def execute_vercel_promote(db, *, payload: dict[str, Any]) -> dict[str, Any]:
    token = await _vercel_token(db)
    if not token:
        raise MobileVercelActionError(
            "Vercel access token missing during promote execution.",
            outcome="missing_vercel_token",
        )
    workspace_path = str(payload.get("workspace_path") or "").strip()
    target = str(payload.get("deployment_url") or payload.get("deployment_id") or "").strip()
    if not workspace_path or not target:
        raise MobileVercelActionError(
            "Promote action is missing its deployment target or workspace path.",
            outcome="invalid_vercel_payload",
            result_payload={"payload": payload},
        )
    command_result = _run_vercel_cli(
        workspace_path=workspace_path,
        token=token,
        command=["promote", target, "--yes"],
    )
    return {
        "workspace_id": payload.get("workspace_id"),
        "project_id": payload.get("project_id"),
        "deployment_id": payload.get("deployment_id"),
        "deployment_url": payload.get("deployment_url"),
        "deployment_target": payload.get("deployment_target"),
        "command": command_result,
        "summary": f"Promoted {target} to production.",
    }


async def execute_vercel_rollback(db, *, payload: dict[str, Any]) -> dict[str, Any]:
    token = await _vercel_token(db)
    if not token:
        raise MobileVercelActionError(
            "Vercel access token missing during rollback execution.",
            outcome="missing_vercel_token",
        )
    workspace_path = str(payload.get("workspace_path") or "").strip()
    target = str(payload.get("deployment_url") or payload.get("deployment_id") or "").strip()
    if not workspace_path or not target:
        raise MobileVercelActionError(
            "Rollback action is missing its deployment target or workspace path.",
            outcome="invalid_vercel_payload",
            result_payload={"payload": payload},
        )
    command_result = _run_vercel_cli(
        workspace_path=workspace_path,
        token=token,
        command=["rollback", target, "--yes"],
    )
    return {
        "workspace_id": payload.get("workspace_id"),
        "project_id": payload.get("project_id"),
        "deployment_id": payload.get("deployment_id"),
        "deployment_url": payload.get("deployment_url"),
        "deployment_target": payload.get("deployment_target"),
        "command": command_result,
        "summary": f"Rolled production back to {target}.",
    }
