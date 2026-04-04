"""Auto-session prompt and receipt helpers extracted from server.py."""
from __future__ import annotations


def auto_session_prompt(message: str, session_meta: dict) -> str:
    workspace_name = str(session_meta.get("workspace_name") or session_meta.get("source_name") or "workspace")
    lines = [
        f"Continue this request inside the current Axon Auto sandbox for {workspace_name}.",
        "",
        "You are in Axon Auto mode inside an isolated git worktree sandbox.",
        f"Sandbox path: {session_meta.get('sandbox_path')}",
        f"Source workspace: {session_meta.get('source_path')}",
        "",
        "Rules:",
        "- Only inspect and edit files inside the sandbox path.",
        "- Do not modify the source workspace directly. Source changes are only applied through the Auto session Apply action.",
        "- Keep working autonomously until the request is complete or clearly blocked.",
        "- Treat routine edits and local shell work inside the sandbox as pre-approved.",
        "- If you hit a real blocker, explain it with tool-backed receipts instead of guessing.",
        "- End with a concise checkpoint using these exact sections:",
        "  Verified In This Run",
        "  Inferred From Repo State",
        "  Not Yet Verified",
        "  Next Action Not Yet Taken",
        "",
        "User request:",
        message.strip(),
    ]
    return "\n".join(lines).strip()


def auto_runtime_summary(ai: dict, *, provider_registry_module, path_cls) -> dict[str, str]:
    backend = str(ai.get("backend") or "").strip().lower()
    if backend == "api":
        provider_id = str(ai.get("api_provider") or "").strip().lower()
        provider = provider_registry_module.PROVIDER_BY_ID.get(provider_id)
        return {
            "backend": backend,
            "label": provider.label if provider else (provider_id or "API"),
            "model": str(ai.get("api_model") or ""),
        }
    if backend == "cli":
        cli_path = str(ai.get("cli_path") or "").strip()
        binary = path_cls(cli_path).name.lower() if cli_path else ""
        label = "Codex CLI" if binary == "codex" else "Claude CLI" if binary == "claude" else "CLI Runtime"
        return {
            "backend": backend,
            "label": label,
            "model": str(ai.get("cli_model") or ""),
            "binary": cli_path,
        }
    return {
        "backend": "ollama",
        "label": "Local Ollama",
        "model": str(ai.get("ollama_model") or ""),
    }


def auto_tool_command(tool_name: str, tool_args: dict) -> tuple[str, str, str]:
    name = str(tool_name or "").strip()
    args = tool_args or {}
    if name in {"shell_cmd", "shell_bg", "shell_bg_check"}:
        command = str(args.get("cmd") or args.get("command") or args.get("check") or "").strip()
        cwd = str(args.get("cwd") or "").strip()
        return command, cwd, command
    if name == "git_status":
        cwd = str(args.get("cwd") or args.get("path") or "").strip()
        return "git status", cwd, "git status"
    if name == "git_diff":
        cwd = str(args.get("cwd") or args.get("path") or "").strip()
        target = str(args.get("path") or "").strip()
        label = "git diff" if not target else f"git diff {target}"
        return label, cwd, label
    if name == "read_file":
        target = str(args.get("path") or "").strip()
        return "", "", f"read_file {target}".strip()
    if name == "edit_file":
        target = str(args.get("path") or "").strip()
        return "", "", f"edit_file {target}".strip()
    if name == "list_files":
        target = str(args.get("path") or "").strip()
        return "", "", f"list_files {target}".strip()
    return "", "", name or "tool"


def is_verification_command(
    tool_name: str,
    tool_args: dict,
    *,
    auto_tool_command_fn,
) -> bool:
    command, _cwd, label = auto_tool_command_fn(tool_name, tool_args)
    haystack = f"{command} {label}".lower()
    verification_terms = (
        " test",
        "test ",
        "pytest",
        "jest",
        "vitest",
        "build",
        "tsc",
        "typecheck",
        "lint",
        "check",
        "ruff",
        "mypy",
        "go test",
        "cargo test",
        "phpunit",
        "next build",
        "npm run build",
        "npm run test",
        "pnpm build",
        "pnpm test",
        "yarn build",
        "yarn test",
    )
    return any(term in haystack for term in verification_terms)


def auto_receipt_summary(result: str) -> str:
    text = str(result or "").strip()
    if not text:
        return ""
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first_line[:220]
