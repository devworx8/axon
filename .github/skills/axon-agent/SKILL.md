---
name: axon-agent
description: "**DOMAIN SKILL** — Axon ReAct agent loop development. USE FOR: modifying the agent execution loop, changing tool definitions, editing intent classification, updating system prompts, modifying approval/autonomy gates, changing agent output sanitization, editing session persistence, working with CLI pacing or CLI command building, modifying vision runtime auto-routing, changing blocked action repair logic. USE WHEN: touching any file in ~/.devbrain/axon_core/, editing agent behavior, adding new agent tools, changing how Axon classifies user intent, modifying the ReAct ACTION/ARGS/ANSWER cycle. DO NOT USE FOR: HTTP route changes (use axon-backend), UI changes (use axon-frontend), database schema changes (use axon-data)."
argument-hint: "Describe the agent behavior change"
---

# Axon Agent Loop Development

You are working on Axon's ReAct-style agentic execution system in `axon_core/`.
This is the brain of Axon's autonomous operation — changes here directly affect
how Axon thinks, acts, and verifies its work.

## Module Map

```
axon_core/
  agent.py               — Main ReAct loop, tool execution, approval gates
  agent_intent.py        — User message classification (casual/planning/operator)
  agent_prompts.py       — System prompt builder (_build_react_system)
  agent_toolspecs.py     — Tool definitions (AgentRuntimeDeps, AGENT_TOOL_DEFS)
  agent_file_actions.py  — File/git/CLI shortcut handlers (320L)
  agent_output.py        — Output sanitization, hallucination detection
  agent_blocked_actions.py — Blocked tool auto-repair (cd wrapper rewrite)
  agent_paths.py         — Path resolution, workspace matching, project lookup
  approval_actions.py    — Autonomy profiles, action fingerprinting
  session_store.py       — SQLite session persistence, in-memory fallback
  cli_pacing.py          — CLI launch rate limiting (per-runtime-family)
  cli_command.py         — CLI command builders (Claude CLI, Codex CLI)
  vision_runtime.py      — Vision model auto-routing across backends
  github_orchestrator.py — Git/GitHub command builders
  chat_context.py        — History selection, image-focused detection
  async_workers.py       — Sync-to-async bridge for agent loop
```

## ReAct Cycle

The agent operates in a strict ACTION → RESULT → THINKING → ACTION loop:

```
User message
  ↓
Intent classification (agent_intent.py)
  ↓
System prompt assembly (agent_prompts.py)
  ↓
┌─────────────────────────────────┐
│  LLM generates:                 │
│    THINKING: reasoning          │
│    ACTION: tool_name            │
│    ARGS: {"key": "value"}       │
│  ─── OR ───                     │
│    ANSWER: final response       │
└─────────────────────────────────┘
  ↓
Tool execution (_execute_tool in agent_toolspecs.py)
  ↓
Blocked? → approval_actions.py → wait for user approval
  ↓
Result injected → loop continues
```

## Tool System

### AgentRuntimeDeps (agent_toolspecs.py)
```python
@dataclass
class AgentRuntimeDeps:
    workspace_path: str
    db_path: Path
    settings: dict
    # ... additional runtime context
```

### AGENT_TOOL_DEFS
```python
AGENT_TOOL_DEFS = [
    {"name": "read_file",    "description": "...", "parameters": {...}},
    {"name": "list_dir",     "description": "...", "parameters": {...}},
    {"name": "shell_cmd",    "description": "...", "parameters": {...}},
    {"name": "shell_bg",     "description": "...", "parameters": {...}},
    {"name": "shell_bg_check", "description": "...", "parameters": {...}},
    # ... more tools
]
```

To add a new tool:
1. Add definition to `AGENT_TOOL_DEFS` in `agent_toolspecs.py`
2. Implement handler in `_execute_tool()` function
3. Add description to tool reference table in `agent_prompts.py`

## Intent Classification (agent_intent.py)

Three-tier classification:

| Function | Returns True when | Result |
|----------|-------------------|--------|
| `_is_casual_conversation()` | Greetings, about-self, short messages | Direct reply, no tools |
| `_is_general_planning_request()` | Business/writing terms without local objects | Planning response, no tools |
| `_requires_local_operator_execution()` | File paths, action verbs + local objects | Full ReAct loop with tools |

### Key: Intent determines whether tools are activated at all.

## Approval System (approval_actions.py)

Six autonomy profiles, ranked:

```
manual → workspace_auto → branch_auto → pr_auto → merge_auto → deploy_auto
```

| Profile | Allows |
|---------|--------|
| `manual` | Nothing auto-approved |
| `workspace_auto` | File ops, shell commands |
| `branch_auto` | + git add/commit/checkout/branch |
| `pr_auto` | + git push, PR create |
| `merge_auto` | + destructive git ops |
| `deploy_auto` | + deploy commands |

### Action fingerprinting
```python
action = build_command_approval_action(
    command="git push -u origin feature-branch",
    cwd="/path/to/repo",
    workspace_id=42,
    session_id="abc123",
)
# Returns: {action_fingerprint, action_type, destructive, scope_options, ...}
```

## Output Sanitization (agent_output.py)

- `_sanitize_agent_text()` — strips leaked ReAct instructions from answers
- `_filter_thinking_chunk()` — removes fake progress bars/structured output
- `_normalize_thinking_spacing()` — fixes merged-word artifacts from small LLMs
- `_looks_like_unverified_edit_claim()` — detects hallucinated edit reports

## Hallucination Prevention (CRITICAL)

The agent system has zero tolerance for hallucination. Key safeguards:

1. **Evidence sections** — checkpoint/audit answers MUST include:
   - `Verified In This Run`
   - `Inferred From Repo State`
   - `Not Yet Verified`
   - `Next Action Not Yet Taken`

2. **Tool log verification** — `_tool_log_has_name()` and `_tool_log_mentions()` check
   if the agent actually used the tools it claims to have used.

3. **Blocked action repair** — `blocked_tool_retry_prompt()` auto-rewrites blocked
   `cd ... && ...` wrappers into proper `cwd` + `cmd` splits.

## Session Persistence (session_store.py)

```python
store = SessionStore()
store.save(session_id, task, messages, iteration, tool_log)
session = store.get_active()  # Resume after "please continue"
store.mark_complete(session_id)
```

Falls back to in-memory `_MEMORY_FALLBACK_SESSIONS` if SQLite write fails.

## CLI Pacing (cli_pacing.py)

Rate-limits CLI launches per runtime family (Claude/Codex):

```python
await wait_for_cli_slot(min_interval_seconds=8.0, key="claude")
await extend_cli_cooldown(seconds=60, key="claude")
```

## Verification

```bash
# Syntax check all axon_core modules
for f in axon_core/*.py; do python3 -m py_compile "$f"; done

# Import check
python3 -c "from axon_core.agent import *; print('OK')"
python3 -c "from axon_core.agent_intent import *; print('OK')"
```

## Anti-Patterns to Avoid

- Claiming tool results without actual tool execution (hallucination)
- Adding tools without updating the system prompt tool reference
- Modifying intent classification without testing edge cases
- Bypassing the approval system for destructive operations
- Growing `agent_prompts.py` system prompt without extracting to template
- Adding sync blocking calls inside the async agent loop
- Nesting subagent spawns (one subagent at a time, no nesting)
