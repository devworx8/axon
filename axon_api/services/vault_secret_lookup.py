"""Helpers for reading named secrets from the unlocked Secure Vault."""

from __future__ import annotations

from collections.abc import Iterable

import vault as devvault


async def vault_secret_value_by_name(
    db,
    *,
    secret_names: Iterable[str],
) -> str:
    key = devvault.VaultSession.get_key()
    if not key:
        return ""

    wanted = {str(name or "").strip().lower() for name in secret_names if str(name or "").strip()}
    if not wanted:
        return ""

    cur = await db.execute("SELECT id, name FROM vault_secrets ORDER BY id DESC")
    rows = await cur.fetchall()
    for row in rows:
        secret_name = str(row["name"] or "").strip().lower()
        if secret_name not in wanted:
            continue
        secret = await devvault.vault_get_secret(db, int(row["id"]), key)
        value = str((secret or {}).get("password") or "").strip()
        if value:
            return value
    return ""


async def vault_secret_status_by_name(
    db,
    *,
    secret_names: Iterable[str],
) -> dict[str, object]:
    wanted = {str(name or "").strip().lower() for name in secret_names if str(name or "").strip()}
    if not wanted:
        return {"value": "", "present": False, "unlocked": devvault.VaultSession.get_key() is not None}

    cur = await db.execute("SELECT id, name FROM vault_secrets ORDER BY id DESC")
    rows = await cur.fetchall()
    matches = [row for row in rows if str(row["name"] or "").strip().lower() in wanted]
    key = devvault.VaultSession.get_key()
    if not key:
        return {"value": "", "present": bool(matches), "unlocked": False}

    for row in matches:
        secret = await devvault.vault_get_secret(db, int(row["id"]), key)
        value = str((secret or {}).get("password") or "").strip()
        if value:
            return {"value": value, "present": True, "unlocked": True}

    return {"value": "", "present": bool(matches), "unlocked": True}
