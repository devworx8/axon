"""Workspace-scoped live preview sessions for Axon Console."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import error as _urlerror, request as _urlrequest

SESSION_ROOT = Path.home() / ".devbrain" / "live_preview_sessions"
SESSION_META = ".axon-preview.json"
_SESSION_PROCESSES: dict[str, subprocess.Popen] = {}


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slugify(value: str, max_len: int = 48) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return (text or "preview")[:max_len].strip("-") or "preview"


def _scope_key(workspace_id: int | None = None, auto_session_id: str = "") -> str:
    auto_session_id = str(auto_session_id or "").strip()
    if auto_session_id:
        return f"auto-{auto_session_id}"
    if workspace_id:
        return f"workspace-{int(workspace_id)}"
    raise ValueError("A workspace_id or auto_session_id is required for a preview session.")


def _find_existing_session_dir(scope_key: str) -> Path | None:
    if not SESSION_ROOT.exists():
        return None
    matches = sorted(SESSION_ROOT.glob(f"{_slugify(scope_key)}-*"))
    return matches[0] if matches else None


def session_dir(scope_key: str, title: str = "") -> Path:
    existing = _find_existing_session_dir(scope_key)
    if existing:
        return existing
    return SESSION_ROOT / f"{_slugify(scope_key)}-{_slugify(title)}"


def session_meta_path(scope_key: str, title: str = "") -> Path:
    return session_dir(scope_key, title) / SESSION_META


def read_preview_session(scope_key: str, title: str = "") -> dict[str, Any] | None:
    meta_path = session_meta_path(scope_key, title)
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_preview_session(meta: dict[str, Any]) -> dict[str, Any]:
    scope_key = str(meta.get("scope_key") or "").strip()
    if not scope_key:
        raise ValueError("Preview session metadata requires scope_key.")
    title = str(meta.get("title") or meta.get("workspace_name") or "preview")
    target_dir = Path(meta.get("session_dir") or session_dir(scope_key, title))
    target_dir.mkdir(parents=True, exist_ok=True)
    meta["session_dir"] = str(target_dir)
    meta["updated_at"] = _now_iso()
    (target_dir / SESSION_META).write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    return meta


def _load_manifest(workspace_path: Path) -> dict[str, Any]:
    manifest_path = workspace_path / "package.json"
    if not manifest_path.is_file():
        return {}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _package_manager(workspace_path: Path) -> str:
    if (workspace_path / "pnpm-lock.yaml").is_file():
        return "pnpm"
    if (workspace_path / "yarn.lock").is_file():
        return "yarn"
    if (workspace_path / "bun.lock").is_file() or (workspace_path / "bun.lockb").is_file():
        return "bun"
    return "npm"


def _free_port(preferred: int) -> int:
    for port in range(max(1024, preferred), max(1024, preferred) + 80):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free port available for live preview.")


def _preferred_port(workspace_id: int | None = None, auto_session_id: str = "") -> int:
    if auto_session_id:
        seed = sum(ord(ch) for ch in str(auto_session_id))
        return 3400 + (seed % 300)
    return 3000 + (int(workspace_id or 0) % 200)


def _framework_hint(manifest: dict[str, Any]) -> str:
    deps = {}
    deps.update(manifest.get("dependencies") or {})
    deps.update(manifest.get("devDependencies") or {})
    keys = {str(k).lower() for k in deps}
    if "expo" in keys:
        return "expo"
    if "next" in keys:
        return "next"
    if "vite" in keys:
        return "vite"
    if "react-scripts" in keys:
        return "cra"
    if "astro" in keys:
        return "astro"
    if "nuxt" in keys:
        return "nuxt"
    return "generic"


def _command_preview(parts: list[str]) -> str:
    return " ".join(str(part) for part in parts)


def _local_bin(repo: Path, name: str, source_repo: Path | None = None) -> str:
    candidate = repo / "node_modules" / ".bin" / name
    if candidate.is_file():
        return str(candidate)
    if source_repo:
        fallback = source_repo / "node_modules" / ".bin" / name
        if fallback.is_file():
            return str(fallback)
    return name


def _ensure_dependency_link(repo: Path, source_repo: Path | None = None) -> None:
    if (repo / "node_modules").exists():
        return
    if not source_repo:
        return
    source_modules = source_repo / "node_modules"
    target_modules = repo / "node_modules"
    if not source_modules.exists() or target_modules.exists():
        return
    try:
        target_modules.symlink_to(source_modules, target_is_directory=True)
    except Exception:
        return


def _replace_path(target: Path, source: Path) -> None:
    if target.is_symlink() or target.is_file():
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(target)
    if source.is_dir():
        shutil.copytree(source, target, symlinks=True)
    else:
        shutil.copy2(source, target)


def _ensure_expo_dependency_layout(repo: Path, source_repo: Path | None = None) -> None:
    if not source_repo or repo == source_repo:
        return
    source_modules = source_repo / "node_modules"
    if not source_modules.is_dir():
        return

    target_modules = repo / "node_modules"
    if target_modules.is_symlink():
        try:
            target_modules.unlink()
        except Exception:
            return
    if not target_modules.exists():
        target_modules.mkdir(parents=True, exist_ok=True)
    if not target_modules.is_dir():
        return

    for source_child in source_modules.iterdir():
        target_child = target_modules / source_child.name
        if target_child.exists() or target_child.is_symlink():
            continue
        try:
            target_child.symlink_to(source_child, target_is_directory=source_child.is_dir())
        except Exception:
            continue

    # Expo Router's route context must resolve from inside the sandbox project root.
    # A whole-directory node_modules symlink causes Expo to build the router context
    # from the source workspace instead of the sandbox, which falls back to the
    # "Welcome to Expo" tutorial page. Keep expo-router local while the rest of
    # node_modules can stay linked back to the source workspace.
    for package_name in ("expo-router",):
        source_package = source_modules / package_name
        if not source_package.exists():
            continue
        target_package = target_modules / package_name
        try:
            if target_package.is_symlink() or not target_package.exists():
                _replace_path(target_package, source_package)
        except Exception:
            continue


def _expo_dependency_layout_stale(repo: Path, source_repo: Path | None = None) -> bool:
    if not source_repo or repo == source_repo:
        return False
    source_modules = source_repo / "node_modules"
    if not source_modules.is_dir():
        return False

    target_modules = repo / "node_modules"
    if target_modules.is_symlink():
        return True
    if not target_modules.is_dir():
        return True

    target_router = target_modules / "expo-router"
    return target_router.is_symlink() or not target_router.exists()


def _should_sync_env_file(path: Path) -> bool:
    name = path.name
    return path.is_file() and (name == ".envrc" or name.startswith(".env"))


def _sync_env_files(repo: Path, source_repo: Path | None = None) -> None:
    if not source_repo or repo == source_repo or not source_repo.exists():
        return
    for source in source_repo.iterdir():
        if not _should_sync_env_file(source):
            continue
        target = repo / source.name
        try:
            if target.is_symlink() and target.resolve() == source.resolve():
                continue
        except Exception:
            pass
        try:
            if target.exists() or target.is_symlink():
                if target.is_dir():
                    continue
                target.unlink()
            target.symlink_to(source)
        except Exception:
            try:
                shutil.copy2(source, target)
            except Exception:
                continue


def infer_preview_launch(
    workspace_path: str,
    *,
    workspace_id: int | None = None,
    auto_session_id: str = "",
    source_workspace_path: str = "",
) -> dict[str, Any]:
    repo = Path(str(workspace_path or "")).expanduser().resolve()
    if not repo.exists():
        raise ValueError(f"Workspace path does not exist: {repo}")
    source_repo = Path(str(source_workspace_path or "")).expanduser().resolve() if source_workspace_path else None
    if source_repo and not source_repo.exists():
        source_repo = None
    manifest = _load_manifest(repo)
    framework = _framework_hint(manifest)
    if framework == "expo":
        _ensure_expo_dependency_layout(repo, source_repo)
    else:
        _ensure_dependency_link(repo, source_repo)
    _sync_env_files(repo, source_repo)
    scripts = manifest.get("scripts") or {}
    port = _free_port(_preferred_port(workspace_id, auto_session_id))
    host = "127.0.0.1"
    env = os.environ.copy()
    env.update(
        {
            "HOST": host,
            "PORT": str(port),
            "BROWSER": "none",
            "CI": "1",
            "AXON_LIVE_PREVIEW": "1",
        }
    )

    manager = _package_manager(repo)
    cmd_parts: list[str]
    script = "dev" if "dev" in scripts else ("start" if "start" in scripts else "")

    if framework == "expo":
        expo_bin = _local_bin(repo, "expo", source_repo)
        cmd_parts = [expo_bin, "start", "--web", "--host", "localhost", "--port", str(port)]
        env["WEB_PORT"] = str(port)
        manager = "expo"
        script = "web"
    elif script:
        if manager == "yarn":
            cmd_parts = ["yarn", script]
        else:
            cmd_parts = [manager, "run", script]

        if framework == "next":
            extras = ["--hostname", host, "--port", str(port)]
        elif framework in {"vite", "astro"}:
            extras = ["--host", host, "--port", str(port)]
        elif framework == "nuxt":
            extras = ["--host", host, "--port", str(port)]
        else:
            extras = []

        if extras:
            if manager == "yarn":
                cmd_parts += extras
            else:
                cmd_parts += ["--", *extras]
    else:
        index_html = repo / "index.html"
        if not index_html.is_file():
            raise ValueError("No package.json dev/start script or static index.html found for this workspace.")
        cmd_parts = ["python3", "-m", "http.server", str(port), "--bind", host]
        framework = "static"
        manager = "python"
        script = "http.server"

    return {
        "workspace_path": str(repo),
        "package_manager": manager,
        "framework": framework,
        "script": script,
        "port": port,
        "host": host,
        "url": f"http://{host}:{port}",
        "command_parts": cmd_parts,
        "command_preview": _command_preview(cmd_parts),
        "env": env,
    }


def _log_indicates_fatal_error(log_tail: str) -> bool:
    text = str(log_tail or "").lower()
    if not text:
        return False
    fatal_markers = (
        "npm err!",
        "error: listen",
        "eaddrinuse",
        "enoent",
        "commanderror:",
        "failed to compile",
        "uncaught exception",
        "traceback (most recent call last)",
    )
    return any(marker in text for marker in fatal_markers)


def _extract_url_from_text(text: str) -> str:
    matches = re.findall(r"https?://(?:localhost|127\.0\.0\.1):\d{2,5}[^\s'\"]*", str(text or ""))
    for url in matches:
        if ":7734" in url:
            continue
        return url.rstrip(").,")
    return ""


def _tail(path: str, limit: int = 4000) -> str:
    if not path:
        return ""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    if len(text) > limit:
        return text[-limit:]
    return text


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def _url_ready(url: str) -> bool:
    if not url:
        return False
    try:
        with _urlrequest.urlopen(url, timeout=1.5) as resp:
            return 200 <= int(resp.status) < 500
    except _urlerror.HTTPError as exc:
        return 200 <= int(exc.code) < 500
    except Exception:
        return False


def _session_log_path(target_dir: Path) -> Path:
    return target_dir / "preview.log"


def refresh_preview_session(scope_key: str, title: str = "") -> dict[str, Any] | None:
    meta = read_preview_session(scope_key, title)
    if not meta:
        return None
    pid = int(meta.get("pid") or 0) or None
    running = _pid_alive(pid)
    log_tail = _tail(str(meta.get("log_path") or ""))
    detected_url = _extract_url_from_text(log_tail)
    if detected_url:
        meta["url"] = detected_url
    healthy = running and _url_ready(str(meta.get("url") or ""))
    if healthy:
        meta["status"] = "running"
        meta["last_error"] = ""
    elif running and _log_indicates_fatal_error(log_tail):
        meta["status"] = "error"
        if not meta.get("last_error"):
            meta["last_error"] = log_tail.splitlines()[-1][:300] if log_tail.splitlines() else "Preview startup failed."
    elif running:
        meta["status"] = "starting"
    else:
        if str(meta.get("status") or "") not in {"stopped", "discarded"}:
            meta["status"] = "stopped"
        if not meta.get("last_error") and log_tail:
            meta["last_error"] = log_tail.splitlines()[-1][:300]
    meta["log_tail"] = log_tail
    meta["healthy"] = healthy
    return write_preview_session(meta)


def get_preview_session(*, workspace_id: int | None = None, auto_session_id: str = "") -> dict[str, Any] | None:
    scope_key = _scope_key(workspace_id, auto_session_id)
    return refresh_preview_session(scope_key)


def _stop_process(meta: dict[str, Any]) -> None:
    pid = int(meta.get("pid") or 0)
    if not pid:
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except Exception:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass


def stop_preview_session(*, workspace_id: int | None = None, auto_session_id: str = "") -> dict[str, Any]:
    meta = get_preview_session(workspace_id=workspace_id, auto_session_id=auto_session_id)
    if not meta:
        raise ValueError("Preview session not found.")
    _stop_process(meta)
    meta["status"] = "stopped"
    return write_preview_session(meta)


def _wait_until_ready(meta: dict[str, Any], timeout_seconds: int = 18) -> dict[str, Any]:
    deadline = datetime.now(UTC).timestamp() + max(4, timeout_seconds)
    while datetime.now(UTC).timestamp() < deadline:
        refreshed = refresh_preview_session(str(meta.get("scope_key") or ""), str(meta.get("title") or "")) or meta
        if refreshed.get("healthy"):
            return refreshed
        if str(refreshed.get("status") or "") == "stopped":
            return refreshed
        import time as _time

        _time.sleep(0.6)
    return refresh_preview_session(str(meta.get("scope_key") or ""), str(meta.get("title") or "")) or meta


def ensure_preview_session(
    *,
    workspace_id: int | None,
    workspace_name: str,
    source_path: str,
    source_workspace_path: str = "",
    auto_session_id: str = "",
    title: str = "",
    restart: bool = False,
) -> dict[str, Any]:
    scope_key = _scope_key(workspace_id, auto_session_id)
    existing = refresh_preview_session(scope_key, title)
    needs_restart = restart
    source_repo = Path(str(source_workspace_path or "")).expanduser().resolve() if source_workspace_path else None
    source_path_resolved = Path(str(source_path or "")).expanduser().resolve()
    preview_framework = _framework_hint(_load_manifest(source_path_resolved))
    if existing and not needs_restart:
        existing_command = str(existing.get("command") or "")
        existing_cwd = str(existing.get("cwd") or "")
        existing_status = str(existing.get("status") or "")
        existing_source_workspace = str(existing.get("source_workspace_path") or "")
        stale_expo_host = "expo start" in existing_command and "--host 127.0.0.1" in existing_command
        wrong_workspace = existing_cwd and Path(existing_cwd).resolve() != source_path_resolved
        missing_auto_source_workspace = bool(auto_session_id) and not existing_source_workspace
        stale_expo_dependencies = preview_framework == "expo" and _expo_dependency_layout_stale(source_path_resolved, source_repo)
        if (
            stale_expo_host
            or wrong_workspace
            or missing_auto_source_workspace
            or stale_expo_dependencies
            or existing_status in {"error", "stopped"}
        ):
            needs_restart = True
    if existing and not needs_restart and str(existing.get("status") or "") in {"running", "starting"}:
        return existing
    if existing and needs_restart:
        _stop_process(existing)

    launch = infer_preview_launch(
        source_path,
        workspace_id=workspace_id,
        auto_session_id=auto_session_id,
        source_workspace_path=source_workspace_path,
    )
    target_dir = session_dir(scope_key, title or workspace_name)
    target_dir.mkdir(parents=True, exist_ok=True)
    log_path = _session_log_path(target_dir)
    log_file = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        launch["command_parts"],
        cwd=launch["workspace_path"],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env=launch["env"],
        text=True,
        start_new_session=True,
    )
    log_file.close()
    _SESSION_PROCESSES[scope_key] = proc

    meta = write_preview_session(
        {
            **(existing or {}),
            "scope_key": scope_key,
            "workspace_id": workspace_id,
            "workspace_name": workspace_name,
            "auto_session_id": str(auto_session_id or ""),
            "title": title or workspace_name or scope_key,
            "source_path": str(source_path),
            "source_workspace_path": str(source_workspace_path or ""),
            "cwd": launch["workspace_path"],
            "command": launch["command_preview"],
            "package_manager": launch["package_manager"],
            "framework": launch["framework"],
            "script": launch["script"],
            "port": launch["port"],
            "url": launch["url"],
            "pid": proc.pid,
            "status": "starting",
            "healthy": False,
            "log_path": str(log_path),
            "log_tail": "",
            "last_error": "",
            "created_at": existing.get("created_at") if existing else _now_iso(),
            "started_at": _now_iso(),
        }
    )
    return _wait_until_ready(meta)


def workspace_env_snapshot(
    workspace_path: str,
    *,
    workspace_id: int | None = None,
    auto_session_id: str = "",
) -> dict[str, Any]:
    preview = get_preview_session(workspace_id=workspace_id, auto_session_id=auto_session_id)
    if not preview:
        return {}
    return {
        "preview_url": str(preview.get("url") or ""),
        "dev_url": str(preview.get("url") or ""),
        "preview_status": str(preview.get("status") or ""),
        "preview_command": str(preview.get("command") or ""),
        "preview_cwd": str(preview.get("cwd") or ""),
        "preview_port": int(preview.get("port") or 0) if preview.get("port") else None,
        "preview_scope_key": str(preview.get("scope_key") or ""),
        "preview_log_tail": str(preview.get("log_tail") or ""),
        "preview_auto_session_id": str(preview.get("auto_session_id") or ""),
    }
