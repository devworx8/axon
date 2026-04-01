# Axon Auto — Autonomous Sandboxed Agent Mode

**Sprint**: Next (April 2026)
**Status**: Planned
**Author**: Axon + EDP

---

## Problem

Axon currently requires user approval for:
- File writes/deletes (edit_file, write_file, delete_file)
- Shell commands (shell_cmd, shell_bg) when safe_mode is on
- Blocked commands (npm install, git push, etc.)

This makes autonomous workflows (clone → debug → update → test → deploy) impossible
without constant intervention. The user wants a mode where Axon can run end-to-end
on a project without any approval prompts.

## Solution: Axon Auto Mode

A sandboxed workspace environment where Axon operates with full autonomy — no
permission prompts, no blocked commands — while being isolated from system files.

## Architecture

### 1. Sandboxed Workspace (`axon_env/`)

```
~/.devbrain/axon_env/
  └── {project-slug}/         # One directory per auto-session
      ├── .axon-auto.json     # Session metadata
      ├── workspace/           # Cloned/created project lives here
      └── logs/                # Full audit trail
```

**Key constraint**: All Axon Auto file operations are confined to
`~/.devbrain/axon_env/{project}/workspace/`. No escape to `~`, `/`, or system dirs.

### 2. New Composer Mode: "Auto"

Add an `auto` mode alongside Ask / Agent / Code / Business / Research:

- Toggle in composer mode bar (bottom of console)
- When selected, agent runs with `safe_mode: false` + `require_approval: false`
- Workspace root is locked to the sandboxed directory
- All commands run inside the sandbox (cd enforced)

### 3. Session Lifecycle

```
User: "Clone bkkinnovationhub and fix the build errors"
  │
  ├── 1. CREATE sandbox:  axon_env/bkkinnovationhub-{timestamp}/
  ├── 2. CLONE project:   git clone <url> workspace/
  ├── 3. DETECT stack:    package.json → Node/Next.js, requirements.txt → Python
  ├── 4. INSTALL deps:    npm install / pip install (inside sandbox)
  ├── 5. RUN agent loop:  Full autonomy — read, write, shell, test, iterate
  ├── 6. VERIFY:          Run tests, build, lint
  ├── 7. REPORT:          Summary of changes + diff
  └── 8. USER DECISION:   Apply to real project / discard / keep sandbox
```

### 4. Safety Boundaries

| Allowed in Auto Mode | Blocked Even in Auto Mode |
|---|---|
| All file CRUD in sandbox | Writing outside `axon_env/` |
| npm/pip/cargo install | `rm -rf /`, `rm -rf ~` |
| git operations (local) | `git push` (needs explicit user OK) |
| Dev servers (localhost) | Accessing system files (/etc, ~/.ssh) |
| Build/test/lint | Network requests to non-localhost (configurable) |
| Create/delete directories | Modifying Axon's own source files |

### 5. Backend Changes

#### `brain.py` — Agent sandbox enforcement
- New `_SANDBOX_ROOT` derived from session
- `_resolve_agent_path()` checks against sandbox boundary
- `_tool_shell_cmd` / `_tool_shell_bg` enforce `cwd` within sandbox
- New tool: `clone_project` — clones a git repo into the sandbox workspace

#### `server.py` — New API endpoints
- `POST /api/auto/start` — Create sandbox, optional git clone
- `GET /api/auto/{session_id}/status` — Session state + log tail
- `POST /api/auto/{session_id}/apply` — Copy changes back to real project
- `DELETE /api/auto/{session_id}` — Delete sandbox
- `GET /api/auto/sessions` — List active/past auto sessions

#### `axon_core/agent_prompts.py` — Auto mode system prompt
- Removes all "ask for permission" language
- Adds: "You are in Axon Auto mode. You have full autonomy within this sandbox."
- Adds workspace context: stack detection, project structure summary

#### New module: `axon_core/sandbox.py`
- `create_sandbox(project_slug, git_url=None) -> SandboxSession`
- `destroy_sandbox(session_id)`
- `apply_sandbox(session_id, target_path) -> DiffSummary`
- `validate_path(session, path) -> bool` — enforce boundary
- `get_session_log(session_id) -> list[LogEntry]`

### 6. Frontend Changes

#### Composer mode bar
- New "Auto" button with distinctive styling (orange/gold, robot icon)
- When Auto mode is selected, show a sandbox setup dialog:
  - Clone URL input (optional — can start empty)
  - Project name
  - "Start Autonomous Session" button

#### Console UI in Auto mode
- Status banner: "🤖 Axon Auto — Running autonomously in sandbox"
- No approval cards appear
- Live progress shows full audit trail (all commands, all edits)
- "Apply Changes" / "Discard" buttons when agent reports completion
- Diff viewer for reviewing changes before applying

#### Right panel
- "Auto Sessions" section showing active/past sandboxed sessions
- Each session shows: project name, status, duration, change count

### 7. Implementation Phases

**Phase 1 — Sandbox Infrastructure (3-4 days)**
- [ ] `axon_core/sandbox.py` — create/destroy/validate/apply
- [ ] `_resolve_agent_path()` sandbox-aware path resolution
- [ ] API endpoints for session CRUD
- [ ] Tests: path boundary enforcement, clone, apply

**Phase 2 — Agent Auto Mode (2-3 days)**
- [ ] `composerOptions.auto_mode` state
- [ ] Auto mode system prompt (no approval language)
- [ ] Shell/file tools check sandbox boundary
- [ ] `clone_project` tool
- [ ] `safe_mode` + `require_approval` auto-disabled in auto mode

**Phase 3 — Frontend UX (2-3 days)**
- [ ] Auto mode button in composer bar
- [ ] Sandbox setup dialog (clone URL, project name)
- [ ] Status banner during auto session
- [ ] Apply/Discard buttons on completion
- [ ] Diff viewer for reviewing changes

**Phase 4 — Polish & Safety (1-2 days)**
- [ ] Audit trail logging (every command, every file change)
- [ ] Session timeout (configurable, default 30 min)
- [ ] Disk quota per sandbox (configurable, default 2GB)
- [ ] Stack detection (Node, Python, Rust, etc.) for smart initialization
- [ ] Auto-cleanup of old sandboxes

### 8. Example Workflow

```
User selects Auto mode → types: "Clone bkkinnovationhub and fix all build errors"
  ↓
Axon creates sandbox: axon_env/bkkinnovationhub-20260401/
  ↓
Axon clones: git clone https://github.com/user/bkkinnovationhub workspace/
  ↓
Axon detects: Next.js project (package.json found)
  ↓
Axon runs: npm install (in sandbox — no approval needed)
  ↓
Axon runs: npm run build → reads errors → fixes files → rebuilds → tests pass
  ↓
Axon reports: "Fixed 3 build errors in 2 files. Ready to apply."
  ↓
User clicks "Apply Changes" → Axon copies changes to real project
```

### 9. Risk Mitigation

- **Disk space**: Sandbox quota enforced, old sessions auto-cleaned
- **Runaway processes**: Session timeout kills all bg processes in sandbox
- **Network abuse**: Outbound requests configurable (default: localhost only)
- **Data loss**: Apply is a copy, not a move — sandbox preserved as backup
- **Escape attempts**: Double validation — both path resolution and chroot-style checks
