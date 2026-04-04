"""Connection, tunnel, and path helpers extracted from server.py."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


def probe_public_origin(
    public_base_url: str,
    enabled: bool,
    *,
    domain_probe_cache: dict,
    time_module,
    urlrequest_module,
    urlerror_module,
    json_module,
) -> dict:
    target = str(public_base_url or "").strip()
    if not enabled or not target:
        return {
            "active": False,
            "status": "planned",
            "detail": "Stable domain is not enabled yet.",
        }
    now = time_module.time()
    if domain_probe_cache.get("url") == target and now - float(domain_probe_cache.get("checked_at") or 0) < 60:
        return {
            "active": bool(domain_probe_cache.get("active")),
            "status": str(domain_probe_cache.get("status") or "configured"),
            "detail": str(domain_probe_cache.get("detail") or ""),
        }

    probe_url = f"{target.rstrip('/')}/api/health"
    active = False
    status = "configured"
    detail = "Stable domain is configured, but Axon has not answered on /api/health yet."
    try:
        request = urlrequest_module.Request(probe_url, headers={"Accept": "application/json"})
        with urlrequest_module.urlopen(request, timeout=3) as response:
            raw = response.read().decode("utf-8", errors="replace")
            payload = json_module.loads(raw)
            active = payload.get("status") == "ok"
            status = "active" if active else "configured"
            detail = "Stable domain reaches Axon successfully." if active else "Stable domain responded, but Axon health was not OK."
    except urlerror_module.HTTPError as exc:
        detail = f"Stable domain responded with HTTP {exc.code}. It is not pointing at Axon yet."
    except Exception as exc:
        detail = f"Stable domain is configured, but Axon could not confirm it yet: {exc}"

    domain_probe_cache.update(
        {
            "url": target,
            "active": active,
            "status": status,
            "detail": detail,
            "checked_at": now,
        }
    )
    return {"active": active, "status": status, "detail": detail}


def connection_snapshot(connection_config, probe_public_origin_fn, read_tunnel_url_fn) -> dict:
    config = connection_config()
    probe = probe_public_origin_fn(config["public_base_url"], config["stable_domain_enabled"])
    tunnel_url = read_tunnel_url_fn(config)
    domain_active = bool(probe["active"])
    if domain_active:
        state = "domain_active"
        label = "Domain Active"
    elif tunnel_url:
        state = "tunnel_active"
        label = "Tunnel Active"
    else:
        state = "local_only"
        label = "Local Only"
    return {
        "connected": True,
        "state": state,
        "label": label,
        "local_only": not bool(tunnel_url) and not domain_active,
        "tunnel_active": bool(tunnel_url),
        "tunnel_url": tunnel_url,
        "domain_active": domain_active,
        "stable_domain": config["stable_domain"],
        "stable_domain_url": config["public_base_url"],
        "stable_domain_enabled": config["stable_domain_enabled"],
        "tunnel_mode": config["tunnel_mode"],
        "probe": probe,
    }


def read_tunnel_url(
    config: Optional[dict] = None,
    *,
    connection_config,
    tunnel_running_fn,
    tunnel_log: Path,
) -> str:
    config = config or connection_config()
    try:
        if config.get("tunnel_mode") == "named" and tunnel_running_fn():
            return config.get("public_base_url") or ""
        if tunnel_log.exists():
            match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", tunnel_log.read_text())
            return match.group(0) if match else ""
    except Exception:
        pass
    return ""


def tunnel_running(*, tunnel_pid: Path, subprocess_module) -> bool:
    try:
        if tunnel_pid.exists():
            pid = int(tunnel_pid.read_text().strip())
            subprocess_module.check_output(["kill", "-0", str(pid)], stderr=subprocess_module.DEVNULL)
            return True
    except Exception:
        pass
    return False


def safe_path(rel_or_abs: str, *, home_path: Path, http_exception_cls) -> Path:
    path = Path(rel_or_abs).expanduser()
    if not path.is_absolute():
        path = home_path / path
    path = path.resolve()
    if not str(path).startswith(str(home_path)):
        raise http_exception_cls(403, "Access outside home directory is not allowed.")
    return path
