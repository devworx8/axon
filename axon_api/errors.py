"""Standardised error response helpers for Axon API routes."""
from __future__ import annotations

from fastapi.responses import JSONResponse


def error_response(status: int, code: str, detail: str) -> JSONResponse:
    """Return a structured JSON error response.

    Usage::

        return error_response(400, "invalid_input", "Limit must be between 1 and 500")
        return error_response(423, "vault_locked", "Vault is locked")
    """
    return JSONResponse(
        status_code=status,
        content={"error": code, "detail": detail},
    )


# ── Common error codes ───────────────────────────────────────────────────────

VAULT_LOCKED = ("vault_locked", "Vault is locked — unlock it first")
AUTH_REQUIRED = ("auth_required", "Authentication required")
INVALID_INPUT = ("invalid_input", "Invalid input")
NOT_FOUND = ("not_found", "Resource not found")
FEATURE_DISABLED = ("feature_disabled", "This feature is not enabled")
RATE_LIMITED = ("rate_limited", "Too many requests — try again later")
