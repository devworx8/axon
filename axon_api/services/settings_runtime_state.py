"""Synchronous settings access helpers extracted from server.py."""
from __future__ import annotations


def read_settings_sync(
    db_path,
    *,
    managed_connection_fn,
    sqlite_row_factory,
) -> dict:
    try:
        with managed_connection_fn(db_path, row_factory=sqlite_row_factory) as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
            return {str(row["key"]): row["value"] for row in rows}
    except Exception:
        return {}


def setting_truthy(raw, default: bool = False) -> bool:
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}
