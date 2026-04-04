"""Workspace connector inspection and safe reconcile helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from axon_api.services.workspace_relationships import (
    infer_workspace_relationships,
    link_workspace_relationship,
    list_workspace_relationships_for_workspace,
)
from axon_api.services.workspace_repo_inspector import inspect_workspace_repo
from axon_data import get_project


def _row(item: Any) -> dict[str, Any]:
    return dict(item) if item else {}


def _meta_dict(raw: Any) -> dict[str, Any]:
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


def _relationship_key(relationship: dict[str, Any]) -> tuple[str, str]:
    return (
        str(relationship.get("external_system") or "").strip().lower(),
        str(relationship.get("external_id") or "").strip().lower(),
    )


def _persisted_relationship_keys(relationships: list[dict[str, Any]]) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for relationship in relationships:
        if str(relationship.get("source") or "persisted").strip().lower() == "inferred":
            continue
        keys.add(_relationship_key(relationship))
    return keys


def _persistable_inferred_relationships(
    relationships: list[dict[str, Any]],
    inferred_relationships: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    persisted_keys = _persisted_relationship_keys(relationships)
    candidates: list[dict[str, Any]] = []
    for relationship in inferred_relationships:
        key = _relationship_key(relationship)
        if key in persisted_keys:
            continue
        candidates.append(dict(relationship))
    return candidates


def _vercel_project_file_path(project: dict[str, Any]) -> Path | None:
    raw_path = str(project.get("path") or "").strip()
    if not raw_path:
        return None
    return Path(raw_path).expanduser().resolve() / ".vercel" / "project.json"


def _vercel_project_payload(relationships: list[dict[str, Any]]) -> dict[str, str]:
    for relationship in relationships:
        if str(relationship.get("external_system") or "").strip().lower() != "vercel":
            continue
        meta = _meta_dict(relationship.get("meta_json") or relationship.get("meta") or {})
        project_id = str(meta.get("project_id") or relationship.get("external_id") or "").strip()
        org_id = str(meta.get("org_id") or "").strip()
        project_name = str(meta.get("project_name") or relationship.get("external_name") or "").strip()
        if not project_id or not org_id:
            continue
        payload = {
            "projectId": project_id,
            "orgId": org_id,
        }
        if project_name:
            payload["projectName"] = project_name
        return payload
    return {}


def _planned_relationship_repairs(inferred_relationships: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    for relationship in inferred_relationships:
        plans.append(
            {
                "kind": "relationship_upsert",
                "external_system": relationship.get("external_system"),
                "external_id": relationship.get("external_id"),
                "summary": (
                    f"Persist {relationship.get('external_system') or 'connector'} relationship "
                    f"{relationship.get('external_id') or relationship.get('external_name') or ''}".strip()
                ),
                "requires_repo_write": False,
                "ready": True,
            }
        )
    return plans


def _planned_vercel_file_repair(
    *,
    project: dict[str, Any],
    repo: dict[str, Any],
    relationships: list[dict[str, Any]],
) -> dict[str, Any] | None:
    project_file = _vercel_project_file_path(project)
    if project_file is None or project_file.exists():
        return None

    payload = _vercel_project_payload(relationships)
    if not payload:
        return {
            "kind": "vercel_project_file",
            "path": str(project_file),
            "requires_repo_write": True,
            "ready": False,
            "blocked_by": "missing_vercel_metadata",
            "summary": "Missing Vercel metadata for .vercel/project.json.",
        }

    if not bool(repo.get("is_git_repo")):
        return {
            "kind": "vercel_project_file",
            "path": str(project_file),
            "payload": payload,
            "requires_repo_write": True,
            "ready": False,
            "blocked_by": "not_git_repo",
            "summary": "Workspace is not a git repo, so Axon will not write .vercel/project.json automatically.",
        }

    if bool(repo.get("dirty")):
        return {
            "kind": "vercel_project_file",
            "path": str(project_file),
            "payload": payload,
            "requires_repo_write": True,
            "ready": False,
            "blocked_by": "dirty_repo",
            "summary": "Repo is dirty; Axon will not write .vercel/project.json on top of local changes.",
        }

    return {
        "kind": "vercel_project_file",
        "path": str(project_file),
        "payload": payload,
        "requires_repo_write": True,
        "ready": True,
        "blocked_by": "",
        "summary": "Write .vercel/project.json from the linked Vercel project metadata.",
    }


def _inspection_summary(
    *,
    repo: dict[str, Any],
    planned_repairs: list[dict[str, Any]],
) -> str:
    parts = [str(repo.get("summary") or "Workspace repo state unknown.").strip()]
    relationship_repairs = sum(1 for item in planned_repairs if item.get("kind") == "relationship_upsert")
    if relationship_repairs:
        parts.append(f"{relationship_repairs} inferred connector relationship(s) can be persisted.")
    vercel_repair = next((item for item in planned_repairs if item.get("kind") == "vercel_project_file"), None)
    if vercel_repair:
        parts.append(str(vercel_repair.get("summary") or "").strip())
    return " ".join(part for part in parts if part)


def _write_vercel_project_file(project_file: Path, payload: dict[str, str]) -> None:
    project_file.parent.mkdir(parents=True, exist_ok=True)
    project_file.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _reconcile_status(receipts: list[dict[str, Any]]) -> str:
    applied = sum(1 for receipt in receipts if str(receipt.get("outcome") or "") == "applied")
    blocked = sum(1 for receipt in receipts if str(receipt.get("outcome") or "").startswith("blocked"))
    if applied and blocked:
        return "partial"
    if applied:
        return "updated"
    if blocked:
        return "blocked"
    return "noop"


def _reconcile_summary(receipts: list[dict[str, Any]], fallback: str) -> str:
    if not receipts:
        return fallback
    applied = sum(1 for receipt in receipts if str(receipt.get("outcome") or "") == "applied")
    blocked = sum(1 for receipt in receipts if str(receipt.get("outcome") or "").startswith("blocked"))
    if applied and blocked:
        return f"Applied {applied} repair(s); blocked {blocked} unsafe repair(s)."
    if applied:
        return f"Applied {applied} repair(s)."
    if blocked:
        return f"Blocked {blocked} unsafe repair(s); no repo changes applied."
    return fallback


async def inspect_workspace_connectors(
    db,
    *,
    workspace_id: int,
    get_project_fn=get_project,
    list_workspace_relationships_for_workspace_fn=list_workspace_relationships_for_workspace,
    infer_workspace_relationships_fn=infer_workspace_relationships,
) -> dict[str, Any]:
    project = await get_project_fn(db, workspace_id)
    if not project:
        raise ValueError("Workspace not found")

    project_dict = _row(project)
    repo = inspect_workspace_repo(project_dict)
    relationships = await list_workspace_relationships_for_workspace_fn(db, workspace_id=workspace_id, limit=50)
    inferred_relationships = infer_workspace_relationships_fn(project_dict)
    persistable_relationships = _persistable_inferred_relationships(relationships, inferred_relationships)
    planned_repairs = _planned_relationship_repairs(persistable_relationships)
    vercel_repair = _planned_vercel_file_repair(
        project=project_dict,
        repo=repo,
        relationships=[*relationships, *inferred_relationships],
    )
    if vercel_repair:
        planned_repairs.append(vercel_repair)

    return {
        "workspace": project_dict,
        "repo": repo,
        "relationships": relationships,
        "inferred_relationships": inferred_relationships,
        "planned_repairs": planned_repairs,
        "summary": _inspection_summary(repo=repo, planned_repairs=planned_repairs),
        "status": "blocked" if any(not item.get("ready") for item in planned_repairs if item.get("requires_repo_write")) else "ready",
    }


async def reconcile_workspace_connectors(
    db,
    *,
    workspace_id: int,
    persist_inferred: bool = True,
    allow_repo_writes: bool = False,
    get_project_fn=get_project,
    list_workspace_relationships_for_workspace_fn=list_workspace_relationships_for_workspace,
    link_workspace_relationship_fn=link_workspace_relationship,
    infer_workspace_relationships_fn=infer_workspace_relationships,
) -> dict[str, Any]:
    inspection = await inspect_workspace_connectors(
        db,
        workspace_id=workspace_id,
        get_project_fn=get_project_fn,
        list_workspace_relationships_for_workspace_fn=list_workspace_relationships_for_workspace_fn,
        infer_workspace_relationships_fn=infer_workspace_relationships_fn,
    )
    project = dict(inspection.get("workspace") or {})
    receipts: list[dict[str, Any]] = []

    if persist_inferred:
        for relationship in _persistable_inferred_relationships(
            list(inspection.get("relationships") or []),
            list(inspection.get("inferred_relationships") or []),
        ):
            linked = await link_workspace_relationship_fn(
                db,
                workspace_id=workspace_id,
                external_system=str(relationship.get("external_system") or ""),
                external_id=str(relationship.get("external_id") or ""),
                relationship_type=str(relationship.get("relationship_type") or "primary"),
                external_name=str(relationship.get("external_name") or ""),
                external_url=str(relationship.get("external_url") or ""),
                status=str(relationship.get("status") or "inferred"),
                meta=_meta_dict(relationship.get("meta_json")),
            )
            receipts.append(
                {
                    "kind": "relationship_upsert",
                    "external_system": relationship.get("external_system"),
                    "external_id": relationship.get("external_id"),
                    "outcome": "applied",
                    "relationship": linked,
                    "summary": (
                        f"Persisted {relationship.get('external_system') or 'connector'} relationship "
                        f"{relationship.get('external_id') or relationship.get('external_name') or ''}".strip()
                    ),
                }
            )

    vercel_plan = next(
        (item for item in list(inspection.get("planned_repairs") or []) if item.get("kind") == "vercel_project_file"),
        None,
    )
    if vercel_plan:
        if not allow_repo_writes:
            receipts.append(
                {
                    **vercel_plan,
                    "outcome": "blocked_repo_write_not_requested",
                    "summary": "Skipped writing .vercel/project.json because repo writes were not requested.",
                }
            )
        elif not bool(vercel_plan.get("ready")):
            receipts.append(
                {
                    **vercel_plan,
                    "outcome": f"blocked_{vercel_plan.get('blocked_by') or 'repo_write'}",
                }
            )
        else:
            project_file = _vercel_project_file_path(project)
            payload = dict(vercel_plan.get("payload") or {})
            if project_file is not None and payload:
                _write_vercel_project_file(project_file, payload)
                receipts.append(
                    {
                        **vercel_plan,
                        "outcome": "applied",
                        "summary": f"Wrote {project_file} from the linked Vercel project metadata.",
                    }
                )

    refreshed = await inspect_workspace_connectors(
        db,
        workspace_id=workspace_id,
        get_project_fn=get_project_fn,
        list_workspace_relationships_for_workspace_fn=list_workspace_relationships_for_workspace_fn,
        infer_workspace_relationships_fn=infer_workspace_relationships_fn,
    )
    return {
        **refreshed,
        "receipts": receipts,
        "changes_applied": sum(1 for receipt in receipts if str(receipt.get("outcome") or "") == "applied"),
        "blocked_repairs": sum(1 for receipt in receipts if str(receipt.get("outcome") or "").startswith("blocked")),
        "repo_write_requested": allow_repo_writes,
        "status": _reconcile_status(receipts),
        "summary": _reconcile_summary(receipts, str(refreshed.get("summary") or "").strip()),
    }
