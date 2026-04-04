"""Chat history read guards extracted from server.py."""
from __future__ import annotations

from typing import Optional


def is_chat_history_db_corruption(exc: Exception, *, sqlite_database_error_cls) -> bool:
    if not isinstance(exc, sqlite_database_error_cls):
        return False
    text = str(exc).lower()
    return (
        "database disk image is malformed" in text
        or "file is not a database" in text
        or "database or disk is full" in text
        or "malformed" in text
    )


def chat_history_db_detail() -> str:
    return (
        "Chat history is temporarily unavailable because the Axon database needs repair or restore. "
        "Export a backup if possible, then run an integrity check on ~/.devbrain/devbrain.db."
    )


async def load_chat_history_rows(
    conn,
    *,
    db_module,
    project_id: Optional[int] = None,
    limit: int = 20,
    degrade_to_empty: bool = False,
    is_chat_history_db_corruption_fn,
    chat_history_db_detail_fn,
    http_exception_cls,
    print_fn=print,
):
    try:
        return await db_module.get_chat_history(conn, project_id=project_id, limit=limit)
    except Exception as exc:
        if not is_chat_history_db_corruption_fn(exc):
            raise
        print_fn(f"[Axon] Chat history read failed: {exc}")
        if degrade_to_empty:
            return []
        raise http_exception_cls(503, chat_history_db_detail_fn())
