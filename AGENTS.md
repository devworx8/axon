# AGENTS.md

This file is the operating contract for humans and Axon when working in this
repository.

Axon is no longer allowed to grow as a monolith.

## Core principle

Every change must make the codebase easier to split, easier to test, and easier
to reason about.

If a change makes a large file larger, that change is presumed wrong unless it
also extracts code in the same patch.

Axon must operate as a set of bounded modules, not as one giant codebase. That
is a permanent project rule.

## Non-negotiable guardrails

1. No new monoliths. Existing monoliths must only shrink.
2. No new feature may be implemented as a large inline block inside an existing
   monolith when a bounded-context module can be created instead.
3. Critical hotspots and ratcheted oversize files are governed by
   `scripts/guardrails/hotspot_budgets.json` and may not exceed their checked-in
   budgets.
4. Touching a critical hotspot requires same-patch extraction that lowers its
   ratchet budget, unless there is an active time-boxed waiver in
   `docs/engineering/guardrail-waivers.json`.
5. Waivers are emergency-only, time-boxed, and must name an exact extraction
   follow-up. Expired waivers fail CI.
6. Root compatibility files must stay thin:
   - `server.py` = app bootstrap + registration + compatibility only
   - `brain.py` = orchestration facade + compatibility only
   - `db.py` = database compatibility facade only
   - `ui/index.html` = shell/layout/partials/bootstrap only
7. New files must have a single bounded context. Do not create dumping-ground
   files like `misc.py`, `more_helpers.py`, `big_utils.py`, or `new_logic.js`.
8. New inline JavaScript in HTML is strongly discouraged. Prefer `ui/js/*`.
9. Backward compatibility matters. Existing routes, settings keys, storage
   paths, and launcher flows must stay stable unless a migration is explicit.

## File size policy

These are the target limits after the refactor settles:

- Python service or domain module: soft `350`, hard `500`
- Frontend JS module: soft `350`, hard `500`
- HTML partial: soft `250`, hard `400`
- Markdown/design doc: soft `400`, hard `700`

Critical hotspots are permanently ratcheted with checked-in budgets and may not
grow:

- `server.py`
- `brain.py`
- `ui/index.html`
- `ui/manual.html`
- `ui/js/dashboard.js`
- `ui/js/chat.js`
- `ui/js/voice.js`

Additional oversize tracked files are ratcheted in
`scripts/guardrails/hotspot_budgets.json` and also may not grow.

`db.py` is already under active extraction and must stay a thin facade.

## Required architecture direction

Backend code belongs in bounded packages:

- `axon_api/` for FastAPI route and request wiring
- `axon_core/` for chat, agent, tool, and provider orchestration
- `axon_data/` for SQLite repositories and persistence

Frontend code belongs in:

- `ui/index.html` for shell only
- `ui/partials/` for rendered markup sections
- `ui/js/` for feature logic split by bounded context

## Refactor rules

When touching a large file:

1. Identify the bounded context first.
2. Extract logic into a new module.
3. Keep the old entrypoint as a compatibility facade.
4. Preserve imports and public behavior.
5. Add or update verification in the same patch.

## Verification rules

Every structural change must include the cheapest reliable verification:

- `python3 -m py_compile` for touched Python modules
- `node --check` for touched JS modules when applicable
- targeted smoke tests for touched routes or scripts
- guardrail scripts when architecture/governance files are touched

## Anti-hallucination policy — ZERO TOLERANCE

Hallucination is defined as inventing data, simulating tool output, or claiming
actions were performed without real tool execution.

1. **No fabricated output.** Every command result, file content, diff, or API
   response must come from an actual tool call. Never simulate output.
2. **No phantom edits.** Claiming a file was edited requires a successful
   `edit_file` / `write_file` tool result. No exceptions.
3. **No narrated commands.** Writing `git push` in a code block is not the same
   as running it. Use `shell_cmd` for every command.
4. **Verify after acting.** After any edit, read the file back or show a diff.
   After any command, report the real output.
5. **Admit uncertainty.** If you cannot verify a fact, say "I'm not sure" and
   use a tool to check. Never guess and present it as fact.
6. **Runtime enforcement.** The ReAct loop has automated hallucination detection
   (`_looks_like_hallucinated_execution`). If triggered, the model is forced to
   retry with real tool calls. Repeated failures abort the task.

Any agent output that violates these rules is considered a critical defect.

## Prohibited shortcuts

- Do not add another standalone prototype that is not wired into the live app.
- Do not hide complexity in giant string literals or giant inline templates.
- Do not solve a large file problem by creating a second large file.
- Do not bypass the guardrail scripts.

## Decision rule

If you are choosing between:

- a fast change that increases central-file complexity
- a slightly slower change that preserves boundaries

choose the second one.

See:

- `docs/engineering/guardrails.md`
- `docs/engineering/guardrail-waivers.json`
- `docs/architecture/refactor-roadmap.md`
- `docs/architecture/module-map.md`
- `scripts/guardrails/hotspot_budgets.json`
