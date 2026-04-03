"""Axon — Usage log repository.

Persists per-call usage data (tokens, cost, backend) so it survives restarts
and can be queried for quota dashboards and historical trends.
"""
from __future__ import annotations

import aiosqlite


async def log_usage(
    db: aiosqlite.Connection,
    *,
    backend: str,
    model: str = "",
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: float = 0.0,
    session_id: str = "",
    workspace_id: int | None = None,
    tool_name: str = "",
) -> int:
    cur = await db.execute(
        """INSERT INTO usage_log
           (backend, model, tokens_in, tokens_out, cost_usd,
            session_id, workspace_id, tool_name)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (backend, model, tokens_in, tokens_out, cost_usd,
         session_id, workspace_id, tool_name),
    )
    await db.commit()
    return cur.lastrowid


async def get_usage_summary(
    db: aiosqlite.Connection,
    *,
    days: int = 30,
) -> dict:
    """Aggregate usage over the last N days."""
    cur = await db.execute(
        """SELECT
               COALESCE(SUM(tokens_in), 0)  AS total_tokens_in,
               COALESCE(SUM(tokens_out), 0) AS total_tokens_out,
               COALESCE(SUM(cost_usd), 0)   AS total_cost_usd,
               COUNT(*)                       AS total_calls
           FROM usage_log
           WHERE created_at >= datetime('now', ?)""",
        (f"-{days} days",),
    )
    row = await cur.fetchone()
    return dict(row) if row else {}


async def get_daily_usage(
    db: aiosqlite.Connection,
    *,
    days: int = 30,
) -> list[dict]:
    """Return per-day breakdown for charts."""
    cur = await db.execute(
        """SELECT
               date(created_at) AS day,
               SUM(tokens_in)   AS tokens_in,
               SUM(tokens_out)  AS tokens_out,
               SUM(cost_usd)    AS cost_usd,
               COUNT(*)         AS calls
           FROM usage_log
           WHERE created_at >= datetime('now', ?)
           GROUP BY day ORDER BY day""",
        (f"-{days} days",),
    )
    rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_usage_by_backend(
    db: aiosqlite.Connection,
    *,
    days: int = 30,
) -> list[dict]:
    """Return usage grouped by backend provider."""
    cur = await db.execute(
        """SELECT
               backend,
               SUM(tokens_in)  AS tokens_in,
               SUM(tokens_out) AS tokens_out,
               SUM(cost_usd)   AS cost_usd,
               COUNT(*)        AS calls
           FROM usage_log
           WHERE created_at >= datetime('now', ?)
           GROUP BY backend ORDER BY cost_usd DESC""",
        (f"-{days} days",),
    )
    rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_quota_status(
    db: aiosqlite.Connection,
    *,
    monthly_token_budget: int = 0,
    monthly_cost_budget_usd: float = 0.0,
) -> dict:
    """Check current month usage against budget limits."""
    cur = await db.execute(
        """SELECT
               COALESCE(SUM(tokens_in + tokens_out), 0) AS tokens_used,
               COALESCE(SUM(cost_usd), 0)               AS cost_used,
               COUNT(*)                                   AS calls
           FROM usage_log
           WHERE created_at >= date('now', 'start of month')"""
    )
    row = await cur.fetchone()
    data = dict(row) if row else {"tokens_used": 0, "cost_used": 0.0, "calls": 0}
    data["monthly_token_budget"] = monthly_token_budget
    data["monthly_cost_budget_usd"] = monthly_cost_budget_usd
    if monthly_token_budget > 0:
        data["token_pct"] = round(data["tokens_used"] / monthly_token_budget * 100, 1)
    else:
        data["token_pct"] = 0.0
    if monthly_cost_budget_usd > 0:
        data["cost_pct"] = round(data["cost_used"] / monthly_cost_budget_usd * 100, 1)
    else:
        data["cost_pct"] = 0.0
    return data
