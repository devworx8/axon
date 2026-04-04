"""Request models for connector relationship routes."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class WorkspaceRelationshipRequest(BaseModel):
    external_system: str
    external_id: str = ""
    relationship_type: str = "primary"
    external_name: str = ""
    external_url: str = ""
    status: str = "active"
    meta: dict[str, Any] | None = Field(default=None)


class WorkspaceConnectorConnectRequest(BaseModel):
    external_system: str
    external_id: str = ""
    relationship_type: str = "primary"
    external_name: str = ""
    external_url: str = ""
    status: str = "active"
    token: str = ""
    secret: str = ""
    url: str = ""
    org_slug: str = ""
    project_slugs: str = ""
    mode: str = ""
    auth: dict[str, Any] | None = Field(default=None)
    meta: dict[str, Any] | None = Field(default=None)


class WorkspaceConnectorReconcileRequest(BaseModel):
    persist_inferred: bool = True
    allow_repo_writes: bool = False
