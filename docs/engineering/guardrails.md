# Axon Engineering Guardrails

## Purpose

These guardrails exist to stop Axon from sliding back into large, fragile,
multi-purpose files.

Axon is not allowed to return to a giant centralized codebase under any
circumstance.

## Working rule

Every file must have a single dominant reason to change.

If a file is accumulating logic from multiple domains, extract first and then
continue feature work.

## Current anti-monolith policy

### Soft and hard limits

| File type | Soft limit | Hard limit |
| --- | ---: | ---: |
| Python domain/service module | 350 lines | 500 lines |
| Frontend JS module | 350 lines | 500 lines |
| HTML partial | 250 lines | 400 lines |
| Markdown doc | 400 lines | 700 lines |

### Legacy freeze list

The following critical hotspots are under permanent ratchet enforcement. They
may not grow beyond their checked-in budgets, and touching them requires a
same-patch size reduction unless there is an active time-boxed waiver:

- `server.py`
- `brain.py`
- `ui/index.html`
- `ui/manual.html`
- `ui/js/dashboard.js`
- `ui/js/chat.js`
- `ui/js/voice.js`

Additional oversized tracked files are ratcheted in
`scripts/guardrails/hotspot_budgets.json`. They may not grow, even when they
are not on the critical hotspot list.

## Ratchet budget manifest

Machine-enforced budgets live in:

- `scripts/guardrails/hotspot_budgets.json`

The manifest has two groups:

- `critical_hotspots`: the files that must shrink whenever they are touched
- `ratcheted_oversize_files`: legacy oversized files that may not grow

If a file shrinks, the manifest must be updated in the same patch to ratchet the
budget down to the new real line count.

## Boundary rules

### `server.py`

Allowed:

- FastAPI app creation
- middleware registration
- router registration
- compatibility imports
- static/app shell serving glue

Not allowed long term:

- large route bodies
- non-trivial business logic
- desktop preview implementation logic
- terminal execution logic
- tunnel orchestration logic

### `brain.py`

Allowed:

- stable compatibility exports
- high-level orchestration facade

Not allowed long term:

- giant tool implementations
- provider-specific chat logic
- prompt-template dumping
- streaming implementation details

### `db.py`

Allowed:

- compatibility imports/re-exports

Not allowed:

- table DDL
- repository implementations
- large SQL blocks

### `ui/index.html`

Allowed:

- shell
- layout scaffolding
- partial placeholders
- tiny bootstrap wiring

Not allowed long term:

- giant feature templates
- giant inline JS state objects
- feature-specific terminal/chat/resource logic

## Waiver policy

A guardrail waiver is allowed only when all of the following are true:

1. The change is time-critical.
2. Extraction would materially increase risk right now.
3. The waiver is documented in the change and includes a follow-up task.

Waivers are stored in:

- `docs/engineering/guardrail-waivers.json`

Acceptable waiver entry format:

```json
{
  "file": "server.py",
  "reason": "urgent production fix",
  "expiry": "2026-04-10",
  "follow_up": "Extract agent routes into axon_api/routes/agent.py"
}
```

Rules:

- waivers only apply to `critical_hotspots`
- waivers allow a non-shrinking touch, not budget growth
- expired waivers fail CI
- missing `reason`, `expiry`, or `follow_up` fails CI

## Review checklist

Before merging:

- Did a large file grow?
- If yes, did the same patch extract a bounded module?
- Does the new module have one clear purpose?
- Is the old entrypoint thinner than before?
- Did verification run?

## Current enforcement

CI currently enforces:

- tracked-file size budgets using the ratchet manifest
- critical-hotspot shrink-or-waiver checks
- `db.py` facade behavior
- banned dumping-ground file names
- presence of the architecture and guardrail docs

These checks ratchet tighter as monoliths are reduced. The end state is thin
compatibility entrypoints plus bounded modules only.
