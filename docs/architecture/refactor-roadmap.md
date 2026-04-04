# Axon Refactor Roadmap

## Goal

Break Axon into bounded modules without breaking:

- current routes
- current launcher/startup behavior
- current local storage paths
- current UI entrypoints
- current compatibility imports

## Phase 0 — Governance

- Add root `AGENTS.md`
- Add architecture docs and module map
- Add file-size and boundary guardrail scripts
- Add CI workflow

Status: completed

## Phase 0.5 — Anti-monolith enforcement

Target:

- make hotspot growth impossible in CI
- require shrink-or-waiver behavior for critical hotspots
- ratchet all currently oversized tracked files

Mechanics:

- `scripts/guardrails/hotspot_budgets.json`
- `docs/engineering/guardrail-waivers.json`
- `scripts/guardrails/check_file_sizes.py`
- `scripts/guardrails/check_hotspot_changes.py`

Status: completed

## Phase 1 — Database extraction

Target:

- move repository logic out of `db.py`
- keep `db.py` as a compatibility facade

Target package:

- `axon_data/`

Submodules:

- `core.py`
- `projects.py`
- `prompts.py`
- `tasks.py`
- `activity.py`
- `chat.py`
- `settings.py`
- `resources.py`
- `memory.py`
- `research_packs.py`
- `terminal.py`
- `webhooks.py`

Status: completed

## Phase 2 — Backend API extraction

Target:

- reduce `server.py` to app bootstrap + router registration

Target package:

- `axon_api/`

Initial slices:

- `app.py`
- `middleware.py`
- `ui_renderer.py`
- `routes/*`
- `services/*`

Status: in progress
Current slice: `axon_api/ui_renderer.py` extracted and wired through `server.py`

## Phase 3 — Core orchestration extraction

Target:

- reduce `brain.py` to a compatibility facade

Target package:

- `axon_core/`

Initial slices:

- `chat.py`
- `streaming.py`
- `agent.py`
- `intent.py`
- `providers.py`
- `prompts.py`
- `safety.py`
- `tools/*`

Status: in progress
Current slice: `axon_core/agent.py` extracted, wired through compatibility wrappers in `brain.py`, and the legacy in-file agent block has been removed

## Phase 4 — Frontend shell breakup

Target:

- reduce `ui/index.html` to app shell
- split markup into `ui/partials/`
- split large JS by feature/bounded context

Initial slices:

- dashboard shell + dashboard modules
- console/composer shell + chat modules
- settings/resources/memory partials
- modal partials

Status: pending
Blocked by: `ui/index.html`, `ui/js/chat.js`, and `ui/js/dashboard.js` ratchet reduction work

## Phase 5 — Manual and docs breakup

Target:

- reduce `ui/manual.html` to a shell and chapter partials

Status: pending

## Completion definition

The refactor is not done when files are merely moved.

It is done when:

- entrypoints are thin
- module boundaries are clear
- CI blocks new monolith growth
- the live app behaves the same or better
- all ratcheted hotspot budgets have been driven down below hard limits
