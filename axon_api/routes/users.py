"""User and team routes extracted from the legacy server facade."""
from __future__ import annotations

import socket
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class UserCreate(BaseModel):
    name: str
    email: str | None = ""
    username: str | None = ""
    role: str | None = "operator"


class UserRouteHandlers:
    def __init__(self, *, db_module: Any) -> None:
        self._db = db_module

    async def list_users(self):
        async with self._db.get_db() as conn:
            cur = await conn.execute(
                "SELECT id, name, email, username, avatar_url, role, status, is_active, created_at FROM users ORDER BY id"
            )
            rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def create_user(self, body: UserCreate):
        async with self._db.get_db() as conn:
            cur = await conn.execute(
                "INSERT INTO users (name, email, username, role) VALUES (?, ?, ?, ?)",
                (body.name, body.email or "", body.username or "", body.role or "operator"),
            )
            await conn.commit()
            user_id = cur.lastrowid
            await conn.execute(
                "INSERT OR IGNORE INTO user_profiles (user_id) VALUES (?)",
                (user_id,),
            )
            await conn.commit()
            row = await (await conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))).fetchone()
        return dict(row)

    async def get_current_user(self):
        async with self._db.get_db() as conn:
            row = await (
                await conn.execute(
                    "SELECT * FROM users WHERE is_active = 1 ORDER BY id LIMIT 1"
                )
            ).fetchone()
            if row:
                return dict(row)
            cur = await conn.execute(
                "INSERT INTO users (name, email, username, role) VALUES (?, ?, ?, 'operator')",
                ("Local Operator", "", socket.gethostname().lower()),
            )
            await conn.commit()
            user_id = cur.lastrowid
            await conn.execute("INSERT OR IGNORE INTO user_profiles (user_id) VALUES (?)", (user_id,))
            await conn.commit()
            row = await (await conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))).fetchone()
        return dict(row)

    async def update_user(self, user_id: int, body: dict):
        allowed = {"name", "email", "username", "avatar_url", "role", "status"}
        updates = {key: value for key, value in body.items() if key in allowed}
        if not updates:
            raise HTTPException(400, "No valid fields to update")
        async with self._db.get_db() as conn:
            set_clauses = ", ".join(f"{key} = ?" for key in updates)
            values = list(updates.values()) + [user_id]
            await conn.execute(
                f"UPDATE users SET {set_clauses}, updated_at = datetime('now') WHERE id = ?",
                values,
            )
            await conn.commit()
            row = await (await conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))).fetchone()
        return dict(row) if row else {}

    async def list_teams(self):
        async with self._db.get_db() as conn:
            cur = await conn.execute("SELECT * FROM teams ORDER BY id")
            rows = await cur.fetchall()
        return [dict(row) for row in rows]


def build_user_router(*, db_module: Any) -> tuple[APIRouter, UserRouteHandlers]:
    handlers = UserRouteHandlers(db_module=db_module)
    router = APIRouter(tags=["users"])
    router.add_api_route("/api/users", handlers.list_users, methods=["GET"])
    router.add_api_route("/api/users", handlers.create_user, methods=["POST"])
    router.add_api_route("/api/users/me", handlers.get_current_user, methods=["GET"])
    router.add_api_route("/api/users/{user_id}", handlers.update_user, methods=["PATCH"])
    router.add_api_route("/api/teams", handlers.list_teams, methods=["GET"])
    return router, handlers
