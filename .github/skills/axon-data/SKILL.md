---
name: axon-data
description: "**DOMAIN SKILL** — Axon SQLite data layer development. USE FOR: modifying database repositories in axon_data/, adding new tables or columns, changing CRUD operations, editing memory sync logic, working with FTS search, modifying resource chunk embeddings, adding new data modules. USE WHEN: touching any file in ~/.devbrain/axon_data/, editing db.py facade, modifying memory_engine.py data access, changing how Axon stores or retrieves persistent data. DO NOT USE FOR: HTTP route changes (use axon-backend), UI changes (use axon-frontend), agent loop changes (use axon-agent)."
argument-hint: "Describe the data layer change"
---

# Axon Data Layer Development

You are working on Axon's persistence layer — async SQLite repositories in
`~/.devbrain/axon_data/`. The data layer is fully extracted from the original
monolithic `db.py`, which now serves as a thin compatibility facade.

## Module Map

```
axon_data/
  __init__.py          — Re-exports ALL public functions (MUST update when adding)
  core.py              — Connection manager (get_db, init_db), schema bootstrap
  projects.py          — Workspace CRUD (upsert_project, get_projects, etc.)
  tasks.py             — Mission CRUD (add_task, get_tasks, update_task, etc.)
  prompts.py           — Prompt templates CRUD
  activity.py          — Activity log (log_event, get_activity)
  chat.py              — Chat history (save_message, get_chat_history, clear)
  settings.py          — Key-value settings (get_setting, set_setting, get_all)
  resources.py         — Resource bank storage (add_resource, chunks, embeddings)
  memory.py            — Memory items (upsert, search, list, count by layer)
  research_packs.py    — Research pack collections
  terminal.py          — Terminal session tracking
  webhooks.py          — Webhook queue (enqueue, get_pending, mark_sent/failed)
  runtime_state.py     — Workspace snapshots, thread summaries, approval grants,
                         external fetch cache, FTS helpers
  sqlite_utils.py      — Sync managed_connection context manager
```

### Facade
```
db.py                  — Thin re-export facade (import from here for compatibility)
```

### Consumers
```
memory_engine.py       — Reads from all data modules, writes to memory.py
resource_bank.py       — Provides analysis/embedding logic consumed by resources.py
```

## Connection Patterns

### Async (standard — use everywhere except agent path resolution)
```python
import db as devdb
# or: from axon_data import get_db

async with devdb.get_db() as conn:
    # conn is aiosqlite.Connection with row_factory=sqlite3.Row
    projects = await devdb.get_projects(conn, status="active")
    settings = await devdb.get_all_settings(conn)
```

### Sync (only for agent_paths.py path resolution)
```python
from axon_data.sqlite_utils import managed_connection

with managed_connection(db_path, row_factory=None) as conn:
    rows = conn.execute("SELECT name, path FROM projects").fetchall()
```

## Schema Bootstrap (core.py init_db)

Tables are created in `init_db()` with `CREATE TABLE IF NOT EXISTS`. Schema
migrations use `ALTER TABLE ... ADD COLUMN` wrapped in try/except for idempotency.

Key tables:
- `projects` — workspaces with health scores, git info, stack detection
- `tasks` — missions with priority, status, due dates
- `prompts` — saved prompt templates per workspace
- `activity` — event log with types and summaries
- `chat_history` — conversation messages per workspace
- `settings` — key-value configuration store
- `resources` — uploaded files and URL imports
- `resource_chunks` — chunked text with embeddings
- `memory_items` — curated memory across 4 layers
- `memory_links` — item relationships
- `research_packs` / `research_pack_items` — research collections
- `terminal_sessions` / `terminal_events` — PTY session tracking
- `webhook_queue` — retry queue for outbound webhooks
- `vault_secrets` — encrypted secret storage
- `workspace_snapshots` — cached workspace context
- `thread_summaries` — conversation summaries
- `approval_grants` — persisted action approvals
- `external_fetch_cache` — cached URL fetches with TTL
- `agent_sessions` — agent loop persistence

## Repository Pattern

Every repository module follows this pattern:

```python
from __future__ import annotations
import aiosqlite

async def create_thing(db: aiosqlite.Connection, *, name: str, ...) -> int:
    cur = await db.execute(
        "INSERT INTO things (name, ...) VALUES (?, ...)",
        (name, ...),
    )
    await db.commit()
    return cur.lastrowid

async def get_things(db: aiosqlite.Connection, *, limit: int = 100):
    cur = await db.execute(
        "SELECT * FROM things ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    return await cur.fetchall()

async def update_thing(db: aiosqlite.Connection, thing_id: int, **fields):
    if not fields:
        return
    set_clauses = [f"{key} = ?" for key in fields]
    values = list(fields.values()) + [thing_id]
    await db.execute(
        f"UPDATE things SET {', '.join(set_clauses)}, updated_at = datetime('now') WHERE id = ?",
        values,
    )
    await db.commit()
```

### Upsert pattern (used heavily)
```python
await db.execute("""
    INSERT INTO things (key, value) VALUES (?, ?)
    ON CONFLICT(key) DO UPDATE SET
        value = excluded.value,
        updated_at = datetime('now')
""", (key, value))
await db.commit()
```

## Adding a New Repository Module

1. Create `axon_data/new_module.py` with repository functions
2. Add schema creation to `core.py` `init_db()` if new tables needed
3. **CRITICAL**: Add exports to `axon_data/__init__.py`
4. Add re-exports to `db.py` for backward compatibility
5. Verify:
   ```bash
   python3 -m py_compile axon_data/new_module.py
   python3 -c "from axon_data import new_function; print('OK')"
   python3 -c "from db import new_function; print('OK')"
   ```

## FTS (Full-Text Search)

FTS tables are bootstrapped in `core.py`:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS memory_items_fts
USING fts5(memory_key, title, content, layer);
```

Query helper in `runtime_state.py`:
```python
def _fts_query(query: str) -> str:
    terms = re.findall(r"[A-Za-z0-9_./:-]{2,}", query)
    return " OR ".join(f'"{term}"' for term in terms[:12])
```

## Memory Engine Integration

`memory_engine.py` syncs data from all repositories into `memory_items`:

- **workspace** layer — from projects table
- **resource** layer — from resources table
- **mission** layer — from tasks + activity tables
- **user** layer — from settings (preferences)

Each item has: `memory_key`, `layer`, `title`, `content`, `trust_level`,
`relevance_score`, `meta_json`.

## Verification

```bash
# Syntax check all data modules
for f in axon_data/*.py; do python3 -m py_compile "$f"; done

# Import check (tests __init__.py re-exports)
python3 -c "import axon_data; print(dir(axon_data))" | head -5

# Verify db.py facade still works
python3 -c "import db; print('db facade OK')"
```

## Anti-Patterns to Avoid

- Direct SQLite calls outside `axon_data/` (use the repository functions)
- Forgetting to add exports to `__init__.py` (breaks `import db`)
- Large SQL blocks in non-data modules (belongs in axon_data/)
- Sync database access outside `agent_paths.py` (use async `get_db()`)
- Raw string formatting in SQL (always use parameterized queries `?`)
- Committing inside a read-only query path (unnecessary overhead)
- Growing `core.py` with repository logic (keep it to connection + schema)
