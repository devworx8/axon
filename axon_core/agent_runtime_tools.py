from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

from . import image_generation, pdf_generation


def normalize_tool_args(name: str, args: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(args or {})

    if name == "shell_cmd":
        raw_cmd = str(normalized.get("cmd") or "").strip()
        if raw_cmd and not normalized.get("cwd"):
            cd_prefix = re.match(r"""^\s*cd\s+(['"]?)(.+?)\1\s*&&\s*(.+)$""", raw_cmd)
            if cd_prefix:
                normalized["cwd"] = cd_prefix.group(2).strip()
                normalized["cmd"] = cd_prefix.group(3).strip()
        if not normalized.get("cwd"):
            for alias in ("dir", "directory", "workdir", "working_dir", "path"):
                if normalized.get(alias):
                    normalized["cwd"] = normalized.pop(alias)
                    break
        for alias in ("dir", "directory", "workdir", "working_dir", "path"):
            normalized.pop(alias, None)
        return {key: value for key, value in normalized.items() if key in {"cmd", "cwd", "timeout"}}

    if name in {"git_status", "list_dir", "read_file"}:
        if not normalized.get("path"):
            for alias in ("cwd", "dir", "directory", "repo", "repository", "file"):
                if normalized.get(alias):
                    normalized["path"] = normalized.pop(alias)
                    break
        for alias in ("cwd", "dir", "directory", "repo", "repository", "file"):
            normalized.pop(alias, None)
        return {key: value for key, value in normalized.items() if key in {"path", "max_kb"}}

    if name in {"search_code", "grep_code", "glob_files"}:
        if not normalized.get("path"):
            for alias in ("cwd", "dir", "directory", "repo", "repository"):
                if normalized.get(alias):
                    normalized["path"] = normalized.pop(alias)
                    break
        if not normalized.get("pattern"):
            for alias in ("query", "text", "search", "term"):
                if normalized.get(alias):
                    normalized["pattern"] = normalized.pop(alias)
                    break
        for alias in ("cwd", "dir", "directory", "repo", "repository", "query", "text", "search", "term"):
            normalized.pop(alias, None)
        return {key: value for key, value in normalized.items() if key in {"pattern", "path", "glob"}}

    if name in {"write_file", "create_file", "append_file", "delete_file"}:
        if not normalized.get("path"):
            for alias in ("file", "target", "destination"):
                if normalized.get(alias):
                    normalized["path"] = normalized.pop(alias)
                    break
        if name != "delete_file" and not normalized.get("content"):
            for alias in ("text", "body"):
                if normalized.get(alias):
                    normalized["content"] = normalized.pop(alias)
                    break
        for alias in ("file", "target", "destination", "text", "body"):
            normalized.pop(alias, None)
        return {key: value for key, value in normalized.items() if key in {"path", "content"}}

    if name == "edit_file":
        if not normalized.get("path"):
            for alias in ("file", "target", "destination"):
                if normalized.get(alias):
                    normalized["path"] = normalized.pop(alias)
                    break
        if not normalized.get("old_string"):
            for alias in ("old", "old_text", "find", "from"):
                if normalized.get(alias):
                    normalized["old_string"] = normalized.pop(alias)
                    break
        if not normalized.get("new_string"):
            for alias in ("new", "new_text", "replace", "to"):
                if normalized.get(alias):
                    normalized["new_string"] = normalized.pop(alias)
                    break
        for alias in ("file", "target", "destination", "old", "old_text", "find", "from", "new", "new_text", "replace", "to"):
            normalized.pop(alias, None)
        return {key: value for key, value in normalized.items() if key in {"path", "old_string", "new_string", "replace_all"}}

    if name == "generate_pdf":
        if not normalized.get("title"):
            for alias in ("filename", "name", "document_title"):
                if normalized.get(alias):
                    normalized["title"] = normalized.pop(alias)
                    break
        if not normalized.get("content"):
            for alias in ("body", "text", "markdown"):
                if normalized.get(alias):
                    normalized["content"] = normalized.pop(alias)
                    break
        return {
            key: value
            for key, value in normalized.items()
            if key in {"title", "subtitle", "author", "content", "sections", "output_path"}
        }

    if name == "generate_image":
        if not normalized.get("title"):
            for alias in ("name", "filename"):
                if normalized.get(alias):
                    normalized["title"] = normalized.pop(alias)
                    break
        return {
            key: value
            for key, value in normalized.items()
            if key in {"prompt", "aspect_ratio", "image_size", "workspace_id", "title"}
        }

    if name == "http_get":
        return {key: value for key, value in normalized.items() if key in {"url", "headers"}}

    return normalized


def build_tool_registry(
    *,
    current_agent_runtime_context_fn: Callable[[], dict[str, Any]],
    tool_path_allowed_fn: Callable[[str], bool],
    action_is_allowed_fn: Callable[[dict[str, Any]], bool],
    workspace_root_fn: Callable[[], str],
    active_workspace_root_fn: Callable[[], str],
    effective_allowed_cmds_fn: Callable[[], set[str]],
    build_command_approval_action: Callable[..., dict[str, Any]],
    build_edit_approval_action: Callable[..., dict[str, Any]],
    normalize_command_preview: Callable[[str], str],
    db_path: Path,
    spawn_subagent_fn: Callable[[str, str], str] | None = None,
) -> dict[str, Callable[..., str]]:
    def _runtime_workspace_id() -> int | None:
        candidate = current_agent_runtime_context_fn().get("workspace_id")
        if candidate is None:
            return None
        try:
            return int(candidate)
        except (TypeError, ValueError):
            return None

    def _file_approval_action(operation: str, resolved: str) -> dict[str, Any]:
        return build_edit_approval_action(
            operation,
            resolved,
            workspace_id=_runtime_workspace_id(),
            session_id=str(current_agent_runtime_context_fn().get("agent_session_id") or ""),
            workspace_root=active_workspace_root_fn(),
        )

    def _tool_read_file(path: str, max_kb: int = 32) -> str:
        resolved = os.path.realpath(os.path.expanduser(path))
        if not tool_path_allowed_fn(resolved):
            approval_action = _file_approval_action("read", resolved)
            if not action_is_allowed_fn(approval_action):
                return f"BLOCKED_EDIT:read:{resolved}"
        if not os.path.exists(resolved):
            return f"ERROR: File not found: {resolved}"
        if os.path.isdir(resolved):
            return f"ERROR: {resolved} is a directory - use list_dir."
        size = os.path.getsize(resolved)
        if size > max_kb * 1024:
            return f"ERROR: File too large ({size // 1024}KB > {max_kb}KB limit). Use head/tail or search_code."
        try:
            with open(resolved, encoding="utf-8", errors="replace") as handle:
                content = handle.read()
            return f"📁 {resolved} ({size} bytes)\n{content}"
        except PermissionError:
            return f"ERROR: Permission denied: {resolved}"

    def _tool_list_dir(path: str = "~") -> str:
        resolved = os.path.realpath(os.path.expanduser(path))
        if not tool_path_allowed_fn(resolved):
            approval_action = _file_approval_action("list", resolved)
            if not action_is_allowed_fn(approval_action):
                return f"BLOCKED_EDIT:list:{resolved}"
        if not os.path.exists(resolved):
            return f"ERROR: Path not found: {resolved}"
        if not os.path.isdir(resolved):
            return f"ERROR: {resolved} is a file - use read_file."
        try:
            entries = sorted(os.scandir(resolved), key=lambda entry: (entry.is_file(), entry.name.lower()))
            lines = [
                f"{'DIR ' if entry.is_dir() else 'FILE'} {entry.name}"
                for entry in entries
                if not entry.name.startswith(".")
            ]
            return f"📁 {resolved}\n" + "\n".join(lines[:100])
        except PermissionError:
            return f"ERROR: Permission denied: {resolved}"

    def _tool_shell_cmd(cmd: str, cwd: str = "", timeout: int = 15) -> str:
        try:
            parts = shlex.split(cmd)
        except ValueError as exc:
            return f"ERROR: Invalid command: {exc}"
        if not parts:
            return "ERROR: Empty command."
        base_cmd = os.path.basename(parts[0])
        allowed_cmds = effective_allowed_cmds_fn()
        if base_cmd not in allowed_cmds:
            return f"ERROR: Command '{base_cmd}' is not in the allowed list. Allowed: {', '.join(sorted(allowed_cmds))}"
        work_dir = os.path.realpath(os.path.expanduser(cwd)) if cwd else workspace_root_fn()
        if not tool_path_allowed_fn(work_dir):
            return "ERROR: cwd must be within the allowed directories."
        normalized = normalize_command_preview(cmd)
        lowered = normalized.lower()
        read_only_git_prefixes = (
            "git status",
            "git diff",
            "git log",
            "git show",
            "git branch",
            "git rev-parse",
            "git remote",
            "git ls-files",
        )
        requires_approval = (
            (lowered.startswith("git ") and not any(lowered == prefix or lowered.startswith(prefix + " ") for prefix in read_only_git_prefixes))
            or lowered.startswith("gh ")
            or base_cmd in {"rm", "chmod", "ln"}
        )
        if requires_approval:
            approval_action = build_command_approval_action(
                normalized,
                cwd=work_dir,
                workspace_id=_runtime_workspace_id(),
                session_id=str(current_agent_runtime_context_fn().get("agent_session_id") or ""),
            )
            if not action_is_allowed_fn(approval_action):
                return f"BLOCKED_CMD:{base_cmd}:{normalized}"
        try:
            result = subprocess.run(
                parts,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=work_dir,
            )
            output = (result.stdout + result.stderr).strip()
            if len(output) > 4096:
                output = output[:4096] + f"\n... (truncated, total {len(output)} chars)"
            return output or "(no output)"
        except subprocess.TimeoutExpired:
            return f"ERROR: Command timed out after {timeout}s."
        except FileNotFoundError:
            return f"ERROR: Command not found: {parts[0]}"
        except Exception as exc:
            return f"ERROR: {exc}"

    def _tool_git_status(path: str = "~") -> str:
        resolved = os.path.realpath(os.path.expanduser(path))
        if not tool_path_allowed_fn(resolved):
            approval_action = _file_approval_action("git_status", resolved)
            if not action_is_allowed_fn(approval_action):
                return f"BLOCKED_EDIT:git_status:{resolved}"
        if not os.path.exists(resolved):
            return f"ERROR: Path not found: {resolved}"
        status = _tool_shell_cmd("git status --short", cwd=resolved)
        log = _tool_shell_cmd("git log --oneline -10", cwd=resolved)
        branch = _tool_shell_cmd("git branch --show-current", cwd=resolved)
        return f"Branch: {branch.strip()}\n\nStatus:\n{status}\n\nRecent commits:\n{log}"

    def _tool_search_code(
        pattern: str,
        path: str = "~",
        glob: str = "*.py *.ts *.tsx *.js *.jsx",
    ) -> str:
        resolved = os.path.realpath(os.path.expanduser(path))
        if not tool_path_allowed_fn(resolved):
            approval_action = _file_approval_action("search", resolved)
            if not action_is_allowed_fn(approval_action):
                return f"BLOCKED_EDIT:search:{resolved}"
        includes = " ".join(f"--include={item}" for item in glob.split())
        cmd = f"grep -rn --max-count=3 {includes} -l {shlex.quote(pattern)} {shlex.quote(resolved)}"
        result = _tool_shell_cmd(cmd)
        return result[:3000] if len(result) > 3000 else result

    def _tool_write_file(path: str, content: str) -> str:
        resolved = os.path.realpath(os.path.expanduser(path))
        approval_action = _file_approval_action("write", resolved)
        if not action_is_allowed_fn(approval_action):
            return f"BLOCKED_EDIT:write:{resolved}"
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        try:
            with open(resolved, "w", encoding="utf-8") as handle:
                handle.write(content)
            return f"📁 Written {len(content)} bytes to {resolved}"
        except PermissionError:
            return f"ERROR: Permission denied: {resolved}"

    def _tool_create_file(path: str, content: str = "") -> str:
        resolved = os.path.realpath(os.path.expanduser(path))
        approval_action = _file_approval_action("create", resolved)
        if not action_is_allowed_fn(approval_action):
            return f"BLOCKED_EDIT:create:{resolved}"
        if os.path.exists(resolved):
            return f"ERROR: File already exists: {resolved}"
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        try:
            with open(resolved, "w", encoding="utf-8") as handle:
                handle.write(content)
            return f"📁 Created {resolved}"
        except PermissionError:
            return f"ERROR: Permission denied: {resolved}"

    def _tool_append_file(path: str, content: str) -> str:
        resolved = os.path.realpath(os.path.expanduser(path))
        approval_action = _file_approval_action("append", resolved)
        if not action_is_allowed_fn(approval_action):
            return f"BLOCKED_EDIT:append:{resolved}"
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        try:
            with open(resolved, "a", encoding="utf-8") as handle:
                handle.write(content)
            return f"📁 Appended {len(content)} bytes to {resolved}"
        except PermissionError:
            return f"ERROR: Permission denied: {resolved}"

    def _tool_delete_file(path: str) -> str:
        resolved = os.path.realpath(os.path.expanduser(path))
        approval_action = _file_approval_action("delete", resolved)
        if not action_is_allowed_fn(approval_action):
            return f"BLOCKED_EDIT:delete:{resolved}"
        if not os.path.exists(resolved):
            return f"ERROR: File not found: {resolved}"
        if os.path.isdir(resolved):
            return f"ERROR: {resolved} is a directory - delete_file only removes files."
        try:
            os.remove(resolved)
            return f"🗑 Deleted {resolved}"
        except PermissionError:
            return f"ERROR: Permission denied: {resolved}"

    def _tool_edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
        resolved = os.path.realpath(os.path.expanduser(path))
        approval_action = _file_approval_action("edit", resolved)
        if not action_is_allowed_fn(approval_action):
            return f"BLOCKED_EDIT:edit:{resolved}"
        if not os.path.exists(resolved):
            return f"ERROR: File not found: {resolved}"
        if os.path.isdir(resolved):
            return f"ERROR: {resolved} is a directory - use read_file or list_dir."
        try:
            with open(resolved, encoding="utf-8", errors="replace") as handle:
                content = handle.read()
            matches = content.count(old_string)
            if matches == 0:
                return f"ERROR: old_string not found in {resolved}"
            if matches > 1 and not replace_all:
                return f"ERROR: old_string matched {matches} locations in {resolved}; provide more context or set replace_all."
            updated = content.replace(old_string, new_string) if replace_all else content.replace(old_string, new_string, 1)
            with open(resolved, "w", encoding="utf-8") as handle:
                handle.write(updated)
            return f"📁 Edited {resolved}"
        except PermissionError:
            return f"ERROR: Permission denied: {resolved}"

    def _tool_http_get(url: str, headers: str = "") -> str:
        target = str(url or "").strip()
        if not target.startswith(("http://", "https://")):
            return "ERROR: URL must start with http:// or https://."
        request_headers: dict[str, str] = {}
        for line in str(headers or "").splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            if key.strip():
                request_headers[key.strip()] = value.strip()
        try:
            with httpx.Client(timeout=20.0, follow_redirects=True) as client:
                response = client.get(target, headers=request_headers)
                response.raise_for_status()
            body = response.text
            if len(body) > 6144:
                body = body[:6144] + f"\n... (truncated, total {len(response.text)} chars)"
            return f"[live fetch] {response.url}\n{body}"
        except Exception as exc:
            return f"ERROR: http_get failed: {exc}"

    def _tool_generate_pdf(
        title: str,
        content: str = "",
        sections: list[dict[str, Any]] | None = None,
        subtitle: str = "",
        author: str = "",
        output_path: str = "",
    ) -> str:
        requested_path = str(output_path or "").strip()
        if requested_path:
            resolved_path = os.path.realpath(os.path.expanduser(requested_path))
            if not tool_path_allowed_fn(resolved_path):
                return "ERROR: PDF output path must stay within the allowed directories."
        spec = pdf_generation.pdf_from_dict(
            {
                "title": title,
                "subtitle": subtitle,
                "author": author,
                "content": content,
                "sections": sections or [],
                "output_path": requested_path,
            }
        )
        out_path = pdf_generation.build_pdf(spec)
        return (
            f"Generated PDF: {out_path}\n"
            f"Sections: {len(spec.sections)}\n"
            f"Download: /api/generate/pdf/download?path={out_path}"
        )

    def _tool_generate_image(
        prompt: str,
        aspect_ratio: str = "1:1",
        image_size: str = "1K",
        workspace_id: int | None = None,
        title: str = "",
    ) -> str:
        runtime = current_agent_runtime_context_fn()
        provider_id = str(runtime.get("api_provider") or "").strip() or "gemini_gems"
        api_key = str(runtime.get("api_key") or "").strip()
        api_model = str(runtime.get("api_model") or "").strip()
        api_base_url = str(runtime.get("api_base_url") or "").strip()
        if provider_id != "gemini_gems" or not api_key:
            fallback_runtime = image_generation.gemini_runtime_from_settings(db_path)
            if fallback_runtime.get("api_key"):
                provider_id = "gemini_gems"
                api_key = fallback_runtime["api_key"]
                api_model = fallback_runtime["api_model"]
                api_base_url = fallback_runtime["api_base_url"]
        if provider_id != "gemini_gems":
            return (
                f"ERROR: generate_image requires the Gemini image runtime, but the current provider is `{provider_id}`. "
                "Use Agent mode without pinning another model so Axon can auto-route image requests."
            )
        if not api_key:
            return (
                "ERROR: No Gemini API key is active for image generation. "
                "Configure Gemini in Settings or unlock the vault before retrying."
            )
        resolved_workspace_id = workspace_id
        if resolved_workspace_id is None:
            candidate = runtime.get("workspace_id")
            resolved_workspace_id = int(candidate) if str(candidate or "").strip().isdigit() else None
        artifact = image_generation.generate_and_store_image(
            db_path=db_path,
            prompt=prompt,
            api_key=api_key,
            api_model=api_model,
            api_base_url=api_base_url,
            aspect_ratio=aspect_ratio,
            image_size=image_size,
            title=title,
            workspace_id=resolved_workspace_id,
        )
        return (
            f"Generated image resource #{artifact.resource_id}: {artifact.title}\n"
            f"Path: {artifact.path}\n"
            f"Content URL: {artifact.content_url}\n"
            f"Summary: {artifact.summary}"
        )

    registry: dict[str, Callable[..., str]] = {
        "read_file": _tool_read_file,
        "list_dir": _tool_list_dir,
        "shell_cmd": _tool_shell_cmd,
        "git_status": _tool_git_status,
        "search_code": _tool_search_code,
        "create_file": _tool_create_file,
        "append_file": _tool_append_file,
        "delete_file": _tool_delete_file,
        "edit_file": _tool_edit_file,
        "write_file": _tool_write_file,
        "http_get": _tool_http_get,
        "generate_pdf": _tool_generate_pdf,
        "generate_image": _tool_generate_image,
    }
    if spawn_subagent_fn is not None:
        registry["spawn_subagent"] = spawn_subagent_fn
    return registry


__all__ = ["build_tool_registry", "normalize_tool_args"]
