from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def managed_connection(
    db_path: str | Path,
    *,
    timeout: float = 10,
    row_factory: sqlite3.Row | None = sqlite3.Row,
) -> Iterator[sqlite3.Connection]:
    """Yield a sqlite3 connection and always close it on exit."""
    conn = sqlite3.connect(str(db_path), timeout=timeout)
    if row_factory is not None:
        conn.row_factory = row_factory
    try:
        yield conn
    finally:
        conn.close()
