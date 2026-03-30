"""
Session persistence for Axon agents.

Saves agent state (messages, iteration count, tool log) to SQLite so a session
can be resumed after the console is closed.  The user just says
"please continue" and Axon picks up exactly where it left off.

API:
    store = SessionStore()

    # Auto-called by run_agent on every iteration
    store.save(session_id, task, messages, iteration, tool_log, ...)

    # Called when the user says "please continue"
    session = store.get_active()

    # Mark done when the loop ends cleanly
    store.mark_complete(session_id)
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

DEFAULT_DB = Path.home() / ".devbrain" / "devbrain.db"

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS agent_sessions (
    session_id   TEXT PRIMARY KEY,
    task         TEXT NOT NULL,
    messages     TEXT NOT NULL DEFAULT '[]',
    iteration    INTEGER NOT NULL DEFAULT 0,
    tool_log     TEXT NOT NULL DEFAULT '[]',
    status       TEXT NOT NULL DEFAULT 'active',
    project_name TEXT,
    backend      TEXT DEFAULT 'ollama',
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL,
    metadata     TEXT NOT NULL DEFAULT '{}'
)
"""


@dataclass
class AgentSession:
    session_id: str
    task: str
    messages: list[dict]
    iteration: int
    tool_log: list[dict]
    status: str                   # "active" | "completed" | "interrupted"
    project_name: Optional[str]
    backend: str
    created_at: float
    updated_at: float
    metadata: dict = field(default_factory=dict)

    def age_seconds(self) -> float:
        return time.time() - self.updated_at

    def summary(self) -> str:
        ago = int(self.age_seconds())
        if ago < 60:
            age_str = f"{ago}s ago"
        elif ago < 3600:
            age_str = f"{ago // 60}m ago"
        else:
            age_str = f"{ago // 3600}h ago"
        return (
            f"Session {self.session_id[:8]}… | {self.status} | "
            f"iter={self.iteration} | updated {age_str} | task: {self.task[:80]}"
        )


def new_session_id() -> str:
    return str(uuid.uuid4())


class SessionStore:
    """Thin synchronous wrapper around SQLite for agent session state."""

    def __init__(self, db_path: Path = DEFAULT_DB):
        self.db_path = db_path
        self._ensure_table()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_table(self):
        try:
            with self._connect() as conn:
                conn.execute(_CREATE_SQL)
                conn.commit()
        except Exception:
            pass  # DB not ready yet — will retry on first write

    # ── Write ─────────────────────────────────────────────────────────────────

    def save(
        self,
        session_id: str,
        task: str,
        messages: list[dict],
        iteration: int,
        tool_log: list[dict],
        status: str = "active",
        project_name: Optional[str] = None,
        backend: str = "ollama",
        metadata: Optional[dict] = None,
    ) -> str:
        """Upsert a session record.  Returns session_id."""
        now = time.time()
        try:
            with self._connect() as conn:
                conn.execute(_CREATE_SQL)
                conn.execute(
                    """
                    INSERT INTO agent_sessions
                        (session_id, task, messages, iteration, tool_log, status,
                         project_name, backend, created_at, updated_at, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        messages     = excluded.messages,
                        iteration    = excluded.iteration,
                        tool_log     = excluded.tool_log,
                        status       = excluded.status,
                        updated_at   = excluded.updated_at,
                        metadata     = excluded.metadata
                    """,
                    (
                        session_id,
                        task,
                        json.dumps(messages[-40:]),   # keep last 40 msgs only
                        iteration,
                        json.dumps(tool_log[-30:]),   # keep last 30 tool calls
                        status,
                        project_name,
                        backend,
                        now,
                        now,
                        json.dumps(metadata or {}),
                    ),
                )
                conn.commit()
        except Exception:
            pass  # Non-fatal — don't crash the agent loop on DB hiccups
        return session_id

    def mark_complete(self, session_id: str):
        self._set_status(session_id, "completed")

    def mark_interrupted(self, session_id: str):
        self._set_status(session_id, "interrupted")

    def _set_status(self, session_id: str, status: str):
        try:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE agent_sessions SET status=?, updated_at=? WHERE session_id=?",
                    (status, time.time(), session_id),
                )
                conn.commit()
        except Exception:
            pass

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_active(self, max_age_hours: float = 48.0) -> Optional[AgentSession]:
        """Return the most-recently-updated active session, if any."""
        cutoff = time.time() - max_age_hours * 3600
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT * FROM agent_sessions
                    WHERE status = 'active' AND updated_at >= ?
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (cutoff,),
                ).fetchone()
        except Exception:
            return None
        return self._row_to_session(row) if row else None

    def get_interrupted(self, max_age_hours: float = 48.0) -> Optional[AgentSession]:
        """Return the most-recently interrupted session that can be resumed."""
        cutoff = time.time() - max_age_hours * 3600
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT * FROM agent_sessions
                    WHERE status IN ('active', 'interrupted') AND updated_at >= ?
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (cutoff,),
                ).fetchone()
        except Exception:
            return None
        return self._row_to_session(row) if row else None

    def get_by_id(self, session_id: str) -> Optional[AgentSession]:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM agent_sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
        except Exception:
            return None
        return self._row_to_session(row) if row else None

    def list_recent(self, limit: int = 10) -> list[AgentSession]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM agent_sessions ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        except Exception:
            return []
        return [self._row_to_session(r) for r in rows]

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_session(row) -> AgentSession:
        return AgentSession(
            session_id=row["session_id"],
            task=row["task"],
            messages=json.loads(row["messages"] or "[]"),
            iteration=row["iteration"],
            tool_log=json.loads(row["tool_log"] or "[]"),
            status=row["status"],
            project_name=row["project_name"],
            backend=row["backend"] or "ollama",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=json.loads(row["metadata"] or "{}"),
        )


# ── Convenience: "please continue" phrase detection ───────────────────────────

_RESUME_PHRASES = (
    "please continue",
    "continue from where",
    "continue from last",
    "pick up where",
    "keep going",
    "resume the task",
    "finish the task",
    "continue the task",
    "carry on",
    "continue working",
    "resume where",
)


def is_resume_request(text: str) -> bool:
    """True if the user's message is asking to continue a previous session."""
    lower = text.lower().strip()
    return any(phrase in lower for phrase in _RESUME_PHRASES)


# Module-level singleton so import is cheap
_store: Optional[SessionStore] = None


def get_store() -> SessionStore:
    global _store
    if _store is None:
        _store = SessionStore()
    return _store
