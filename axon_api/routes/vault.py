"""Vault routes extracted from the legacy server facade."""
from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel


class VaultSetupRequest(BaseModel):
    master_password: str


class VaultUnlockRequest(BaseModel):
    master_password: str
    totp_code: str
    remember_me: bool = False


class VaultSecretCreate(BaseModel):
    name: str
    category: str = "general"
    username: str = ""
    password: str = ""
    url: str = ""
    notes: str = ""


class VaultSecretUpdate(BaseModel):
    name: str
    category: str = "general"
    username: str = ""
    password: str = ""
    url: str = ""
    notes: str = ""


class VaultRouteHandlers:
    def __init__(
        self,
        *,
        db_module: Any,
        devvault_module: Any,
        dev_local_vault_bypass_active: Callable[[Request | None], bool],
    ) -> None:
        self._db = db_module
        self._devvault = devvault_module
        self._dev_local_vault_bypass_active = dev_local_vault_bypass_active

    async def vault_status(self, request: Request):
        if self._dev_local_vault_bypass_active(request):
            return {"is_setup": False, "is_unlocked": True, "ttl_remaining": 0, "dev_bypass": True}
        async with self._db.get_db() as conn:
            is_setup = await self._devvault.vault_is_setup(conn)
        return {
            "is_setup": is_setup,
            "is_unlocked": self._devvault.VaultSession.is_unlocked(),
            "ttl_remaining": self._devvault.VaultSession.ttl_remaining(),
            "dev_bypass": False,
        }

    async def vault_provider_keys(self, request: Request):
        if self._dev_local_vault_bypass_active(request):
            return {"unlocked": True, "resolved": {}, "dev_bypass": True}
        result = {}
        if self._devvault.VaultSession.is_unlocked():
            async with self._db.get_db() as conn:
                resolved = await self._devvault.vault_resolve_all_provider_keys(conn)
                for provider_id in resolved:
                    result[provider_id] = True
        return {"unlocked": self._devvault.VaultSession.is_unlocked(), "resolved": result, "dev_bypass": False}

    async def vault_setup(self, body: VaultSetupRequest):
        async with self._db.get_db() as conn:
            already = await self._devvault.vault_is_setup(conn)
            if already:
                raise HTTPException(400, "Vault is already set up. Reset not supported via API.")
            result = await self._devvault.setup_vault(conn, body.master_password)
        return result

    async def vault_unlock(self, body: VaultUnlockRequest):
        ttl = self._devvault.VaultSession.EXTENDED_TTL if body.remember_me else self._devvault.VaultSession.DEFAULT_TTL
        async with self._db.get_db() as conn:
            ok, err = await self._devvault.unlock_vault(conn, body.master_password, body.totp_code, session_ttl=ttl)
        if not ok:
            raise HTTPException(401, err)
        return {"unlocked": True, "session_ttl": ttl, "ttl_label": "24 hours" if body.remember_me else "1 hour"}

    async def vault_lock(self):
        self._devvault.VaultSession.lock()
        return {"locked": True}

    async def list_vault_secrets(self):
        if not self._devvault.VaultSession.is_unlocked():
            raise HTTPException(403, "Vault is locked")
        async with self._db.get_db() as conn:
            secrets = await self._devvault.vault_list_secrets(conn)
        return secrets

    async def get_vault_secret(self, secret_id: int):
        key = self._devvault.VaultSession.get_key()
        if not key:
            raise HTTPException(403, "Vault is locked")
        async with self._db.get_db() as conn:
            secret = await self._devvault.vault_get_secret(conn, secret_id, key)
        if not secret:
            raise HTTPException(404, "Secret not found")
        return secret

    async def create_vault_secret(self, body: VaultSecretCreate):
        key = self._devvault.VaultSession.get_key()
        if not key:
            raise HTTPException(403, "Vault is locked")
        async with self._db.get_db() as conn:
            secret_id = await self._devvault.vault_add_secret(
                conn,
                key,
                body.name,
                body.category,
                body.username,
                body.password,
                body.url,
                body.notes,
            )
            await self._db.log_event(conn, "vault", f"Secret added: {body.name}")
        return {"id": secret_id, "name": body.name}

    async def update_vault_secret(self, secret_id: int, body: VaultSecretUpdate):
        key = self._devvault.VaultSession.get_key()
        if not key:
            raise HTTPException(403, "Vault is locked")
        async with self._db.get_db() as conn:
            await self._devvault.vault_update_secret(
                conn,
                key,
                secret_id,
                body.name,
                body.category,
                body.username,
                body.password,
                body.url,
                body.notes,
            )
            await self._db.log_event(conn, "vault", f"Secret updated: {body.name}")
        return {"updated": True}

    async def delete_vault_secret(self, secret_id: int):
        if not self._devvault.VaultSession.is_unlocked():
            raise HTTPException(403, "Vault is locked")
        async with self._db.get_db() as conn:
            await self._devvault.vault_delete_secret(conn, secret_id)
        return {"deleted": True}


def build_vault_router(**deps: Any) -> tuple[APIRouter, VaultRouteHandlers]:
    handlers = VaultRouteHandlers(**deps)
    router = APIRouter(tags=["vault"])
    router.add_api_route("/api/vault/status", handlers.vault_status, methods=["GET"])
    router.add_api_route("/api/vault/provider-keys", handlers.vault_provider_keys, methods=["GET"])
    router.add_api_route("/api/vault/setup", handlers.vault_setup, methods=["POST"])
    router.add_api_route("/api/vault/unlock", handlers.vault_unlock, methods=["POST"])
    router.add_api_route("/api/vault/lock", handlers.vault_lock, methods=["POST"])
    router.add_api_route("/api/vault/secrets", handlers.list_vault_secrets, methods=["GET"])
    router.add_api_route("/api/vault/secrets/{secret_id}", handlers.get_vault_secret, methods=["GET"])
    router.add_api_route("/api/vault/secrets", handlers.create_vault_secret, methods=["POST"])
    router.add_api_route("/api/vault/secrets/{secret_id}", handlers.update_vault_secret, methods=["PUT"])
    router.add_api_route("/api/vault/secrets/{secret_id}", handlers.delete_vault_secret, methods=["DELETE"])
    return router, handlers
