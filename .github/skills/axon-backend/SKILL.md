---
name: axon-backend
description: "**DOMAIN SKILL** — Axon Python backend development. USE FOR: modifying FastAPI routes, adding API endpoints, changing server.py/brain.py facades, working with model_router.py or provider_registry.py, editing standalone modules (scanner, scheduler, integrations, vault, memory_engine, document_engine, pptx_engine, gpu_guard, resource_bank, runtime_manager, permissions_guard, browser_bridge). USE WHEN: touching any .py file in ~/.devbrain/, adding or changing HTTP routes, modifying AI provider logic, editing background jobs, changing vault operations. DO NOT USE FOR: frontend JS/HTML changes (use axon-frontend), agent loop or tool changes (use axon-agent), SQLite repository changes (use axon-data)."
argument-hint: "Describe the backend change or feature"
---

# Axon Backend Development

You are working on Axon's Python backend — a FastAPI server at `~/.devbrain/`
serving on port 7734. Every change must respect the extraction architecture and
file size guardrails defined in `AGENTS.md`.

## Architecture Overview

```
~/.devbrain/
  server.py          — FastAPI app bootstrap + routes (6027L, FROZEN — extract, don't grow)
  brain.py           — AI orchestration facade (1928L, FROZEN — extract to axon_core/)
  db.py              — Thin facade, re-exports from axon_data/
  model_router.py    — Multi-provider model selection (ModelRole, ModelRoute, LOCAL_MODEL_ROUTES)
  provider_registry.py — Cloud provider specs (ProviderSpec, PROVIDERS, PROVIDER_BY_ID)
  agent_registry.py  — Multi-agent registry (AgentPhase, AgentRole, AGENT_SPECS)
  runtime_manager.py — Runtime snapshot builder (build_runtime_status, env_snapshot)
  scanner.py         — Workspace scanner (detect_stack, scan_project, discover_and_scan)
  scheduler.py       — APScheduler jobs (scan, digest, reminders, webhook queue)
  integrations.py    — GitHub CLI, Slack webhooks
  memory_engine.py   — Memory layer (sync_memory_layers, search)
  document_engine.py — Invoice engine (InvoiceDraft, render)
  pptx_engine.py     — PPTX generator (DeckSpec, build_deck)
  vault.py           — AES-256-GCM vault (VaultSession, PBKDF2, TOTP)
  gpu_guard.py       — GPU safety (detect_display_gpu_state)
  resource_bank.py   — File ingestion + embeddings (analyze_resource_file)
  permissions_guard.py — Permission scaffolding (PermissionScope, GuardDecision)
  browser_bridge.py  — Playwright CDP bridge (BrowserBridge)
  axon_api/          — Extracted API layer (services/, settings_models, ui_renderer)
  axon_core/         — Extracted orchestration (agent loop, intent, prompts, tools)
  axon_data/         — Extracted data layer (SQLite repositories)
```

## File Size Guardrails (from AGENTS.md)

| Type | Soft | Hard |
|------|-----:|-----:|
| Python service/domain module | 350 | 500 |
| Frontend JS module | 350 | 500 |
| HTML partial | 250 | 400 |

### Frozen files (must NOT grow):
- `server.py` — extract routes to `axon_api/routes/`
- `brain.py` — extract logic to `axon_core/`

## Key Patterns

### Database access
```python
import db as devdb
async with devdb.get_db() as conn:
    result = await devdb.get_projects(conn, status="active")
```

### Settings retrieval
```python
async with devdb.get_db() as conn:
    settings = await devdb.get_all_settings(conn)
    backend = settings.get("ai_backend", "ollama")
```

### API route pattern (in server.py or axon_api/routes/)
```python
@app.get("/api/example")
async def get_example():
    async with devdb.get_db() as conn:
        data = await devdb.get_something(conn)
    return JSONResponse({"items": data})
```

### Provider routing
```python
from model_router import resolve_model_for_role, ModelRouterConfig
from provider_registry import runtime_api_config, merged_provider_config
```

### Vault operations (require unlock)
```python
from vault import VaultSession, decrypt, encrypt
key = VaultSession.get_key()
if key is None:
    return JSONResponse({"error": "Vault locked"}, status_code=403)
```

## Extraction Rules

When touching `server.py` or `brain.py`:

1. **Identify the bounded context** — which domain does this logic belong to?
2. **Extract to the right package:**
   - HTTP routes → `axon_api/routes/`
   - Services/helpers → `axon_api/services/`
   - AI orchestration → `axon_core/`
   - Data operations → `axon_data/`
3. **Keep the old entrypoint as a facade** — add a compatibility import/re-export
4. **Preserve public behavior** — existing routes, function signatures, import paths

## Verification (required for every change)

```bash
# Syntax check all touched Python files
python3 -m py_compile <file>

# Quick import test
python3 -c "import ast; ast.parse(open('<file>').read()); print('OK')"

# For server.py changes, verify the app still loads
cd ~/.devbrain && .venv/bin/python -c "from server import app; print('App OK')"
```

## Anti-Patterns to Avoid

- Adding large route bodies to `server.py` (extract instead)
- Adding business logic to `brain.py` (extract to `axon_core/`)
- Creating "utility" files without a single bounded context
- Bypassing `devdb.get_db()` with direct SQLite calls
- Storing secrets in settings instead of the vault
- Adding new CDN dependencies without documenting in comments
