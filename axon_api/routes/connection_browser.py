"""Mobile/browser/desktop/tunnel routes extracted from server.py."""
from __future__ import annotations

import asyncio
import base64
import io
import os
import re
import shutil
import socket
import subprocess
import textwrap
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from PIL import Image, ImageDraw
from pydantic import BaseModel


class BrowserSessionUpdate(BaseModel):
    connected: Optional[bool] = None
    url: Optional[str] = None
    title: Optional[str] = None
    mode: Optional[str] = None
    control_owner: Optional[str] = None
    control_state: Optional[str] = None
    attached_preview_url: Optional[str] = None
    attached_preview_status: Optional[str] = None
    attached_workspace_id: Optional[int] = None
    attached_workspace_name: Optional[str] = None
    attached_auto_session_id: Optional[str] = None
    attached_scope_key: Optional[str] = None
    attached_source_workspace_path: Optional[str] = None


class BrowserActionProposalCreate(BaseModel):
    action_type: str
    summary: str
    target: Optional[str] = None
    value: Optional[str] = None
    url: Optional[str] = None
    risk: Optional[str] = "medium"
    scope: Optional[str] = "browser_act"
    requires_confirmation: Optional[bool] = True
    metadata: Optional[dict] = None


class ConnectionBrowserRouteHandlers:
    def __init__(
        self,
        *,
        db_module: Any,
        browser_action_state: dict[str, Any],
        connection_config: Callable[[], dict[str, Any]],
        probe_public_origin: Callable[[str, bool], dict[str, Any]],
        read_tunnel_url: Callable[[dict[str, Any] | None], str],
        tunnel_running: Callable[[], bool],
        now_iso: Callable[[], str],
        serialize_browser_action_state: Callable[[], dict[str, Any]],
        normalize_browser_session: Callable[..., dict[str, Any]],
        next_browser_action_id: Callable[[], int],
        normalize_browser_action_payload: Callable[[dict[str, Any]], dict[str, Any]],
        find_approved_browser_action: Callable[[int], Optional[dict[str, Any]]],
        port: int,
        tunnel_log: Path,
        tunnel_pid: Path,
        tunnel_bin: Path,
    ) -> None:
        self._db = db_module
        self._browser_action_state = browser_action_state
        self._connection_config = connection_config
        self._probe_public_origin = probe_public_origin
        self._read_tunnel_url = read_tunnel_url
        self._tunnel_running = tunnel_running
        self._now_iso = now_iso
        self._serialize_browser_action_state = serialize_browser_action_state
        self._normalize_browser_session = normalize_browser_session
        self._next_browser_action_id = next_browser_action_id
        self._normalize_browser_action_payload = normalize_browser_action_payload
        self._find_approved_browser_action = find_approved_browser_action
        self._port = port
        self._tunnel_log = tunnel_log
        self._tunnel_pid = tunnel_pid
        self._tunnel_bin = tunnel_bin

    async def mobile_info(self):
        config = self._connection_config()
        probe = self._probe_public_origin(config["public_base_url"], config["stable_domain_enabled"])
        tunnel_running = self._tunnel_running()

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.connect(("8.8.8.8", 80))
            local_ip = sock.getsockname()[0]
            sock.close()
        except Exception:
            local_ip = "127.0.0.1"

        tailscale_ip = ""
        try:
            for iface_ip in socket.getaddrinfo(socket.gethostname(), None):
                ip = iface_ip[4][0]
                if ip.startswith("100.") and not ip.startswith("100.127."):
                    tailscale_ip = ip
                    break
            if not tailscale_ip:
                out = subprocess.check_output(
                    ["ip", "-4", "addr", "show", "tailscale0"],
                    stderr=subprocess.DEVNULL,
                    timeout=3,
                ).decode()
                match = re.search(r"inet\s+(100\.\d+\.\d+\.\d+)", out)
                if match:
                    tailscale_ip = match.group(1)
        except Exception:
            pass

        cloudflared_url = self._read_tunnel_url(config)
        if probe["active"] and config["public_base_url"]:
            qr_url = config["public_base_url"]
        elif cloudflared_url:
            qr_url = cloudflared_url
        elif config["stable_domain_enabled"] and config["public_base_url"]:
            qr_url = config["public_base_url"]
        elif tailscale_ip:
            qr_url = f"http://{tailscale_ip}:{self._port}"
        else:
            qr_url = f"http://{local_ip}:{self._port}"

        qr_data_uri = ""
        try:
            import qrcode

            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=6,
                border=2,
            )
            qr.add_data(qr_url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            qr_data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        except Exception:
            pass

        return {
            "local_url": f"http://{local_ip}:{self._port}",
            "local_ip": local_ip,
            "tailscale_ip": tailscale_ip,
            "tailscale_url": f"http://{tailscale_ip}:{self._port}" if tailscale_ip else "",
            "cloudflared_url": cloudflared_url,
            "tunnel_running": tunnel_running,
            "stable_domain": config["stable_domain"],
            "stable_domain_url": config["public_base_url"],
            "stable_domain_enabled": config["stable_domain_enabled"],
            "stable_domain_status": probe["status"],
            "stable_domain_detail": probe["detail"],
            "tunnel_mode": config.get("tunnel_mode", "trycloudflare"),
            "named_tunnel_ready": config.get("named_tunnel_ready", False),
            "qr_url": qr_url,
            "port": self._port,
            "qr_data_uri": qr_data_uri,
        }

    async def browser_actions_status(self):
        return self._serialize_browser_action_state()

    async def update_browser_session(self, body: BrowserSessionUpdate):
        session = self._normalize_browser_session(
            self._browser_action_state["session"],
            connected=body.connected,
            url=str(body.url or "").strip() if body.url is not None else None,
            title=str(body.title or "").strip() if body.title is not None else None,
            mode=body.mode,
            control_owner=body.control_owner,
            control_state=body.control_state,
            attached_preview_url=body.attached_preview_url,
            attached_preview_status=body.attached_preview_status,
            attached_workspace_id=body.attached_workspace_id,
            attached_workspace_name=body.attached_workspace_name,
            attached_auto_session_id=body.attached_auto_session_id,
            attached_scope_key=body.attached_scope_key,
            attached_source_workspace_path=body.attached_source_workspace_path,
            last_seen_at=self._now_iso(),
        )
        self._browser_action_state["session"] = session
        return self._serialize_browser_action_state()

    async def create_browser_action_proposal(self, body: BrowserActionProposalCreate):
        created_at = self._now_iso()
        proposal = self._normalize_browser_action_payload(
            {
                "id": self._next_browser_action_id(),
                "action_type": body.action_type,
                "summary": body.summary,
                "target": body.target,
                "value": body.value,
                "url": body.url,
                "risk": body.risk,
                "scope": body.scope,
                "requires_confirmation": bool(body.requires_confirmation if body.requires_confirmation is not None else True),
                "metadata": body.metadata or {},
                "status": "pending",
                "created_at": created_at,
                "updated_at": created_at,
            }
        )
        self._browser_action_state["proposals"] = [proposal, *(self._browser_action_state["proposals"] or [])]
        return {"created": True, "proposal": proposal, **self._serialize_browser_action_state()}

    async def reject_browser_action(self, proposal_id: int):
        proposals = list(self._browser_action_state["proposals"] or [])
        for idx, proposal in enumerate(proposals):
            if int(proposal.get("id") or 0) != proposal_id:
                continue
            updated = {**proposal, "status": "rejected", "updated_at": self._now_iso()}
            proposals.pop(idx)
            self._browser_action_state["proposals"] = proposals
            self._browser_action_state["history"] = [updated, *(self._browser_action_state["history"] or [])][:50]
            return {"rejected": True, "proposal": updated, **self._serialize_browser_action_state()}
        raise HTTPException(404, "Browser action proposal not found")

    async def browser_bridge_start(self, headless: bool = False):
        try:
            import browser_bridge

            bridge = browser_bridge.get_bridge()
            if bridge.is_running:
                return {"status": "already_running", **bridge.status()}
            proxy = None
            async with self._db.get_db() as conn:
                settings = await self._db.get_all_settings(conn)
                proxy_url = settings.get("resource_fetch_proxy", "").strip()
                if proxy_url:
                    proxy = {"server": proxy_url}
            await bridge.start(headless=headless, proxy=proxy)
            return {"status": "started", **bridge.status()}
        except RuntimeError as exc:
            raise HTTPException(400, str(exc))
        except Exception as exc:
            raise HTTPException(500, f"Failed to start browser bridge: {exc}")

    async def browser_bridge_stop(self):
        try:
            import browser_bridge

            bridge = browser_bridge.get_bridge()
            await bridge.stop()
            return {"status": "stopped"}
        except Exception as exc:
            raise HTTPException(500, f"Failed to stop bridge: {exc}")

    async def browser_bridge_status(self):
        try:
            import browser_bridge

            bridge = browser_bridge.get_bridge()
            return bridge.status()
        except Exception:
            return {"running": False, "url": "", "title": ""}

    async def browser_bridge_execute(self, request: Request):
        try:
            import browser_bridge

            bridge = browser_bridge.get_bridge()
            if not bridge.is_running:
                raise HTTPException(400, "Browser bridge is not running. Start it first.")
            body = await request.json()

            proposal_id = int(body.get("proposal_id") or body.get("id") or 0)
            approved_action = self._find_approved_browser_action(proposal_id) if proposal_id else None
            if approved_action:
                execution_target = self._normalize_browser_action_payload(approved_action)
            else:
                execution_target = self._normalize_browser_action_payload(body)
                session_mode = str(self._browser_action_state["session"].get("mode") or "approval_required")
                if session_mode != "inspect_auto" or str(execution_target.get("action_type")) not in {"inspect", "screenshot", "wait"}:
                    raise HTTPException(
                        403,
                        "Direct browser execution is limited to read-only inspect actions in inspect_auto mode. "
                        "Approve a proposal first for browser mutations.",
                    )

            result = await bridge.execute_action(execution_target)
            if approved_action is not None:
                approved_action["execution_result"] = result
                approved_action["executed_at"] = self._now_iso()
                approved_action["updated_at"] = approved_action["executed_at"]
            return result
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"Execution error: {exc}")

    async def approve_and_execute_browser_action(self, proposal_id: int):
        proposals = list(self._browser_action_state["proposals"] or [])
        for idx, proposal in enumerate(proposals):
            if int(proposal.get("id") or 0) != proposal_id:
                continue
            updated = {**proposal, "status": "approved", "updated_at": self._now_iso()}
            proposals.pop(idx)
            self._browser_action_state["proposals"] = proposals
            self._browser_action_state["history"] = [updated, *(self._browser_action_state["history"] or [])][:50]

            execution_result = None
            try:
                import browser_bridge

                bridge = browser_bridge.get_bridge()
                if bridge.is_running:
                    execution_result = await bridge.execute_action(self._normalize_browser_action_payload(updated))
                    updated["execution_result"] = execution_result
                    updated["executed_at"] = self._now_iso()
            except Exception:
                pass

            return {"approved": True, "proposal": updated, "execution": execution_result, **self._serialize_browser_action_state()}
        raise HTTPException(404, "Browser action proposal not found")

    async def desktop_preview(self, w: int = 960, h: int = 540):
        width = max(320, min(int(w), 1600))
        height = max(180, min(int(h), 900))
        display = os.environ.get("DISPLAY", "")

        def placeholder_png(status: str, message: str) -> Response:
            image = Image.new("RGB", (width, height), color=(11, 15, 25))
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle(
                (24, 24, width - 24, height - 24),
                radius=24,
                outline=(51, 65, 85),
                width=2,
                fill=(15, 23, 42),
            )
            draw.text((48, 44), "Axon Desktop Preview Unavailable", fill=(245, 158, 11))
            draw.text((48, 76), f"Status: {status}", fill=(226, 232, 240))
            body = textwrap.fill(
                message.strip() or "Desktop preview is unavailable in the current environment.",
                width=56,
            )
            draw.multiline_text((48, 116), body, fill=(148, 163, 184), spacing=6)
            draw.text((48, height - 56), f"Display: {display or 'not set'}", fill=(100, 116, 139))
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            return Response(
                content=buf.getvalue(),
                media_type="image/png",
                headers={"Cache-Control": "no-store, max-age=0", "X-Axon-Preview-Status": status},
            )

        strategies: list[tuple[str, list[str]]] = []
        if display:
            if shutil.which("scrot"):
                strategies.append(("scrot", ["scrot", "-z", "-o", "--quality", "70", "/dev/stdout"]))
            if shutil.which("gnome-screenshot"):
                strategies.append(("gnome-screenshot", ["gnome-screenshot", "-f", "/dev/stdout"]))
            if shutil.which("import"):
                strategies.append(("import", ["import", "-silent", "-window", "root", "-resize", f"{width}x{height}", "png:-"]))
        if shutil.which("xvfb-run") and shutil.which("import"):
            strategies.append(("xvfb-import", ["xvfb-run", "--auto-servernum", "import", "-silent", "-window", "root", "-resize", f"{width}x{height}", "png:-"]))

        if not strategies:
            return placeholder_png(
                "no_display",
                "No display server or supported capture tool is available. Set DISPLAY or install a supported desktop capture backend.",
            )

        last_error = ""
        for name, cmd in strategies:
            env = os.environ.copy()
            try:
                result = subprocess.run(cmd, capture_output=True, timeout=8, check=False, env=env)
            except subprocess.TimeoutExpired:
                last_error = f"{name}: timed out"
                continue
            except Exception as exc:
                last_error = f"{name}: {exc}"
                continue

            if result.returncode != 0 or not result.stdout:
                stderr = (result.stderr or b"").decode("utf-8", errors="replace").strip()
                last_error = f"{name}: exit {result.returncode} — {stderr[:120]}"
                continue

            return Response(
                content=result.stdout,
                media_type="image/png",
                headers={"Cache-Control": "no-store, max-age=0"},
            )

        return placeholder_png("capture_failed", f"All desktop capture strategies failed. Last error: {last_error[:220]}")

    async def tunnel_status(self):
        config = self._connection_config()
        running = self._tunnel_running()
        url = self._read_tunnel_url(config) if running else ""
        return {
            "running": running,
            "url": url,
            "mode": config.get("tunnel_mode", "trycloudflare"),
            "named_tunnel_ready": config.get("named_tunnel_ready", False),
        }

    async def tunnel_start(self):
        config = self._connection_config()
        if self._tunnel_running():
            return {
                "running": True,
                "url": self._read_tunnel_url(config),
                "mode": config["tunnel_mode"],
                "msg": "Already running",
            }
        if not self._tunnel_bin.exists():
            raise HTTPException(400, "cloudflared binary not found")
        if config["tunnel_mode"] == "external":
            raise HTTPException(400, "External domain mode does not start a local tunnel.")
        if config.get("tunnel_mode") == "named" and not config.get("named_tunnel_ready"):
            raise HTTPException(400, "Named tunnel mode needs a saved Cloudflare tunnel token.")

        self._tunnel_log.write_text("")
        cmd = [str(self._tunnel_bin)]
        expected_url = ""
        if config["tunnel_mode"] == "named":
            cmd.extend(["--no-autoupdate", "tunnel", "run", "--token", config["cloudflare_tunnel_token"]])
            expected_url = config["public_base_url"]
        else:
            cmd.extend(["tunnel", "--url", f"http://localhost:{self._port}", "--no-autoupdate"])

        with open(str(self._tunnel_log), "a", encoding="utf-8") as log_handle:
            proc = subprocess.Popen(cmd, stdout=log_handle, stderr=subprocess.STDOUT)
        self._tunnel_pid.write_text(str(proc.pid))

        for _ in range(24):
            await asyncio.sleep(0.5)
            if config["tunnel_mode"] == "named":
                if self._tunnel_running():
                    return {"running": True, "url": expected_url, "mode": "named", "msg": "Named tunnel started"}
            else:
                url = self._read_tunnel_url(config)
                if url:
                    return {"running": True, "url": url, "mode": "trycloudflare", "msg": "Tunnel started"}

        return {
            "running": True,
            "url": expected_url if config["tunnel_mode"] == "named" else "",
            "mode": config["tunnel_mode"],
            "msg": "Started — URL not yet ready",
        }

    async def tunnel_stop(self):
        config = self._connection_config()
        if self._tunnel_pid.exists():
            try:
                pid = int(self._tunnel_pid.read_text().strip())
                subprocess.run(["kill", str(pid)], check=False)
            except Exception:
                pass
            self._tunnel_pid.unlink(missing_ok=True)
        self._tunnel_log.write_text("")
        return {"running": False, "url": "", "mode": config["tunnel_mode"], "msg": "Tunnel stopped"}


def build_connection_browser_router(
    *,
    db_module: Any,
    browser_action_state: dict[str, Any],
    connection_config: Callable[[], dict[str, Any]],
    probe_public_origin: Callable[[str, bool], dict[str, Any]],
    read_tunnel_url: Callable[[dict[str, Any] | None], str],
    tunnel_running: Callable[[], bool],
    now_iso: Callable[[], str],
    serialize_browser_action_state: Callable[[], dict[str, Any]],
    normalize_browser_session: Callable[..., dict[str, Any]],
    next_browser_action_id: Callable[[], int],
    normalize_browser_action_payload: Callable[[dict[str, Any]], dict[str, Any]],
    find_approved_browser_action: Callable[[int], Optional[dict[str, Any]]],
    port: int,
    tunnel_log: Path,
    tunnel_pid: Path,
    tunnel_bin: Path,
):
    handlers = ConnectionBrowserRouteHandlers(
        db_module=db_module,
        browser_action_state=browser_action_state,
        connection_config=connection_config,
        probe_public_origin=probe_public_origin,
        read_tunnel_url=read_tunnel_url,
        tunnel_running=tunnel_running,
        now_iso=now_iso,
        serialize_browser_action_state=serialize_browser_action_state,
        normalize_browser_session=normalize_browser_session,
        next_browser_action_id=next_browser_action_id,
        normalize_browser_action_payload=normalize_browser_action_payload,
        find_approved_browser_action=find_approved_browser_action,
        port=port,
        tunnel_log=tunnel_log,
        tunnel_pid=tunnel_pid,
        tunnel_bin=tunnel_bin,
    )
    router = APIRouter()
    router.add_api_route("/api/mobile/info", handlers.mobile_info, methods=["GET"])
    router.add_api_route("/api/browser/actions", handlers.browser_actions_status, methods=["GET"])
    router.add_api_route("/api/browser/session", handlers.update_browser_session, methods=["POST"])
    router.add_api_route("/api/browser/actions/propose", handlers.create_browser_action_proposal, methods=["POST"])
    router.add_api_route("/api/browser/actions/{proposal_id}/reject", handlers.reject_browser_action, methods=["POST"])
    router.add_api_route("/api/browser/bridge/start", handlers.browser_bridge_start, methods=["POST"])
    router.add_api_route("/api/browser/bridge/stop", handlers.browser_bridge_stop, methods=["POST"])
    router.add_api_route("/api/browser/bridge/status", handlers.browser_bridge_status, methods=["GET"])
    router.add_api_route("/api/browser/bridge/execute", handlers.browser_bridge_execute, methods=["POST"])
    router.add_api_route("/api/browser/actions/{proposal_id}/approve", handlers.approve_and_execute_browser_action, methods=["POST"])
    router.add_api_route("/api/desktop/preview", handlers.desktop_preview, methods=["GET"])
    router.add_api_route("/api/tunnel/status", handlers.tunnel_status, methods=["GET"])
    router.add_api_route("/api/tunnel/start", handlers.tunnel_start, methods=["POST"])
    router.add_api_route("/api/tunnel/stop", handlers.tunnel_stop, methods=["POST"])
    return router, handlers
