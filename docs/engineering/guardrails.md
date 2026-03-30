# Axon Engineering Guardrails

## Purpose

These guardrails exist to stop Axon from sliding back into large, fragile,
multi-purpose files.

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

The following files are currently too large and are under extraction. They may
not grow beyond their baseline budgets:

- `server.py`
- `brain.py`
- `ui/index.html`
- `ui/manual.html`
- `ui/js/dashboard.js`
- `ui/js/chat.js`
- `ui/js/voice.js`

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

Acceptable waiver note format:

```md
Guardrail waiver:
- file: path/to/file
- reason: short operational reason
- expiry: YYYY-MM-DD or next milestone
- follow-up: exact extraction target
```

## Review checklist

Before merging:

- Did a large file grow?
- If yes, did the same patch extract a bounded module?
- Does the new module have one clear purpose?
- Is the old entrypoint thinner than before?
- Did verification run?

## Initial enforcement

CI currently enforces:

- file-size budgets, including legacy freeze budgets
- `db.py` facade behavior
- presence of the architecture and guardrail docs

These checks will get stricter as the monoliths are reduced.
