from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Optional
import re as _re

from .agent_paths import DEFAULT_DEVBRAIN_DB_PATH


@dataclass(frozen=True)
class AgentRuntimeDeps:
    tool_registry: dict[str, Callable[..., str]]
    normalize_tool_args: Callable[[str, dict[str, Any]], dict[str, Any]]
    stream_cli: Callable[..., AsyncGenerator[str, None]]
    stream_api_chat: Callable[..., AsyncGenerator[str, None]]
    stream_ollama_chat: Callable[..., AsyncGenerator[str, None]]
    ollama_execution_profile_sync: Callable[..., dict[str, Any]]
    ollama_message_with_images: Callable[[str, Optional[list[str]]], dict[str, Any]]
    api_message_with_images: Callable[[str, Optional[list[str]]], dict[str, Any]]
    cli_message_with_images: Callable[[str, Optional[list[str]]], dict[str, Any]]
    find_cli: Callable[[str], str]
    ollama_default_model: str
    ollama_agent_model: str
    db_path: Path = DEFAULT_DEVBRAIN_DB_PATH


AGENT_TOOL_DEFS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the filesystem. Returns file content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path (absolute or ~-relative)"},
                    "max_kb": {"type": "integer", "description": "Max KB to read (default 32)", "default": 32},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files and directories in a given path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path (default: ~)", "default": "~"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shell_cmd",
            "description": "Run a shell command and return output. For builds or dev servers, set timeout=60 or higher. Use shell_bg for long-running servers that should keep running.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "Shell command to run"},
                    "cwd": {"type": "string", "description": "Working directory (default: home)", "default": "~"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 30, use 60+ for builds)", "default": 30},
                },
                "required": ["cmd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shell_bg",
            "description": "Start a long-running background process (dev servers, watchers). Returns initial output after a few seconds. Use shell_bg_check to see later output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "Command to run in background (e.g. 'npm run dev', 'next dev')"},
                    "cwd": {"type": "string", "description": "Working directory", "default": "~"},
                    "wait_seconds": {"type": "integer", "description": "Seconds to wait for initial output (default 8)", "default": 8},
                },
                "required": ["cmd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shell_bg_check",
            "description": "Check output from a running background process started with shell_bg. Returns recent output and whether it's still running.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pid": {"type": "integer", "description": "Process ID returned by shell_bg"},
                },
                "required": ["pid"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Get git branch, status, and recent commit log for a project directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Project directory path"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search for a pattern in source code files using grep.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Search pattern (regex)"},
                    "path": {"type": "string", "description": "Directory to search in", "default": "~"},
                    "glob": {"type": "string", "description": "File glob patterns (space-separated)", "default": "*.py *.ts *.tsx *.js *.jsx"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to write"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "append_file",
            "description": "Append content to an existing file or create it if missing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to append to"},
                    "content": {"type": "string", "description": "Content to append"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": "Create a new file with optional content. Fails if the file already exists.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to create"},
                    "content": {"type": "string", "description": "Initial file content", "default": ""},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a file safely. Only removes files, not directories.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to delete"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Make targeted edits to a file using find-and-replace. "
                "This is the PREFERRED tool for modifying code — it makes surgical, "
                "reviewable changes instead of rewriting the entire file. "
                "old_string must match exactly (including whitespace/indentation). "
                "If old_string matches multiple locations, provide more context to make it unique."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to edit"},
                    "old_string": {"type": "string", "description": "Exact text to find (must be unique in file)"},
                    "new_string": {"type": "string", "description": "Replacement text"},
                    "replace_all": {"type": "boolean", "description": "Replace all occurrences (default: false)", "default": False},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "show_diff",
            "description": "Show git diff for a file or directory. Use after making edits to review/verify changes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File or directory path to diff"},
                    "staged": {"type": "boolean", "description": "Show staged changes only", "default": False},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_mission",
            "description": "Create a new mission (task) for tracking. Use this when the user asks to create, add, or queue a mission/task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short mission title (e.g. 'Fix login page bug')"},
                    "detail": {"type": "string", "description": "Detailed description of what needs to be done", "default": ""},
                    "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"], "description": "Priority level", "default": "medium"},
                    "project_id": {"type": "integer", "description": "Project ID to link to (optional)"},
                    "due_date": {"type": "string", "description": "Due date in YYYY-MM-DD format (optional)"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_mission",
            "description": "Update an existing mission's status or fields. Use this to mark missions as done, in_progress, or to change details.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mission_id": {"type": "integer", "description": "The mission ID to update"},
                    "status": {"type": "string", "enum": ["open", "in_progress", "done", "cancelled"], "description": "New status"},
                    "title": {"type": "string", "description": "Updated title"},
                    "detail": {"type": "string", "description": "Updated description"},
                    "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"], "description": "Updated priority"},
                    "due_date": {"type": "string", "description": "Updated due date (YYYY-MM-DD)"},
                },
                "required": ["mission_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_missions",
            "description": "List current missions/tasks, optionally filtered by status or project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["open", "in_progress", "done", "cancelled"], "description": "Filter by status (default: all open)"},
                    "project_id": {"type": "integer", "description": "Filter by project ID"},
                },
                "required": [],
            },
        },
    },
    # ── Enhanced agentic tools ─────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "plan_task",
            "description": (
                "Emit a structured execution plan at the START of any complex multi-step task. "
                "Use this before starting work so the user can see your approach. "
                "Steps should be concrete actions (read file X, edit Y, run test Z)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "One-sentence description of what you are trying to accomplish"},
                    "steps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ordered list of concrete steps to complete the goal",
                    },
                },
                "required": ["goal", "steps"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spawn_subagent",
            "description": (
                "Spawn a focused sub-agent to handle a well-defined subtask in parallel. "
                "The sub-agent has full tool access and runs its own ReAct loop. "
                "Use this to delegate discrete subtasks like: "
                "'read file X and summarise it', 'find all TODO comments in ~/project', "
                "'check if function Y exists in codebase'. "
                "Returns the sub-agent's answer. Max 15 iterations."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "The specific subtask for the sub-agent to complete"},
                    "context": {"type": "string", "description": "Optional extra context to give the sub-agent", "default": ""},
                    "max_iterations": {"type": "integer", "description": "Max ReAct iterations (1-15, default 10)", "default": 10},
                },
                "required": ["task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "http_get",
            "description": "Perform an HTTP GET request and return the response body (max 6 KB). Use for fetching documentation, APIs, or web content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to fetch (must start with http:// or https://)"},
                    "headers": {"type": "string", "description": "Optional request headers in 'Key: Value\\nKey2: Value2' format", "default": ""},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "Generate an image with a configured image-capable provider and store it as an Axon resource.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Text prompt describing the image to generate"},
                    "aspect_ratio": {"type": "string", "description": "Optional aspect ratio like 1:1, 16:9, 9:16", "default": "1:1"},
                    "image_size": {"type": "string", "description": "Optional size like 512, 1K, 2K, 4K", "default": "1K"},
                    "workspace_id": {"type": "integer", "description": "Optional workspace/project ID to associate the generated image with"},
                    "title": {"type": "string", "description": "Optional resource title for the generated image", "default": ""},
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": (
                "Persist a named note in agent memory. Use this to save important facts, decisions, "
                "file paths, credentials, or any information you'll need in future sessions. "
                "Notes survive console close and server restart."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Unique name for this note (e.g. 'project_db_url', 'api_key_name')"},
                    "value": {"type": "string", "description": "The information to remember"},
                },
                "required": ["key", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall",
            "description": "Search persisted agent memory notes. Returns all notes whose key or value matches your query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search term to find in stored notes"},
                },
                "required": ["query"],
            },
        },
    },
    # ── Power tools ───────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "project_info",
            "description": (
                "Scan a project directory and return REAL structure: file tree, line counts, "
                "git history, and key config files. ALWAYS call this before making any claims "
                "about a project's size, structure, or codebase. Do NOT guess project layout."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Project directory path (default: ~)", "default": "~"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web using DuckDuckGo. Returns titles, URLs, and snippets. "
                "Use for: documentation, package info, error messages, current events, tutorials."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "description": "Max results to return (1-10, default 6)", "default": 6},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "glob_files",
            "description": "Find files matching a glob pattern (e.g. '**/*.py', 'src/**/*.ts'). Returns paths sorted by modification time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern, e.g. '**/*.py'"},
                    "path": {"type": "string", "description": "Base directory (default: ~)", "default": "~"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep_code",
            "description": "Search file contents with regex. Faster and more powerful than search_code. Returns matching lines with context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern to search for"},
                    "path": {"type": "string", "description": "Directory to search in (default: ~)", "default": "~"},
                    "file_type": {"type": "string", "description": "File extension filter e.g. 'py', 'js', 'ts'", "default": ""},
                    "context_lines": {"type": "integer", "description": "Lines of context around each match (0-5)", "default": 2},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "diff_files",
            "description": "Show a unified diff between two files. Use for reviewing changes or comparing versions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path_a": {"type": "string", "description": "First file path"},
                    "path_b": {"type": "string", "description": "Second file path"},
                },
                "required": ["path_a", "path_b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_write",
            "description": (
                "Write a structured memory entry to Axon's persistent knowledge bank. "
                "Categories: facts, patterns, preferences, code, context, skills, project. "
                "Use this to remember things about the user, project, or domain across sessions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Category: facts|patterns|preferences|code|context|skills|project"},
                    "key": {"type": "string", "description": "Unique key for this memory entry"},
                    "value": {"type": "string", "description": "The information to remember"},
                },
                "required": ["category", "key", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_read",
            "description": "Read from Axon's structured memory bank. Filter by category and/or search term.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Category filter: facts|patterns|preferences|code|context|skills|project", "default": ""},
                    "query": {"type": "string", "description": "Search term to filter entries", "default": ""},
                },
                "required": [],
            },
        },
    },
]


def _canonical_tool_name(name: str, args: dict[str, Any] | None = None) -> str:
    raw = str(name or "").strip().lower()
    normalized = _re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    alias_map = {
        "append": "append_file",
        "append_file": "append_file",
        "create": "create_file",
        "create_file": "create_file",
        "delete": "delete_file",
        "delete_file": "delete_file",
        "remove": "delete_file",
        "remove_file": "delete_file",
        "rm": "delete_file",
        "read": "read_file",
        "read_file": "read_file",
        "readfile": "read_file",
        "write": "write_file",
        "write_file": "write_file",
        "writefile": "write_file",
        "list": "list_dir",
        "list_dir": "list_dir",
        "listdir": "list_dir",
        "gitstatus": "git_status",
        "git_status": "git_status",
        "search": "search_code",
        "search_code": "search_code",
        "searchcode": "search_code",
        "shell": "shell_cmd",
        "shell_cmd": "shell_cmd",
        "shellcmd": "shell_cmd",
        "shell_bg": "shell_bg",
        "shellbg": "shell_bg",
        "shell_background": "shell_bg",
        "background": "shell_bg",
        "shell_bg_check": "shell_bg_check",
        "shellbgcheck": "shell_bg_check",
        "bg_check": "shell_bg_check",
        "edit": "edit_file",
        "edit_file": "edit_file",
        "editfile": "edit_file",
        "replace": "edit_file",
        "patch": "edit_file",
        "diff": "show_diff",
        "show_diff": "show_diff",
        "showdiff": "show_diff",
        "git_diff": "show_diff",
        # enhanced agentic tools
        "http": "http_get",
        "http_get": "http_get",
        "fetch": "http_get",
        "get_url": "http_get",
        "image": "generate_image",
        "generate_image": "generate_image",
        "image_gen": "generate_image",
        "imagegen": "generate_image",
        "create_image": "generate_image",
        "save_note": "remember",
        "note": "remember",
        "remember": "remember",
        "recall": "recall",
        "search_memory": "recall",
        "plan": "plan_task",
        "plan_task": "plan_task",
        "subagent": "spawn_subagent",
        "spawn_subagent": "spawn_subagent",
        "delegate": "spawn_subagent",
        # power tools
        "project_info": "project_info",
        "projectinfo": "project_info",
        "scan_project": "project_info",
        "analyze_project": "project_info",
        "web_search": "web_search",
        "websearch": "web_search",
        "search_web": "web_search",
        "google": "web_search",
        "duckduckgo": "web_search",
        "glob_files": "glob_files",
        "glob": "glob_files",
        "find_files": "glob_files",
        "grep_code": "grep_code",
        "rg": "grep_code",
        "ripgrep": "grep_code",
        "diff_files": "diff_files",
        "diff": "diff_files",
        "memory_write": "memory_write",
        "memorize": "memory_write",
        "save_memory": "memory_write",
        "memory_read": "memory_read",
        "recall_memory": "memory_read",
        "load_memory": "memory_read",
    }
    if normalized == "using" and (args or {}).get("path"):
        return "read_file"
    return alias_map.get(normalized, normalized)


def _execute_tool(name: str, args: dict[str, Any], deps: AgentRuntimeDeps) -> str:
    """Execute a tool by name with the given arguments."""
    canonical_name = _canonical_tool_name(name, args)
    fn = deps.tool_registry.get(canonical_name)
    if not fn:
        return f"ERROR: Unknown tool '{name}'"
    normalized = deps.normalize_tool_args(canonical_name, args)
    try:
        return fn(**normalized)
    except TypeError as e:
        example = _TOOL_ARG_EXAMPLES.get(canonical_name, "")
        hint = f"\nExample:\nACTION: {canonical_name}\nARGS: {example}" if example else ""
        received = ", ".join(sorted(normalized.keys())) if normalized else "none"
        return f"ERROR: Bad arguments for {canonical_name}: {e}\nReceived keys: {received}{hint}"
    except Exception as e:
        return f"ERROR: {canonical_name} failed: {e}"


_TOOL_ARG_EXAMPLES: dict[str, str] = {
    "shell_cmd":    '{"cmd": "ls -la", "cwd": "~/project"}',
    "shell_bg":     '{"cmd": "npm run dev", "cwd": "~/project"}',
    "read_file":    '{"path": "~/project/src/app.tsx"}',
    "write_file":   '{"path": "~/project/file.ts", "content": "file contents here"}',
    "edit_file":    '{"path": "~/project/file.ts", "old_string": "exact old text", "new_string": "replacement text"}',
    "search_code":  '{"pattern": "function_name", "path": "~/project"}',
    "list_dir":     '{"path": "~/project/src"}',
    "delete_file":  '{"path": "~/project/old_file.ts"}',
    "git_status":   '{"path": "~/project"}',
    "show_diff":    '{"path": "~/project"}',
    "http_get":     '{"url": "http://localhost:3000"}',
    "generate_image": '{"prompt": "A clean isometric landing page hero illustration of a futuristic AI workspace", "aspect_ratio": "16:9", "image_size": "1K"}',
    "plan_task":    '{"goal": "Fix the login page", "steps": ["Read the file", "Find the bug", "Fix it"]}',
    "remember":     '{"key": "db_url", "value": "postgres://localhost/mydb"}',
    "recall":       '{"query": "database"}',
    "glob_files":   '{"pattern": "**/*.tsx", "path": "~/project"}',
}

