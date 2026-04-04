"""Connection configuration normalization helpers extracted from server.py."""
from __future__ import annotations

from typing import Optional


def normalize_domain(value: str | None) -> str:
    domain = str(value or "axon.edudashpro.org.za").strip()
    domain = domain.replace("https://", "").replace("http://", "").strip().strip("/")
    return domain or "axon.edudashpro.org.za"


def normalize_public_base_url(value: str | None, domain: str) -> str:
    url = str(value or "").strip()
    if not url:
        return f"https://{domain}"
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    return url.rstrip("/")


def connection_config(
    settings: Optional[dict] = None,
    *,
    read_settings_sync_fn,
    setting_truthy_fn,
) -> dict:
    settings = settings or read_settings_sync_fn()
    stable_domain = normalize_domain(settings.get("stable_domain"))
    public_base_url = normalize_public_base_url(settings.get("public_base_url"), stable_domain)
    tunnel_mode = str(settings.get("tunnel_mode") or "trycloudflare").strip() or "trycloudflare"
    cloudflare_tunnel_token = str(settings.get("cloudflare_tunnel_token") or "").strip()
    return {
        "stable_domain": stable_domain,
        "public_base_url": public_base_url,
        "stable_domain_enabled": setting_truthy_fn(settings.get("stable_domain_enabled")),
        "tunnel_mode": tunnel_mode,
        "cloudflare_tunnel_token": cloudflare_tunnel_token,
        "named_tunnel_ready": tunnel_mode == "named" and bool(cloudflare_tunnel_token),
    }
