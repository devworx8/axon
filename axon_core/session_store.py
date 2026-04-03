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
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from axon_data.sqlite_utils import managed_connection

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

_MEMORY_FALLBACK_SESSIONS: dict[str, "AgentSession"] = {}


@dataclass
class AgentSession:
    session_id: str
    task: str
    messages: list[dict]
    iteration: int
    tool_log: list[dict]
    status: str                   # "active" | "completed" | "interrupted" | "approval_required"
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

    def _connect(self):
        return managed_connection(self.db_path, timeout=10, row_factory=sqlite3.Row)

    def _ensure_table(self):
        try:
            with self._connect() as conn:
                conn.execute(_CREATE_SQL)
                conn.commit()
        except Exception:
            pass  # DB not ready yet — will retry on first write

    @staticmethod
    def _remember_fallback(session: AgentSession):
        _MEMORY_FALLBACK_SESSIONS[session.session_id] = deepcopy(session)

    @staticmethod
    def _set_fallback_status(session_id: str, status: str):
        session = _MEMORY_FALLBACK_SESSIONS.get(session_id)
        if not session:
            return
        session.status = status
        session.updated_at = time.time()
        _MEMORY_FALLBACK_SESSIONS[session_id] = deepcopy(session)

    @staticmethod
    def _fallback_recent(*statuses: str, max_age_hours: float = 48.0) -> Optional[AgentSession]:
        cutoff = time.time() - max_age_hours * 3600
        candidates = [
            deepcopy(session)
            for session in _MEMORY_FALLBACK_SESSIONS.values()
            if session.status in statuses and session.updated_at >= cutoff
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda item: item.updated_at, reverse=True)
        return candidates[0]

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
        session = AgentSession(
            session_id=session_id,
            task=task,
            messages=deepcopy(messages[-40:]),
            iteration=iteration,
            tool_log=deepcopy(tool_log[-30:]),
            status=status,
            project_name=project_name,
            backend=backend,
            created_at=now,
            updated_at=now,
            metadata=deepcopy(metadata or {}),
        )
        existing = _MEMORY_FALLBACK_SESSIONS.get(session_id)
        if existing:
            session.created_at = existing.created_at
        self._remember_fallback(session)
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
        self._set_fallback_status(session_id, status)
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
        return self._row_to_session(row) if row else self._fallback_recent("active", max_age_hours=max_age_hours)

    @staticmethod
    def _same_workspace(
        session: AgentSession,
        *,
        workspace_id: Optional[int] = None,
        workspace_path: str = "",
        project_name: Optional[str] = None,
    ) -> bool:
        metadata = session.metadata or {}
        if workspace_id is not None and str(metadata.get("workspace_id") or "").strip() == str(workspace_id):
            return True
        if workspace_path:
            left = str(metadata.get("workspace_path") or "").strip()
            if left and Path(left).expanduser().resolve(strict=False) == Path(workspace_path).expanduser().resolve(strict=False):
                return True
        if project_name:
            label = str(session.project_name or metadata.get("project_name") or "").strip().lower()
            if label and label == str(project_name).strip().lower():
                return True
        return False

    @classmethod
    def _sessions_share_workspace(cls, left: AgentSession, right: AgentSession) -> bool:
        right_meta = right.metadata or {}
        return cls._same_workspace(
            left,
            workspace_id=right_meta.get("workspace_id"),
            workspace_path=str(right_meta.get("workspace_path") or ""),
            project_name=str(right.project_name or right_meta.get("project_name") or ""),
        ) or cls._same_workspace(
            right,
            workspace_id=(left.metadata or {}).get("workspace_id"),
            workspace_path=str((left.metadata or {}).get("workspace_path") or ""),
            project_name=str(left.project_name or (left.metadata or {}).get("project_name") or ""),
        )

    @classmethod
    def _filter_shadowed_paused(
        cls,
        paused_sessions: list[AgentSession],
        recent_sessions: list[AgentSession],
    ) -> list[AgentSession]:
        filtered: list[AgentSession] = []
        for session in paused_sessions:
            shadowed = any(
                candidate.session_id != session.session_id
                and candidate.updated_at > session.updated_at
                and candidate.status not in {"interrupted", "approval_required"}
                and cls._sessions_share_workspace(session, candidate)
                for candidate in recent_sessions
            )
            if not shadowed:
                filtered.append(session)
        return filtered

    def _pick_resumable(
        self,
        paused_sessions: list[AgentSession],
        active_sessions: list[AgentSession],
        *,
        preferred_session_id: str = "",
        workspace_id: Optional[int] = None,
        workspace_path: str = "",
        project_name: Optional[str] = None,
        strict_workspace: bool = False,
    ) -> Optional[AgentSession]:
        if preferred_session_id:
            for session in paused_sessions + active_sessions:
                if session.session_id == preferred_session_id:
                    return session

        workspace_paused = [
            session
            for session in paused_sessions
            if self._same_workspace(
                session,
                workspace_id=workspace_id,
                workspace_path=workspace_path,
                project_name=project_name,
            )
        ]
        workspace_active = [
            session
            for session in active_sessions
            if self._same_workspace(
                session,
                workspace_id=workspace_id,
                workspace_path=workspace_path,
                project_name=project_name,
            )
        ]

        if strict_workspace and (workspace_id is not None or workspace_path or project_name):
            for pool, status in (
                (workspace_paused, "interrupted"),
                (workspace_paused, "approval_required"),
                (workspace_active, "active"),
            ):
                match = next((session for session in pool if session.status == status), None)
                if match:
                    return match
            return None

        for pool, status in (
            (workspace_paused, "interrupted"),
            (workspace_paused, "approval_required"),
            (paused_sessions, "interrupted"),
            (paused_sessions, "approval_required"),
            (workspace_active, "active"),
            (active_sessions, "active"),
        ):
            match = next((session for session in pool if session.status == status), None)
            if match:
                return match
        return None

    def get_interrupted(
        self,
        max_age_hours: float = 8.0,
        *,
        preferred_session_id: str = "",
        workspace_id: Optional[int] = None,
        workspace_path: str = "",
        project_name: Optional[str] = None,
        strict_workspace: bool = False,
    ) -> Optional[AgentSession]:
        """Return the best resumable session, preferring the current workspace first."""
        paused_cutoff = time.time() - max_age_hours * 3600
        active_cutoff = time.time() - min(max_age_hours, 2.0) * 3600
        try:
            with self._connect() as conn:
                paused_rows = conn.execute(
                    """
                    SELECT * FROM agent_sessions
                    WHERE status IN ('interrupted', 'approval_required') AND updated_at >= ?
                    ORDER BY updated_at DESC
                    LIMIT 40
                    """,
                    (paused_cutoff,),
                ).fetchall()

                active_rows = conn.execute(
                    """
                    SELECT * FROM agent_sessions
                    WHERE status = 'active' AND updated_at >= ?
                    ORDER BY updated_at DESC
                    LIMIT 20
                    """,
                    (active_cutoff,),
                ).fetchall()

                recent_rows = conn.execute(
                    """
                    SELECT * FROM agent_sessions
                    WHERE updated_at >= ?
                    ORDER BY updated_at DESC
                    LIMIT 120
                    """,
                    (paused_cutoff,),
                ).fetchall()
        except Exception:
            paused_sessions = [
                deepcopy(session)
                for session in sorted(
                    _MEMORY_FALLBACK_SESSIONS.values(),
                    key=lambda item: item.updated_at,
                    reverse=True,
                )
                if session.status in {"interrupted", "approval_required"} and session.updated_at >= paused_cutoff
            ]
            active_sessions = [
                deepcopy(session)
                for session in sorted(
                    _MEMORY_FALLBACK_SESSIONS.values(),
                    key=lambda item: item.updated_at,
                    reverse=True,
                )
                if session.status == "active" and session.updated_at >= active_cutoff
            ]
            return self._pick_resumable(
                paused_sessions,
                active_sessions,
                preferred_session_id=preferred_session_id,
                workspace_id=workspace_id,
                workspace_path=workspace_path,
                project_name=project_name,
                strict_workspace=strict_workspace,
            )

        paused_sessions = [self._row_to_session(row) for row in paused_rows]
        active_sessions = [self._row_to_session(row) for row in active_rows]
        recent_sessions = [self._row_to_session(row) for row in recent_rows]
        seen = {session.session_id for session in paused_sessions + active_sessions}
        for session in sorted(
            _MEMORY_FALLBACK_SESSIONS.values(),
            key=lambda item: item.updated_at,
            reverse=True,
        ):
            if session.session_id in seen:
                continue
            if session.status in {"interrupted", "approval_required"} and session.updated_at >= paused_cutoff:
                paused_sessions.append(deepcopy(session))
            elif session.status == "active" and session.updated_at >= active_cutoff:
                active_sessions.append(deepcopy(session))
            if session.updated_at >= paused_cutoff:
                recent_sessions.append(deepcopy(session))

        if not preferred_session_id:
            paused_sessions = self._filter_shadowed_paused(paused_sessions, recent_sessions)

        return self._pick_resumable(
            paused_sessions,
            active_sessions,
            preferred_session_id=preferred_session_id,
            workspace_id=workspace_id,
            workspace_path=workspace_path,
            project_name=project_name,
            strict_workspace=strict_workspace,
        )

    def get_by_id(self, session_id: str) -> Optional[AgentSession]:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM agent_sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
        except Exception:
            session = _MEMORY_FALLBACK_SESSIONS.get(session_id)
            return deepcopy(session) if session else None
        if row:
            return self._row_to_session(row)
        session = _MEMORY_FALLBACK_SESSIONS.get(session_id)
        return deepcopy(session) if session else None

    def list_recent(self, limit: int = 10) -> list[AgentSession]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM agent_sessions ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        except Exception:
            rows = []
        sessions = [self._row_to_session(r) for r in rows]
        seen = {session.session_id for session in sessions}
        fallback = [
            deepcopy(session)
            for session in sorted(
                _MEMORY_FALLBACK_SESSIONS.values(),
                key=lambda item: item.updated_at,
                reverse=True,
            )
            if session.session_id not in seen
        ]
        return (sessions + fallback)[:limit]

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
    "go ahead",
    "proceed",
)

# Also match bare "continue" as an exact match
_RESUME_EXACT = ("continue", "go", "yes continue", "yes", "ok", "ok continue")


def is_resume_request(text: str) -> bool:
    """True if the user's message is asking to continue a previous session."""
    lower = text.lower().strip()
    if lower in _RESUME_EXACT:
        return True
    return any(phrase in lower for phrase in _RESUME_PHRASES)


# Module-level singleton so import is cheap
_store: Optional[SessionStore] = None


def get_store() -> SessionStore:
    global _store
    if _store is None:
        _store = SessionStore()
    return _store
