# AGENTS.md

This file is the operating contract for humans and Axon when working in this
repository.

Axon is no longer allowed to grow as a monolith.

## Core principle

Every change must make the codebase easier to split, easier to test, and easier
to reason about.

If a change makes a large file larger, that change is presumed wrong unless it
also extracts code in the same patch.

## Non-negotiable guardrails

1. No new monoliths.
2. No new feature may be implemented as a large inline block inside an existing
   monolith when a bounded-context module can be created instead.
3. If a touched file exceeds its soft limit, extraction is required in the same
   change unless a written waiver is added to `docs/engineering/guardrails.md`.
4. Root compatibility files must stay thin:
   - `server.py` = app bootstrap + registration + compatibility only
   - `brain.py` = orchestration facade + compatibility only
   - `db.py` = database compatibility facade only
   - `ui/index.html` = shell/layout/partials/bootstrap only
5. New files must have a single bounded context. Do not create dumping-ground
   files like `misc.py`, `more_helpers.py`, `big_utils.py`, or `new_logic.js`.
6. New inline JavaScript in HTML is strongly discouraged. Prefer `ui/js/*`.
7. Backward compatibility matters. Existing routes, settings keys, storage
   paths, and launcher flows must stay stable unless a migration is explicit.

## File size policy

These are the target limits after the refactor settles:

- Python service or domain module: soft `350`, hard `500`
- Frontend JS module: soft `350`, hard `500`
- HTML partial: soft `250`, hard `400`
- Markdown/design doc: soft `400`, hard `700`

Legacy hotspots are temporarily frozen with baseline budgets and may not grow:

- `server.py`
- `brain.py`
- `ui/index.html`
- `ui/manual.html`
- `ui/js/dashboard.js`
- `ui/js/chat.js`
- `ui/js/voice.js`

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
- `docs/architecture/refactor-roadmap.md`
- `docs/architecture/module-map.md`
