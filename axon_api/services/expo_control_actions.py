"""Expo / EAS discovery, status, and action helpers for Axon."""

from __future__ import annotations

import json
import os
import subprocess
import time
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from axon_api.services.expo_action_auth import resolve_project_action_auth
from axon_api.services.expo_cli_runtime import (
    ExpoControlError,
    parse_whoami_profile,
    resolve_expo_cli_runtime,
    run_eas_cli,
    whoami_has_project_access,
)
from axon_api.services.vault_secret_lookup import vault_secret_status_by_name
from axon_data import get_project, get_projects, get_setting

OVERVIEW_CACHE_TTL_SECONDS = 45.0
_OVERVIEW_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
PERSISTED_OVERVIEW_CACHE_DIR = Path.home() / ".devbrain" / ".cache" / "expo_overview"

@dataclass(slots=True)
class ExpoProjectContext:
    workspace_id: int | None
    workspace_name: str
    workspace_path: str
    project_root: Path
    app_name: str
    owner: str
    slug: str
    project_id: str
    android_package: str
    ios_bundle_identifier: str
    build_profiles: list[str]
    runtime_version: str
    update_channel: str
    channels: dict[str, str]
    git_branch: str


def _row(row: Any) -> dict[str, Any]:
    return dict(row) if row else {}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json_file(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return {}
    try:
        loaded = json.loads(text)
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _app_config(root: Path) -> dict[str, Any]:
    app_json = root / "app.json"
    if app_json.exists():
        loaded = _load_json_file(app_json)
        expo = loaded.get("expo")
        return dict(expo) if isinstance(expo, dict) else {}
    return {}


def _eas_config(root: Path) -> dict[str, Any]:
    eas_json = root / "eas.json"
    if eas_json.exists():
        return _load_json_file(eas_json)
    return {}


def _package_config(root: Path) -> dict[str, Any]:
    package_json = root / "package.json"
    if package_json.exists():
        return _load_json_file(package_json)
    return {}


def _owner_env_suffix(owner: str) -> str:
    raw = str(owner or "").strip().upper()
    if not raw:
        return ""
    return "".join(char if char.isalnum() else "_" for char in raw).strip("_")


def _runtime_version_label(value: Any) -> str:
    if isinstance(value, str):
        return str(value).strip()
    if isinstance(value, dict):
        policy = str(value.get("policy") or "").strip()
        if policy:
            return f"policy:{policy}"
    return ""


def _build_channels(build_config: dict[str, Any]) -> dict[str, str]:
    channels: dict[str, str] = {}
    for profile_name, profile_config in dict(build_config or {}).items():
        profile = str(profile_name or "").strip()
        if not profile:
            continue
        config = dict(profile_config or {}) if isinstance(profile_config, dict) else {}
        channel = str(config.get("channel") or "").strip()
        if channel:
            channels[profile] = channel
    return channels


def _default_update_channel(channels: dict[str, str]) -> str:
    for preferred in ("development", "preview", "production"):
        channel = str(channels.get(preferred) or "").strip()
        if channel:
            return channel
    for channel in channels.values():
        value = str(channel or "").strip()
        if value:
            return value
    return ""


def _looks_like_expo_root(root: Path) -> bool:
    if not root.is_dir():
        return False
    package_json = root / "package.json"
    app_json = root / "app.json"
    eas_json = root / "eas.json"
    return package_json.exists() and app_json.exists() and eas_json.exists()


def _workspace_candidate_roots(workspace_path: str) -> list[Path]:
    base = Path(str(workspace_path or "")).expanduser()
    if not base.is_dir():
        return []
    candidates: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        resolved = str(path.resolve())
        if resolved in seen:
            return
        seen.add(resolved)
        if _looks_like_expo_root(path):
            candidates.append(path)

    add(base)
    for container_name in ("apps", "packages", "mobile"):
        container = base / container_name
        if not container.is_dir():
            continue
        for child in container.iterdir():
            if child.is_dir():
                add(child)
    return candidates


def _git_branch_for_project(root: Path, fallback: str = "") -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        branch = str(proc.stdout or "").strip()
        if proc.returncode == 0 and branch:
            return branch
    except Exception:
        pass
    return str(fallback or "").strip()


def _project_context_from_workspace(workspace: dict[str, Any], root: Path) -> ExpoProjectContext:
    app = _app_config(root)
    eas = _eas_config(root)
    pkg = _package_config(root)
    extra = dict(app.get("extra") or {})
    eas_extra = dict(extra.get("eas") or {})
    build_config = dict(eas.get("build") or {})
    build_profiles = [str(name) for name in build_config.keys() if str(name or "").strip()]
    channels = _build_channels(build_config)
    runtime_version = _runtime_version_label(app.get("runtimeVersion"))
    workspace_path = str(workspace.get("path") or "").strip()
    git_branch = _git_branch_for_project(root, str(workspace.get("git_branch") or ""))
    return ExpoProjectContext(
        workspace_id=int(workspace.get("id") or 0) or None,
        workspace_name=str(workspace.get("name") or "").strip() or root.name,
        workspace_path=workspace_path,
        project_root=root.resolve(),
        app_name=str(app.get("name") or pkg.get("name") or root.name).strip() or root.name,
        owner=str(app.get("owner") or "").strip(),
        slug=str(app.get("slug") or pkg.get("name") or root.name).strip() or root.name,
        project_id=str(eas_extra.get("projectId") or "").strip(),
        android_package=str(dict(app.get("android") or {}).get("package") or "").strip(),
        ios_bundle_identifier=str(dict(app.get("ios") or {}).get("bundleIdentifier") or "").strip(),
        build_profiles=build_profiles,
        runtime_version=runtime_version,
        update_channel=str(extra.get("updateChannel") or "").strip() or _default_update_channel(channels),
        channels=channels,
        git_branch=git_branch,
    )


async def discover_expo_projects(
    db,
    *,
    workspace_id: int | None = None,
    limit: int = 8,
) -> list[ExpoProjectContext]:
    workspaces: list[dict[str, Any]] = []
    if workspace_id:
        workspace = _row(await get_project(db, workspace_id))
        if workspace:
            workspaces.append(workspace)
    else:
        rows = await get_projects(db, status="active")
        workspaces.extend(_row(row) for row in rows or [])

    projects: list[ExpoProjectContext] = []
    seen_roots: set[str] = set()
    for workspace in workspaces:
        for root in _workspace_candidate_roots(str(workspace.get("path") or "")):
            resolved = str(root.resolve())
            if resolved in seen_roots:
                continue
            seen_roots.add(resolved)
            projects.append(_project_context_from_workspace(workspace, root))
            if len(projects) >= max(1, limit):
                return projects
    return projects


async def expo_token_state(db, *, owner: str = "") -> dict[str, Any]:
    owner_suffix = _owner_env_suffix(owner)
    owner_setting_key = f"expo_api_token__{owner_suffix.lower()}" if owner_suffix else ""

    if owner_setting_key:
        owner_setting_token = str(await get_setting(db, owner_setting_key) or "").strip()
        if owner_setting_token:
            return {
                "value": owner_setting_token,
                "source": f"setting:{owner_setting_key}",
                "present": True,
                "locked": False,
                "owner": owner,
            }

    setting_token = str(await get_setting(db, "expo_api_token") or "").strip()
    if setting_token:
        return {"value": setting_token, "source": "setting", "present": True, "locked": False, "owner": owner}

    env_candidates: list[str] = []
    if owner_suffix:
        env_candidates.extend([
            f"EXPO_TOKEN__{owner_suffix}",
            f"EXPO_ACCESS_TOKEN__{owner_suffix}",
            f"EXPO_TOKEN_{owner_suffix}",
            f"EXPO_ACCESS_TOKEN_{owner_suffix}",
        ])
    env_candidates.extend(["EXPO_TOKEN", "EXPO_ACCESS_TOKEN"])
    env_token = ""
    env_source = ""
    for env_name in env_candidates:
        candidate = str(os.environ.get(env_name) or "").strip()
        if candidate:
            env_token = candidate
            env_source = env_name
            break
    if env_token:
        return {"value": env_token, "source": f"env:{env_source}", "present": True, "locked": False, "owner": owner}

    vault_candidates: list[str] = []
    if owner_suffix:
        vault_candidates.extend([
            f"EXPO_ACCESS_TOKEN__{owner_suffix}",
            f"EXPO_TOKEN__{owner_suffix}",
            f"EXPO_ACCESS_TOKEN_{owner_suffix}",
            f"EXPO_TOKEN_{owner_suffix}",
        ])
    vault_candidates.extend(("EXPO_ACCESS_TOKEN", "EXPO_TOKEN"))
    status = await vault_secret_status_by_name(db, secret_names=vault_candidates)
    value = str(status.get("value") or "").strip()
    present = bool(status.get("present"))
    unlocked = bool(status.get("unlocked"))
    return {
        "value": value,
        "source": "vault" if value else "",
        "present": present,
        "locked": present and not unlocked,
        "owner": owner,
    }


def _cache_key(*, workspace_id: int | None, limit: int) -> str:
    return f"expo:{workspace_id or 'all'}:{limit}"


def _persisted_cache_path(key: str) -> Path:
    safe_key = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in key)
    return PERSISTED_OVERVIEW_CACHE_DIR / f"{safe_key}.json"


def _persisted_cache_get(key: str) -> dict[str, Any] | None:
    path = _persisted_cache_path(key)
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return None
    try:
        payload = json.loads(raw)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _persisted_cache_put(key: str, payload: dict[str, Any]) -> None:
    path = _persisted_cache_path(key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
    except Exception:
        return


def _cache_get(key: str) -> dict[str, Any] | None:
    record = _OVERVIEW_CACHE.get(key)
    if not record:
        return _persisted_cache_get(key)
    expires_at, payload = record
    if time.time() > expires_at:
        _OVERVIEW_CACHE.pop(key, None)
        return _persisted_cache_get(key)
    return payload


def _cache_put(key: str, payload: dict[str, Any]) -> dict[str, Any]:
    _OVERVIEW_CACHE[key] = (time.time() + OVERVIEW_CACHE_TTL_SECONDS, payload)
    _persisted_cache_put(key, payload)
    return payload


def invalidate_expo_overview_cache() -> None:
    _OVERVIEW_CACHE.clear()


def _cached_fallback_payload(
    cached: dict[str, Any] | None,
    *,
    token_state: dict[str, Any],
) -> dict[str, Any] | None:
    if not cached:
        return None
    payload = json.loads(json.dumps(cached))
    sync_at = _utc_now_iso()
    last_sync_at = str(payload.get("last_sync_at") or payload.get("updated_at") or payload.get("generated_at") or "").strip()
    if token_state.get("locked"):
        status = "degraded"
        summary = "Expo / EAS access is available, but the Axon vault is locked."
        reason = "vault_locked"
    elif not token_state.get("present"):
        status = "degraded"
        summary = "Expo / EAS token is not currently available."
        reason = "token_missing"
    else:
        return payload
    if last_sync_at:
        summary = f"{summary} Showing last successful sync from {last_sync_at}."
    payload["generated_at"] = sync_at
    payload["updated_at"] = sync_at
    payload["status"] = status
    payload["summary"] = summary
    payload["token"] = {
        "present": bool(token_state.get("present")),
        "locked": bool(token_state.get("locked")),
        "source": str(token_state.get("source") or ""),
    }
    payload["stale"] = True
    payload["stale_reason"] = reason
    for project in payload.get("projects") or []:
        if isinstance(project, dict):
            project["stale"] = True
            project["stale_reason"] = reason
    return payload

def _run_eas_cli(
    *,
    project_root: Path,
    token: str = "",
    command: list[str],
    timeout: int = 600,
    expect_json: bool = True,
) -> dict[str, Any]:
    return run_eas_cli(
        project_root=project_root,
        token=token,
        command=command,
        timeout=timeout,
        expect_json=expect_json,
    )


async def _run_eas_cli_async(
    *,
    project_root: Path,
    token: str = "",
    command: list[str],
    timeout: int = 600,
    expect_json: bool = True,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _run_eas_cli,
        project_root=project_root,
        token=token,
        command=command,
        timeout=timeout,
        expect_json=expect_json,
    )


def _iso_from_any(value: Any) -> str:
    text = str(value or "").strip()
    return text


def _sort_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        entries,
        key=lambda item: (
            str(item.get("created_at") or item.get("updated_at") or ""),
            str(item.get("id") or ""),
        ),
        reverse=True,
    )


def _overview_status(projects: list[dict[str, Any]], token_state: dict[str, Any]) -> tuple[str, str]:
    if bool(token_state.get("locked")):
        return "blocked", "Expo / EAS access is available, but the Axon vault is locked."
    if not bool(token_state.get("present")):
        return "blocked", "Add EXPO_ACCESS_TOKEN to the Axon vault to unlock Expo / EAS control."
    statuses = {str(project.get("status") or "").strip().lower() for project in projects}
    if "expo_cli_missing" in statuses and statuses.issubset({"expo_cli_missing"}):
        return "blocked", "Expo / EAS project discovery worked, but Axon cannot run the EAS CLI from this runtime yet."
    if any(status in {"expo_auth_failed", "expo_cli_failed", "expo_account_mismatch", "expo_cli_missing"} for status in statuses):
        return "degraded", "Expo / EAS is connected, but one or more project checks failed."
    if any(status in {"ready"} for status in statuses):
        return "ready", f"Expo / EAS is connected across {len(projects)} project(s)."
    if projects:
        return "degraded", f"Expo / EAS discovered {len(projects)} project(s), but status is incomplete."
    return "idle", "No Expo / EAS projects are linked to active workspaces yet."


def _build_entry(raw: dict[str, Any]) -> dict[str, Any]:
    artifacts = dict(raw.get("artifacts") or {})
    actor = raw.get("actor") or raw.get("initiatingActor") or raw.get("userActor") or {}
    actor_dict = dict(actor) if isinstance(actor, dict) else {}
    error = dict(raw.get("error") or {})
    log_files = [str(item).strip() for item in raw.get("logFiles") or [] if str(item).strip()]
    profile = raw.get("profile") or raw.get("buildProfile")
    return {
        "id": str(raw.get("id") or raw.get("buildId") or raw.get("group") or "").strip(),
        "name": str(raw.get("appName") or profile or raw.get("name") or "").strip(),
        "platform": str(raw.get("platform") or "").strip(),
        "status": str(raw.get("status") or raw.get("buildStatus") or raw.get("state") or "").strip(),
        "created_at": _iso_from_any(raw.get("createdAt") or raw.get("created") or raw.get("updatedAt")),
        "updated_at": _iso_from_any(raw.get("updatedAt") or raw.get("completedAt") or raw.get("finishedAt")),
        "branch": str(raw.get("branch") or raw.get("gitBranch") or "").strip(),
        "message": str(error.get("message") or raw.get("message") or raw.get("gitCommitMessage") or raw.get("commitMessage") or "").strip(),
        "actor": str(actor_dict.get("displayName") or actor_dict.get("username") or "").strip(),
        "url": str(raw.get("webpageUrl") or raw.get("logsUrl") or raw.get("detailsUrl") or (log_files[0] if log_files else "")).strip(),
        "runtime_version": str(raw.get("runtimeVersion") or "").strip(),
        "commit_sha": str(raw.get("gitCommitHash") or "").strip(),
        "artifact_url": str(artifacts.get("buildUrl") or artifacts.get("applicationArchiveUrl") or "").strip(),
        "developer_tool": str(raw.get("developmentClient") or "").strip(),
        "error_code": str(error.get("errorCode") or "").strip(),
        "log_files": log_files,
        "meta": {
            "profile": profile,
            "distribution": raw.get("distribution"),
            "appVersion": raw.get("appVersion"),
            "appBuildVersion": raw.get("appBuildVersion"),
            "channel": raw.get("channel"),
        },
    }


def _update_entry(raw: dict[str, Any]) -> dict[str, Any]:
    actor = raw.get("actor") or raw.get("userActor") or {}
    actor_dict = dict(actor) if isinstance(actor, dict) else {}
    return {
        "id": str(raw.get("id") or raw.get("group") or "").strip(),
        "name": str(raw.get("message") or raw.get("group") or raw.get("branch") or "update").strip(),
        "platform": str(raw.get("platform") or raw.get("platforms") or "").strip(),
        "status": str(raw.get("status") or "published").strip(),
        "created_at": _iso_from_any(raw.get("createdAt") or raw.get("publishedAt") or raw.get("updatedAt")),
        "updated_at": _iso_from_any(raw.get("updatedAt") or raw.get("createdAt")),
        "branch": str(raw.get("branch") or raw.get("channel") or "").strip(),
        "message": str(raw.get("message") or "").strip(),
        "actor": str(actor_dict.get("displayName") or actor_dict.get("username") or "").strip(),
        "url": str(raw.get("link") or raw.get("websiteUrl") or "").strip(),
        "runtime_version": str(raw.get("runtimeVersion") or "").strip(),
        "commit_sha": str(raw.get("gitCommitHash") or "").strip(),
        "artifact_url": "",
        "meta": {
            "channel": raw.get("channel"),
            "group": raw.get("group"),
        },
    }


def _select_project_context(projects: list[ExpoProjectContext], *, workspace_id: int | None, payload: dict[str, Any]) -> ExpoProjectContext:
    explicit_root = str(payload.get("project_root") or "").strip()
    if explicit_root:
        for project in projects:
            if str(project.project_root) == explicit_root:
                return project
    if workspace_id:
        for project in projects:
            if int(project.workspace_id or 0) == int(workspace_id):
                return project
    if projects:
        return projects[0]
    raise ExpoControlError(
        "No Expo / EAS project is linked to the requested workspace yet.",
        outcome="missing_expo_project",
        result_payload={"workspace_id": workspace_id},
    )


async def load_expo_overview(
    db,
    *,
    workspace_id: int | None = None,
    limit: int = 6,
    force_refresh: bool = False,
) -> dict[str, Any]:
    key = _cache_key(workspace_id=workspace_id, limit=limit)
    persisted_fallback = _persisted_cache_get(key)
    if not force_refresh:
        cached = _cache_get(key)
        if cached is not None:
            return cached

    projects = await discover_expo_projects(db, workspace_id=workspace_id, limit=limit)
    project_token_states: dict[str, dict[str, Any]] = {}
    for project in projects:
        owner_key = str(project.owner or "").strip()
        if owner_key not in project_token_states:
            project_token_states[owner_key] = await expo_token_state(db, owner=owner_key)

    whoami_profiles: dict[str, dict[str, Any]] = {}
    whoami_errors: dict[str, dict[str, Any]] = {}
    effective_token_states: dict[str, dict[str, Any]] = {}
    project_cli_states: list[dict[str, Any]] = []
    project_payloads: list[dict[str, Any]] = []
    build_count = 0
    flattened_builds: list[dict[str, Any]] = []
    active_builds: list[dict[str, Any]] = []

    for project in projects:
        cli_runtime = resolve_expo_cli_runtime(project.project_root)
        project_cli_states.append(
            {
                "available": cli_runtime.available,
                "source": cli_runtime.source,
                "command_preview": cli_runtime.command_preview,
            }
        )
        owner_key = str(project.owner or "").strip()
        token_state = project_token_states.get(owner_key) or {"present": False, "locked": False, "source": ""}
        effective_token_state = dict(token_state)
        effective_token = str(token_state.get("value") or "").strip()
        status = "ready"
        latest_builds: list[dict[str, Any]] = []
        latest_updates: list[dict[str, Any]] = []
        project_error: dict[str, Any] | None = None
        whoami_profile = whoami_profiles.get(owner_key)
        whoami_error = whoami_errors.get(owner_key)
        if not cli_runtime.available:
            status = "expo_cli_missing"
            project_error = {
                "summary": cli_runtime.summary,
                "outcome": status,
                "command_preview": cli_runtime.command_preview,
                "cli_source": cli_runtime.source,
            }
        elif not effective_token:
            try:
                session_probe = await _run_eas_cli_async(
                    project_root=project.project_root,
                    token="",
                    command=["whoami"],
                    timeout=120,
                    expect_json=False,
                )
                session_profile = parse_whoami_profile(str(session_probe.get("stdout") or ""))
                if str(session_profile.get("username") or "").strip():
                    effective_token_state = {
                        **effective_token_state,
                        "value": "",
                        "source": "local_cli_session",
                        "present": True,
                        "locked": False,
                        "read_only": True,
                    }
                    token_state = effective_token_state
                    whoami_profile = session_profile
                    whoami_profiles[owner_key] = session_profile
            except ExpoControlError:
                pass
        effective_token_states[owner_key] = dict(effective_token_state)
        if effective_token_state.get("locked"):
            status = "vault_locked"
        elif not effective_token_state.get("present"):
            status = "token_missing"
        else:
            token = effective_token
            if effective_token_state.get("present"):
                if whoami_profile is None and whoami_error is None:
                    try:
                        whoami_result = await _run_eas_cli_async(
                            project_root=project.project_root,
                            token=token,
                            command=["whoami"],
                            timeout=120,
                            expect_json=False,
                        )
                        whoami_profile = parse_whoami_profile(str(whoami_result.get("stdout") or ""))
                        whoami_profiles[owner_key] = whoami_profile
                    except ExpoControlError as exc:
                        whoami_error = {
                            "summary": exc.summary,
                            "outcome": exc.outcome,
                            **dict(exc.result_payload or {}),
                        }
                        whoami_errors[owner_key] = whoami_error
                if whoami_error:
                    status = str(whoami_error.get("outcome") or "expo_cli_failed")
                    project_error = dict(whoami_error)
                elif not whoami_has_project_access(whoami_profile, required_owner=project.owner):
                    status = "expo_account_mismatch"
                    project_error = {
                        "summary": (
                            f"Expo token is authenticated as {whoami_profile.get('username') or 'an unrelated account'}, "
                            f"which does not include access to the owner '{project.owner}'."
                        ),
                        "outcome": status,
                        "required_owner": project.owner,
                        "authenticated_as": whoami_profile.get("username") or "",
                        "authenticated_email": whoami_profile.get("email") or "",
                        "accessible_accounts": list(whoami_profile.get("account_names") or []),
                    }
                else:
                    try:
                        builds_result = await _run_eas_cli_async(
                            project_root=project.project_root,
                            token=token,
                            command=["build:list", "--limit", "5", "--json", "--non-interactive"],
                            timeout=180,
                        )
                        builds_raw = builds_result.get("parsed")
                        if isinstance(builds_raw, list):
                            latest_builds = [_build_entry(dict(item)) for item in builds_raw if isinstance(item, dict)]
                    except ExpoControlError as exc:
                        status = exc.outcome
                        project_error = {
                            "summary": exc.summary,
                            "outcome": exc.outcome,
                            **dict(exc.result_payload or {}),
                        }
                    try:
                        updates_result = await _run_eas_cli_async(
                            project_root=project.project_root,
                            token=token,
                            command=["update:list", "--all", "--limit", "5", "--json", "--non-interactive"],
                            timeout=180,
                        )
                        updates_raw = updates_result.get("parsed")
                        if isinstance(updates_raw, list):
                            latest_updates = [_update_entry(dict(item)) for item in updates_raw if isinstance(item, dict)]
                    except ExpoControlError as exc:
                        project_error = project_error or {
                            "summary": exc.summary,
                            "outcome": exc.outcome,
                            **dict(exc.result_payload or {}),
                        }

        build_count += len(latest_builds)
        flattened_builds.extend(latest_builds)
        project_active_builds = [
            build
            for build in latest_builds
            if str(build.get("status") or "").strip().upper() in {"NEW", "QUEUE", "QUEUED", "IN_QUEUE", "PENDING", "RUNNING", "IN_PROGRESS"}
        ]
        active_builds.extend(project_active_builds)
        project_payloads.append(
            {
                "workspace_id": project.workspace_id,
                "workspace_name": project.workspace_name,
                "workspace_path": project.workspace_path,
                "project_root": str(project.project_root),
                "project_id": project.project_id,
                "project_name": project.app_name,
                "account_name": (
                    str((whoami_profile or {}).get("username") or "").strip()
                    or project.owner
                ),
                "owner": project.owner,
                "slug": project.slug,
                "runtime": "expo",
                "status": status,
                "build_profile": project.build_profiles[0] if project.build_profiles else "",
                "branch": project.git_branch,
                "platform": "android/ios",
                "runtime_version": project.runtime_version,
                "update_channel": project.update_channel,
                "last_build_status": str((latest_builds[0] or {}).get("status") or "").strip() if latest_builds else "",
                "last_build_at": str((latest_builds[0] or {}).get("created_at") or "").strip() if latest_builds else "",
                "last_update_at": str((latest_updates[0] or {}).get("created_at") or "").strip() if latest_updates else "",
                "latest_builds": latest_builds,
                "active_builds": project_active_builds,
                "latest_updates": latest_updates,
                "available_actions": [
                    "expo.project.status",
                    "expo.build.list",
                    "expo.build.android.dev",
                    "expo.build.ios.dev",
                    "expo.update.publish",
                ],
                "meta": {
                    "android_package": project.android_package,
                    "ios_bundle_identifier": project.ios_bundle_identifier,
                    "build_profiles": project.build_profiles,
                    "channels": project.channels,
                    "eas_cli_available": cli_runtime.available,
                    "eas_cli_source": cli_runtime.source,
                    "eas_cli_command_preview": cli_runtime.command_preview,
                    "token_source": effective_token_state.get("source") or "",
                    "auth_mode": "session" if effective_token_state.get("source") == "local_cli_session" else "token",
                    "authenticated_account": str((whoami_profile or {}).get("username") or "").strip(),
                    "authenticated_email": str((whoami_profile or {}).get("email") or "").strip(),
                    "accessible_accounts": list((whoami_profile or {}).get("account_names") or []),
                },
                "error": project_error,
            }
        )

    token_present = any(bool(state.get("present")) for state in effective_token_states.values()) or any(
        str(project.get("status") or "") == "ready" for project in project_payloads
    )
    token_locked = bool(effective_token_states) and all(
        bool(state.get("locked")) for state in effective_token_states.values()
    )
    overview_token_state = {
        "present": token_present,
        "locked": token_locked,
        "source": ",".join(
            sorted(
                {
                    str(state.get("source") or "")
                    for state in effective_token_states.values()
                    if str(state.get("source") or "").strip()
                }
            )
        ),
    }
    overview_cli_state = {
        "available": any(bool(state.get("available")) for state in project_cli_states),
        "source": ",".join(
            sorted(
                {
                    str(state.get("source") or "")
                    for state in project_cli_states
                    if str(state.get("source") or "").strip()
                }
            )
        ),
        "command_preview": next(
            (
                str(state.get("command_preview") or "")
                for state in project_cli_states
                if str(state.get("command_preview") or "").strip()
            ),
            "",
        ),
    }
    if persisted_fallback is not None:
        blocked_statuses = {str(project.get("status") or "").strip().lower() for project in project_payloads}
        if blocked_statuses and blocked_statuses.issubset({"vault_locked", "token_missing"}):
            fallback_payload = _cached_fallback_payload(persisted_fallback, token_state=overview_token_state)
            if fallback_payload is not None:
                return _cache_put(key, fallback_payload)
    status, summary = _overview_status(project_payloads, overview_token_state)
    flattened_builds = _sort_entries(flattened_builds)[:10]
    sync_at = _utc_now_iso()
    payload = {
        "generated_at": sync_at,
        "updated_at": sync_at,
        "last_sync_at": sync_at,
        "status": status,
        "summary": summary,
        "token": {
            "present": bool(overview_token_state.get("present")),
            "locked": bool(overview_token_state.get("locked")),
            "source": str(overview_token_state.get("source") or ""),
        },
        "cli": overview_cli_state,
        "project_count": len(project_payloads),
        "build_count": build_count,
        "projects": project_payloads,
        "builds": flattened_builds,
        "active_builds": _sort_entries(active_builds)[:10],
    }
    return _cache_put(key, payload)


async def prepare_expo_action_request(
    db,
    *,
    action_type: str,
    workspace_id: int | None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(payload or {})
    projects = await discover_expo_projects(db, workspace_id=workspace_id, limit=8)
    project = _select_project_context(projects, workspace_id=workspace_id, payload=payload)
    auth = await resolve_project_action_auth(
        db,
        project,
        expo_token_state_fn=expo_token_state,
        run_eas_cli_async_fn=_run_eas_cli_async,
    )

    message = str(payload.get("message") or "").strip()
    branch = str(payload.get("branch") or project.git_branch or "development").strip() or "development"

    if action_type == "expo.build.android.dev":
        return {
            "auth": auth,
            "payload": {
                "workspace_id": workspace_id,
                "project_root": str(project.project_root),
                "platform": "android",
                "profile": str(payload.get("profile") or "development"),
                "message": message or f"Axon Android dev build for {project.app_name}",
            },
            "title": "Android dev build",
            "summary": f"Start an Android development build for {project.app_name}.",
        }
    if action_type == "expo.build.ios.dev":
        return {
            "auth": auth,
            "payload": {
                "workspace_id": workspace_id,
                "project_root": str(project.project_root),
                "platform": "ios",
                "profile": str(payload.get("profile") or "development"),
                "message": message or f"Axon iOS dev build for {project.app_name}",
            },
            "title": "iOS dev build",
            "summary": f"Start an iOS development build for {project.app_name}.",
        }
    if action_type == "expo.update.publish":
        return {
            "auth": auth,
            "payload": {
                "workspace_id": workspace_id,
                "project_root": str(project.project_root),
                "branch": branch,
                "message": message or f"Axon OTA publish for {project.app_name}",
                "platform": str(payload.get("platform") or "all"),
            },
            "title": "Publish update",
            "summary": f"Publish an Expo update to {branch} for {project.app_name}.",
        }
    if action_type in {"expo.project.status", "expo.build.list"}:
        return {
            "auth": auth,
            "payload": {
                "workspace_id": workspace_id,
                "project_root": str(project.project_root),
            },
            "title": "Expo status" if action_type == "expo.project.status" else "Expo builds",
            "summary": f"Inspect Expo / EAS status for {project.app_name}.",
        }
    raise ExpoControlError(
        f"Unsupported Expo action: {action_type}",
        outcome="unsupported_action",
        result_payload={"action_type": action_type},
    )


async def execute_expo_status_action(
    db,
    *,
    workspace_id: int | None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prepared = await prepare_expo_action_request(db, action_type="expo.project.status", workspace_id=workspace_id, payload=payload)
    overview = await load_expo_overview(db, workspace_id=workspace_id, limit=4, force_refresh=True)
    project_root = str(dict(prepared.get("payload") or {}).get("project_root") or "")
    project = next((item for item in overview.get("projects", []) if str(item.get("project_root") or "") == project_root), None)
    if not project:
        raise ExpoControlError(
            "Expo project status is not available for the selected workspace.",
            outcome="missing_expo_project",
            result_payload={"workspace_id": workspace_id},
        )
    return {
        "status": str(project.get("status") or overview.get("status") or "ready"),
        "updated_at": str(overview.get("updated_at") or overview.get("generated_at") or _utc_now_iso()),
        "label": str(project.get("project_name") or project.get("slug") or "Expo project"),
        "project": project,
        "summary": f"{project.get('project_name') or 'Expo project'} · {project.get('last_build_status') or project.get('status') or 'ready'}",
        **project,
    }


async def execute_expo_build_list_action(
    db,
    *,
    workspace_id: int | None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = await execute_expo_status_action(db, workspace_id=workspace_id, payload=payload)
    project = dict(status.get("project") or {})
    return {
        "project": project,
        "builds": list(project.get("latest_builds") or []),
        "status": str(project.get("status") or "ready"),
        "updated_at": str(project.get("last_build_at") or status.get("updated_at") or _utc_now_iso()),
        "summary": f"{len(project.get('latest_builds') or [])} recent Expo build(s) loaded for {project.get('project_name') or 'the project'}.",
    }


async def execute_expo_build_action(
    db,
    *,
    action_type: str,
    workspace_id: int | None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prepared = await prepare_expo_action_request(db, action_type=action_type, workspace_id=workspace_id, payload=payload)
    run_payload = dict(prepared.get("payload") or {})
    auth = dict(prepared.get("auth") or {})
    project_root = Path(str(run_payload["project_root"]))
    result = await _run_eas_cli_async(
        project_root=project_root,
        token=str(auth.get("token") or "").strip(),
        command=[
            "build",
            "--platform", str(run_payload.get("platform") or "android"),
            "--profile", str(run_payload.get("profile") or "development"),
            "--message", str(run_payload.get("message") or ""),
            "--json",
            "--non-interactive",
        ],
        timeout=900,
    )
    invalidate_expo_overview_cache()
    parsed = result.get("parsed")
    build = _build_entry(dict(parsed)) if isinstance(parsed, dict) else {}
    return {
        "project_root": run_payload.get("project_root"),
        "build": build or parsed,
        "command_preview": result.get("command_preview"),
        "summary": f"Expo {run_payload.get('platform')} development build started for {Path(str(run_payload['project_root'])).name}.",
    }


async def execute_expo_update_publish(
    db,
    *,
    workspace_id: int | None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prepared = await prepare_expo_action_request(db, action_type="expo.update.publish", workspace_id=workspace_id, payload=payload)
    run_payload = dict(prepared.get("payload") or {})
    auth = dict(prepared.get("auth") or {})
    project_root = Path(str(run_payload["project_root"]))
    result = await _run_eas_cli_async(
        project_root=project_root,
        token=str(auth.get("token") or "").strip(),
        command=[
            "update",
            "--branch", str(run_payload.get("branch") or "development"),
            "--message", str(run_payload.get("message") or ""),
            "--platform", str(run_payload.get("platform") or "all"),
            "--json",
            "--non-interactive",
        ],
        timeout=900,
    )
    invalidate_expo_overview_cache()
    parsed = result.get("parsed")
    update_entry = _update_entry(dict(parsed)) if isinstance(parsed, dict) else parsed
    return {
        "project_root": run_payload.get("project_root"),
        "update": update_entry,
        "command_preview": result.get("command_preview"),
        "summary": f"Expo update publish started for branch {run_payload.get('branch') or 'development'}.",
    }
