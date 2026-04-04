"""Workspace relationship helpers for GitHub/Vercel/Sentry links."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from axon_data import (
    get_project,
    get_projects,
    get_workspace_relationship,
    list_workspace_relationships,
    resolve_workspace_relationship,
    upsert_workspace_relationship,
)


def _json_meta(meta: dict[str, Any] | None) -> str:
    return "{}" if meta is None else json.dumps(meta, sort_keys=True, ensure_ascii=True)


def _parse_meta(meta: Any) -> dict[str, Any]:
    if isinstance(meta, dict):
        return meta
    raw = str(meta or "").strip()
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _project_path(project: Any) -> Path | None:
    path = str((dict(project) if project else {}).get("path") or "").strip()
    if not path:
        return None
    candidate = Path(path).expanduser()
    return candidate if candidate.exists() else None


def _git_output(project_path: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(project_path), *args],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _parse_github_remote(remote_url: str) -> tuple[str, str, str]:
    remote = str(remote_url or "").strip()
    if not remote:
        return "", "", ""
    cleaned = remote.removesuffix(".git")
    if cleaned.startswith("git@github.com:"):
        repo = cleaned.split("git@github.com:", 1)[1]
        return repo, repo.split("/")[-1], f"https://github.com/{repo}"
    if "github.com/" in cleaned:
        repo = cleaned.split("github.com/", 1)[1].lstrip(":/")
        return repo, repo.split("/")[-1], f"https://github.com/{repo}"
    return "", "", ""


def _relationship_signal_tokens(
    relationship: dict[str, Any],
    project: dict[str, Any] | None = None,
) -> set[str]:
    meta = _parse_meta(relationship.get("meta_json"))
    tokens = {
        str(relationship.get("external_id") or "").strip().lower(),
        str(relationship.get("external_name") or "").strip().lower(),
        str(meta.get("project_id") or "").strip().lower(),
        str(meta.get("project_name") or "").strip().lower(),
        str(meta.get("org_id") or "").strip().lower(),
        str(meta.get("remote_url") or "").strip().lower(),
        str(meta.get("config_file") or "").strip().lower(),
    }
    if project:
        tokens.add(str(project.get("name") or "").strip().lower())
        project_path = _project_path(project)
        if project_path is not None:
            tokens.add(project_path.name.strip().lower())
    return {token for token in tokens if token}


def infer_workspace_relationships(project: Any) -> list[dict[str, Any]]:
    project_dict = dict(project) if project else {}
    workspace_id = int(project_dict.get("id") or 0)
    project_path = _project_path(project)
    if workspace_id <= 0 or project_path is None:
        return []

    inferred: list[dict[str, Any]] = []

    remote_url = _git_output(project_path, "config", "--get", "remote.origin.url")
    repo_id, repo_name, repo_url = _parse_github_remote(remote_url)
    if repo_id:
        inferred.append(
            {
                "id": None,
                "workspace_id": workspace_id,
                "external_system": "github",
                "external_id": repo_id,
                "relationship_type": "primary",
                "external_name": repo_name or repo_id,
                "external_url": repo_url,
                "status": "inferred",
                "meta_json": _json_meta({"remote_url": remote_url}),
                "source": "inferred",
            }
        )

    vercel_project = project_path / ".vercel" / "project.json"
    if vercel_project.exists():
        try:
            payload = json.loads(vercel_project.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        project_id = str(payload.get("projectId") or "").strip()
        project_name = str(payload.get("projectName") or "").strip()
        org_id = str(payload.get("orgId") or "").strip()
        if project_id or org_id or project_name:
            inferred.append(
                {
                    "id": None,
                    "workspace_id": workspace_id,
                    "external_system": "vercel",
                    "external_id": project_id,
                    "relationship_type": "primary",
                    "external_name": project_name or project_dict.get("name") or project_id or "Vercel project",
                    "external_url": "",
                    "status": "inferred",
                    "meta_json": _json_meta({"project_id": project_id, "project_name": project_name, "org_id": org_id}),
                    "source": "inferred",
                }
            )

    sentry_files = [
        "sentry.client.config.ts",
        "sentry.client.config.js",
        "sentry.server.config.ts",
        "sentry.server.config.js",
        "sentry.edge.config.ts",
        "sentry.edge.config.js",
        "sentry.properties",
    ]
    found = next((name for name in sentry_files if (project_path / name).exists()), "")
    if found:
        inferred.append(
            {
                "id": None,
                "workspace_id": workspace_id,
                "external_system": "sentry",
                "external_id": "",
                "relationship_type": "primary",
                "external_name": "Sentry",
                "external_url": "",
                "status": "inferred",
                "meta_json": _json_meta({"config_file": found}),
                "source": "inferred",
            }
        )
    return inferred


async def list_workspace_relationship_bundle(
    db,
    *,
    workspace_id: int,
    external_system: str = "",
    status: str = "",
    limit: int = 100,
    include_inferred: bool = True,
) -> list[dict[str, Any]]:
    rows = await list_workspace_relationships(
        db,
        workspace_id=workspace_id,
        external_system=external_system,
        status=status,
        limit=limit,
    )
    persisted = [dict(row) | {"source": "persisted"} for row in rows]
    if not include_inferred:
        return persisted

    project = await get_project(db, workspace_id)
    existing_keys = {
        (
            str(item.get("external_system") or "").strip().lower(),
            str(item.get("external_id") or "").strip().lower(),
        )
        for item in persisted
    }
    for inferred in infer_workspace_relationships(project):
        if external_system and str(inferred.get("external_system") or "").strip().lower() != external_system.strip().lower():
            continue
        if status and str(inferred.get("status") or "").strip().lower() != status.strip().lower():
            continue
        key = (
            str(inferred.get("external_system") or "").strip().lower(),
            str(inferred.get("external_id") or "").strip().lower(),
        )
        if key in existing_keys:
            continue
        persisted.append(inferred)
    return persisted


async def link_workspace_relationship(
    db,
    *,
    workspace_id: int,
    external_system: str,
    external_id: str = "",
    relationship_type: str = "primary",
    external_name: str = "",
    external_url: str = "",
    status: str = "active",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    relationship_id = await upsert_workspace_relationship(
        db,
        workspace_id=workspace_id,
        external_system=external_system,
        external_id=external_id,
        relationship_type=relationship_type,
        external_name=external_name,
        external_url=external_url,
        status=status,
        meta_json=_json_meta(meta),
    )
    row = await get_workspace_relationship(db, relationship_id)
    return dict(row) if row else {"id": relationship_id, "workspace_id": workspace_id, "external_system": external_system}


async def list_workspace_relationships_for_workspace(
    db,
    *,
    workspace_id: int | None = None,
    external_system: str = "",
    status: str = "",
    limit: int = 100,
) -> list[dict[str, Any]]:
    if workspace_id is not None:
        return await list_workspace_relationship_bundle(
            db,
            workspace_id=int(workspace_id),
            external_system=external_system,
            status=status,
            limit=limit,
            include_inferred=True,
        )
    rows = await list_workspace_relationships(
        db,
        workspace_id=workspace_id,
        external_system=external_system,
        status=status,
        limit=limit,
    )
    return [dict(row) for row in rows]


async def resolve_workspace_identity(
    db,
    *,
    external_system: str,
    external_id: str,
) -> dict[str, Any] | None:
    row = await resolve_workspace_relationship(db, external_system=external_system, external_id=external_id)
    return dict(row) if row else None


async def resolve_workspace_for_connector_signal(
    db,
    *,
    external_system: str,
    external_id: str = "",
    project_name: str = "",
) -> int | None:
    system = str(external_system or "").strip().lower()
    external_id_token = str(external_id or "").strip().lower()
    project_token = str(project_name or "").strip().lower()
    if not system:
        return None

    if external_id_token:
        resolved = await resolve_workspace_relationship(db, external_system=system, external_id=external_id_token)
        if resolved:
            return int(resolved["workspace_id"])

    projects = await get_projects(db, status="active")
    matches: list[int] = []
    for project in projects or []:
        project_dict = dict(project)
        workspace_id = int(project_dict.get("id") or 0)
        if workspace_id <= 0:
            continue
        relationships = await list_workspace_relationship_bundle(
            db,
            workspace_id=workspace_id,
            external_system=system,
            limit=20,
            include_inferred=True,
        )
        if not relationships:
            continue
        for relationship in relationships:
            tokens = _relationship_signal_tokens(relationship, project_dict)
            if external_id_token and external_id_token in tokens:
                return workspace_id
            if project_token and project_token in tokens:
                matches.append(workspace_id)
                break

    unique_matches = sorted(set(matches))
    if len(unique_matches) == 1:
        return unique_matches[0]
    return None
