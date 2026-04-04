"""Maintenance, Ollama, backup, health, and PPTX routes extracted from server.py."""
from __future__ import annotations

import json
import os
import platform
import shlex
import subprocess
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse


class OllamaRuntimeModeBody(BaseModel):
    mode: str


class OllamaPullRequest(BaseModel):
    model: str


class SystemActionExecute(BaseModel):
    action: str
    confirmation_text: str = ""
    acknowledge: bool = False


class PptxFromPromptRequest(BaseModel):
    prompt: str
    context: str = ""
    theme: str = "dark"
    output_path: str = ""


class PptxFromDataRequest(BaseModel):
    deck: dict
    output_path: str = ""


RECOMMENDED_MODELS = [
    {"name": "qwen2.5-coder:7b", "desc": "Best coding model — 7B, 4.7GB", "category": "code", "size_gb": 4.7},
    {"name": "qwen2.5-coder:1.5b", "desc": "Ultra-fast code suggestions", "category": "code", "size_gb": 1.0},
    {"name": "llama3.2:3b", "desc": "Fast general-purpose chat", "category": "general", "size_gb": 2.0},
    {"name": "deepseek-r1:7b", "desc": "Strong reasoning + code (7B)", "category": "reason", "size_gb": 4.7},
    {"name": "nomic-embed-text", "desc": "Embeddings for semantic search", "category": "embed", "size_gb": 0.3},
    {"name": "phi4-mini", "desc": "Microsoft Phi-4 Mini — 3.8B", "category": "general", "size_gb": 2.5},
]


class MaintenanceRouteHandlers:
    def __init__(
        self,
        *,
        db_module: Any,
        brain_module: Any,
        gpu_guard_module: Any,
        managed_connection: Callable[..., Any],
        sqlite_row_factory: Any,
        now_iso: Callable[[], str],
        load_chat_history_rows: Callable[..., Awaitable[list[Any]]],
        devbrain_dir: Path,
        devbrain_log: Path,
        pidfile: Path,
        ollama_sh: Path,
        port: int,
        system_action_confirmations: dict[str, str],
    ) -> None:
        self._db = db_module
        self._brain = brain_module
        self._gpu_guard = gpu_guard_module
        self._managed_connection = managed_connection
        self._sqlite_row_factory = sqlite_row_factory
        self._now_iso = now_iso
        self._load_chat_history_rows = load_chat_history_rows
        self._devbrain_dir = devbrain_dir
        self._devbrain_log = devbrain_log
        self._pidfile = pidfile
        self._ollama_sh = ollama_sh
        self._port = port
        self._system_action_confirmations = dict(system_action_confirmations)

    def command_preview(self, cmd: list[str]) -> str:
        return " ".join(shlex.quote(part) for part in cmd)

    def run_capture(self, cmd: list[str], timeout: int = 20) -> dict[str, Any]:
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            stdout = (proc.stdout or "").strip()
            stderr = (proc.stderr or "").strip()
            output = "\n".join(part for part in (stdout, stderr) if part).strip()
            return {
                "ok": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "output": output,
            }
        except FileNotFoundError as exc:
            return {
                "ok": False,
                "returncode": 127,
                "stdout": "",
                "stderr": str(exc),
                "output": str(exc),
            }
        except subprocess.TimeoutExpired as exc:
            stdout = (exc.stdout or "").strip() if isinstance(exc.stdout, str) else ""
            stderr = (exc.stderr or "").strip() if isinstance(exc.stderr, str) else ""
            output = "\n".join(part for part in (stdout, stderr) if part).strip() or "Command timed out"
            return {
                "ok": False,
                "returncode": 124,
                "stdout": stdout,
                "stderr": stderr,
                "output": output,
            }

    def read_pidfile(self) -> Optional[int]:
        try:
            value = self._pidfile.read_text(encoding="utf-8").strip()
            return int(value) if value.isdigit() else None
        except Exception:
            return None

    def ollama_service_status(self) -> dict[str, Any]:
        if not self._ollama_sh.exists():
            return {
                "running": False,
                "mode": "unavailable",
                "detail": "Ollama launcher not found",
                "command_preview": "",
                "output": "",
            }

        result = self.run_capture([str(self._ollama_sh), "status"], timeout=15)
        output = result["output"]
        lower = output.lower()
        mode = "unknown"
        running = False
        detail = output or "No status output"

        if lower.startswith("cpu-safe: running"):
            mode = "cpu_safe"
            running = True
        elif lower.startswith("systemd: active"):
            mode = "systemd"
            running = True
        elif lower.startswith("manual: running"):
            mode = "manual"
            running = True
        elif lower.startswith("running (external process)"):
            mode = "external"
            running = True
        elif "stopped" in lower:
            mode = "stopped"
            running = False
        elif result["ok"] and output:
            mode = "running"
            running = True

        return {
            "running": running,
            "mode": mode,
            "detail": detail,
            "command_preview": self.command_preview([str(self._ollama_sh), "restart"]),
            "output": output,
        }

    def stored_ollama_runtime_mode(self, settings: dict[str, Any]) -> str:
        explicit = (settings.get("ollama_runtime_mode") or "").strip().lower()
        if explicit in {"cpu_safe", "gpu_default"}:
            return explicit
        url = (settings.get("ollama_url") or "").strip().rstrip("/")
        return "cpu_safe" if url.endswith(":11435") else "gpu_default"

    def reboot_plan(self, os_name: str) -> dict[str, Any]:
        if os_name == "Linux":
            return {
                "supported": True,
                "execution_mode": "manual",
                "command_preview": "sudo systemctl reboot",
                "note": "Requires root privileges and immediately disconnects every client.",
            }
        if os_name == "Darwin":
            return {
                "supported": True,
                "execution_mode": "manual",
                "command_preview": "sudo shutdown -r now",
                "note": "Requires an administrator password and immediately disconnects every client.",
            }
        if os_name == "Windows":
            return {
                "supported": True,
                "execution_mode": "manual",
                "command_preview": "shutdown /r /t 0",
                "note": "Requires an elevated shell on most Windows setups and immediately disconnects every client.",
            }
        return {
            "supported": False,
            "execution_mode": "unsupported",
            "command_preview": "",
            "note": f"System reboot is not configured for {os_name}.",
        }

    def restart_devbrain_plan(self, os_name: str) -> dict[str, Any]:
        server_py = self._devbrain_dir / "server.py"
        if server_py.exists():
            preview = (
                f"kill {os.getpid()} && "
                f"cd {shlex.quote(str(self._devbrain_dir))} && "
                f"setsid python3 {shlex.quote(str(server_py))} >> {shlex.quote(str(self._devbrain_log))} 2>&1 < /dev/null &"
            )
            return {
                "supported": True,
                "execution_mode": "automatic",
                "command_preview": preview,
                "note": "Safe user-level restart. Existing Axon tabs reconnect after a short interruption.",
            }

        preview = "python %USERPROFILE%\\.devbrain\\server.py" if os_name == "Windows" else "python3 ~/.devbrain/server.py"
        return {
            "supported": False,
            "execution_mode": "manual",
            "command_preview": preview,
            "note": "Axon launcher files were not found on this machine.",
        }

    def restart_ollama_plan(self, os_name: str, service: dict[str, Any]) -> dict[str, Any]:
        if os_name == "Linux":
            if service.get("mode") == "systemd":
                return {
                    "supported": True,
                    "execution_mode": "manual",
                    "command_preview": "sudo systemctl restart ollama",
                    "note": "Ollama is managed by systemd, so Axon prepares the exact command but does not run sudo automatically.",
                }
            if self._ollama_sh.exists():
                return {
                    "supported": True,
                    "execution_mode": "automatic",
                    "command_preview": self.command_preview([str(self._ollama_sh), "restart"]),
                    "note": "Restarts only the model runtime. Active chats and agents may fail while Ollama comes back.",
                }
            return {
                "supported": False,
                "execution_mode": "unsupported",
                "command_preview": "ollama serve",
                "note": "Ollama launcher script is missing.",
            }
        if os_name == "Darwin":
            return {
                "supported": True,
                "execution_mode": "manual",
                "command_preview": "pkill -f 'ollama serve' && ollama serve",
                "note": "macOS restart is manual because launch methods vary between installations.",
            }
        if os_name == "Windows":
            return {
                "supported": True,
                "execution_mode": "manual",
                "command_preview": "taskkill /IM ollama.exe /F && ollama serve",
                "note": "Windows restart is manual because service setup varies between installations.",
            }
        return {
            "supported": False,
            "execution_mode": "unsupported",
            "command_preview": "",
            "note": f"Ollama restart is not configured for {os_name}.",
        }

    def system_action_specs(self, os_name: str, ollama_service: dict[str, Any]) -> list[dict[str, Any]]:
        restart_devbrain = self.restart_devbrain_plan(os_name)
        restart_ollama = self.restart_ollama_plan(os_name, ollama_service)
        reboot_machine = self.reboot_plan(os_name)
        return [
            {
                "id": "restart_devbrain",
                "title": "Restart Axon",
                "description": "Restart the local Axon server without touching the rest of the machine.",
                "impact": "Open Axon tabs disconnect briefly, then reconnect when the server is back.",
                "level": "warning",
                "supported": restart_devbrain["supported"],
                "execution_mode": restart_devbrain["execution_mode"],
                "confirmation_text": self._system_action_confirmations["restart_devbrain"],
                "command_preview": restart_devbrain["command_preview"],
                "note": restart_devbrain["note"],
            },
            {
                "id": "restart_ollama",
                "title": "Restart Ollama",
                "description": "Restart the local Ollama runtime separately from Axon.",
                "impact": "Current model pulls, chat streams, and agent runs may fail until Ollama is healthy again.",
                "level": "warning",
                "supported": restart_ollama["supported"],
                "execution_mode": restart_ollama["execution_mode"],
                "confirmation_text": self._system_action_confirmations["restart_ollama"],
                "command_preview": restart_ollama["command_preview"],
                "note": restart_ollama["note"],
            },
            {
                "id": "reboot_machine",
                "title": "Reboot Machine",
                "description": "Prepare a full OS reboot with the exact command for this operating system.",
                "impact": "Every app, model, shell, and remote/mobile client will disconnect immediately.",
                "level": "danger",
                "supported": reboot_machine["supported"],
                "execution_mode": reboot_machine["execution_mode"],
                "confirmation_text": self._system_action_confirmations["reboot_machine"],
                "command_preview": reboot_machine["command_preview"],
                "note": reboot_machine["note"],
            },
        ]

    def queue_devbrain_restart(self) -> None:
        cmd = (
            f"sleep 1; "
            f"kill {os.getpid()} >/dev/null 2>&1 || true; "
            f"sleep 1; "
            f"cd {shlex.quote(str(self._devbrain_dir))} && "
            f"setsid python3 {shlex.quote(str(self._devbrain_dir / 'server.py'))} >> {shlex.quote(str(self._devbrain_log))} 2>&1 < /dev/null & "
            f"echo $! > {shlex.quote(str(self._pidfile))}"
        )
        with open(os.devnull, "wb") as devnull:
            subprocess.Popen(
                ["/usr/bin/env", "bash", "-lc", cmd],
                cwd=str(self._devbrain_dir),
                start_new_session=True,
                stdout=devnull,
                stderr=devnull,
            )

    async def ollama_status(self):
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
        url = settings.get("ollama_url", "")
        status = await self._brain.ollama_status(ollama_url=url)
        service = self.ollama_service_status()
        status["runtime_mode"] = self.stored_ollama_runtime_mode(settings)
        status["service_mode"] = service.get("mode", "")
        status["service_detail"] = service.get("detail", "")
        return status

    async def switch_ollama_runtime_mode(self, body: OllamaRuntimeModeBody):
        requested = (body.mode or "").strip().lower()
        if requested not in {"cpu_safe", "gpu_default"}:
            raise HTTPException(400, "Unknown Ollama runtime mode.")
        if not self._ollama_sh.exists():
            raise HTTPException(500, "Ollama launcher not found.")

        launcher_command = "cpu" if requested == "cpu_safe" else "start"
        result = self.run_capture([str(self._ollama_sh), launcher_command], timeout=25)
        if not result["ok"]:
            raise HTTPException(500, result["output"] or "Failed to switch Ollama runtime mode.")

        ollama_url = "http://127.0.0.1:11435" if requested == "cpu_safe" else self._brain.OLLAMA_BASE_URL
        status = await self._brain.ollama_status(ollama_url=ollama_url)
        async with self._db.get_db() as conn:
            await self._db.set_setting(conn, "ollama_runtime_mode", requested)
            await self._db.set_setting(conn, "ollama_url", ollama_url)
        return {
            "ok": True,
            "runtime_mode": requested,
            "ollama_url": ollama_url,
            "status": status,
            "launcher_output": result["output"],
        }

    async def ollama_models(self):
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
        base_url = (settings.get("ollama_url", "") or self._brain.OLLAMA_BASE_URL).rstrip("/")
        try:
            import httpx

            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{base_url}/api/tags")
                resp.raise_for_status()
                data = resp.json()
            models = [
                {
                    "name": model["name"],
                    "size_gb": round(model.get("size", 0) / 1e9, 1),
                    "modified": model.get("modified_at", ""),
                    "family": model.get("details", {}).get("family", ""),
                    "parameter_size": model.get("details", {}).get("parameter_size", ""),
                    "quantization": model.get("details", {}).get("quantization_level", ""),
                }
                for model in data.get("models", [])
            ]
            return {"models": models, "running": True}
        except Exception as exc:
            return {"models": [], "running": False, "error": str(exc)}

    async def ollama_recommended(self):
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
        base_url = (settings.get("ollama_url", "") or self._brain.OLLAMA_BASE_URL).rstrip("/")
        try:
            import httpx

            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{base_url}/api/tags")
                resp.raise_for_status()
                installed = {model["name"] for model in resp.json().get("models", [])}
        except Exception:
            installed = set()

        gpu_profile = self._gpu_guard.detect_display_gpu_state()
        result = []
        for model in RECOMMENDED_MODELS:
            safety = self._gpu_guard.ollama_model_safety(model["name"], gpu_profile)
            result.append(
                {
                    **model,
                    "installed": model["name"] in installed,
                    "risky": safety.get("risky", False),
                    "risk_severity": safety.get("severity", "none"),
                    "warning": safety.get("warning", ""),
                }
            )
        return {"models": result, "gpu_guard": gpu_profile}

    async def ollama_pull(self, body: OllamaPullRequest, request: Request):
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
        base_url = (settings.get("ollama_url", "") or self._brain.OLLAMA_BASE_URL).rstrip("/")

        async def generate():
            try:
                import httpx

                async with httpx.AsyncClient(timeout=3600) as client:
                    async with client.stream("POST", f"{base_url}/api/pull", json={"name": body.model}) as resp:
                        resp.raise_for_status()
                        async for line in resp.aiter_lines():
                            if not line:
                                continue
                            if await request.is_disconnected():
                                return
                            try:
                                yield {"data": json.dumps(json.loads(line))}
                            except json.JSONDecodeError:
                                continue
            except Exception as exc:
                yield {"data": json.dumps({"error": str(exc), "status": "error"})}

        return EventSourceResponse(generate())

    async def ollama_delete_model(self, model_name: str):
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
        base_url = (settings.get("ollama_url", "") or self._brain.OLLAMA_BASE_URL).rstrip("/")
        try:
            import httpx

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.request("DELETE", f"{base_url}/api/delete", json={"name": model_name})
                resp.raise_for_status()
            return {"deleted": model_name}
        except Exception as exc:
            raise HTTPException(500, str(exc))

    async def system_actions(self):
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
        os_name = platform.system() or "Unknown"
        ollama_service = self.ollama_service_status()
        actions = self.system_action_specs(os_name, ollama_service)
        pid = self.read_pidfile() or os.getpid()
        return {
            "host": {
                "os": os_name,
                "release": platform.release(),
                "hostname": platform.node() or "localhost",
                "python": platform.python_version(),
            },
            "services": {
                "axon": {"running": True, "pid": pid, "port": self._port, "url": f"http://localhost:{self._port}", "mode": "local-server"},
                "devbrain": {"running": True, "pid": pid, "port": self._port, "url": f"http://localhost:{self._port}", "mode": "local-server"},
                "ollama": {**ollama_service, "url": (settings.get("ollama_url", "") or self._brain.OLLAMA_BASE_URL)},
            },
            "actions": actions,
        }

    async def system_action_execute(self, body: SystemActionExecute, background_tasks: BackgroundTasks):
        action_id = body.action.strip()
        if action_id not in self._system_action_confirmations:
            raise HTTPException(404, "Unknown system action")
        if not body.acknowledge:
            raise HTTPException(400, "Please acknowledge the impact before continuing.")
        expected = self._system_action_confirmations[action_id]
        if body.confirmation_text.strip().upper() != expected:
            raise HTTPException(400, f"Type '{expected}' to confirm this action.")

        os_name = platform.system() or "Unknown"
        ollama_service = self.ollama_service_status()
        actions = {item["id"]: item for item in self.system_action_specs(os_name, ollama_service)}
        action = actions[action_id]
        if not action.get("supported"):
            raise HTTPException(400, action.get("note") or "This action is not supported on this machine.")

        if action_id == "restart_devbrain":
            background_tasks.add_task(self.queue_devbrain_restart)
            async with self._db.get_db() as conn:
                await self._db.log_event(conn, "maintenance", "Restart Axon requested")
            return {
                "status": "accepted",
                "action": action_id,
                "message": "Axon restart queued. The page should reconnect in a moment.",
                "command_preview": action["command_preview"],
                "execution_mode": action["execution_mode"],
                "reconnect_after_ms": 4500,
            }

        if action_id == "restart_ollama":
            if action["execution_mode"] != "automatic":
                async with self._db.get_db() as conn:
                    await self._db.log_event(conn, "maintenance", "Restart Ollama manual command prepared")
                return {
                    "status": "manual_required",
                    "action": action_id,
                    "message": action["note"],
                    "command_preview": action["command_preview"],
                    "execution_mode": action["execution_mode"],
                }

            result = self.run_capture([str(self._ollama_sh), "restart"], timeout=90)
            async with self._db.get_db() as conn:
                await self._db.log_event(conn, "maintenance", "Restart Ollama requested")
            if not result["ok"]:
                raise HTTPException(500, result["output"] or "Failed to restart Ollama")
            return {
                "status": "completed",
                "action": action_id,
                "message": result["output"] or "Ollama restart requested.",
                "command_preview": action["command_preview"],
                "execution_mode": action["execution_mode"],
                "output": result["output"],
            }

        if action_id == "reboot_machine":
            async with self._db.get_db() as conn:
                await self._db.log_event(conn, "maintenance", "Reboot command prepared")
            return {
                "status": "manual_required",
                "action": action_id,
                "message": action["note"],
                "command_preview": action["command_preview"],
                "execution_mode": action["execution_mode"],
            }

        raise HTTPException(400, "Unsupported system action")

    async def backup_export(self):
        async with self._db.get_db() as conn:
            projects = [dict(row) for row in await self._db.get_projects(conn)]
            tasks = [dict(row) for row in await self._db.get_tasks(conn, status=None)]
            prompts = [dict(row) for row in await self._db.get_prompts(conn)]
            memory = [dict(row) for row in await self._db.list_memory_items(conn, limit=5000)]
            resources = [dict(row) for row in await self._db.list_resources(conn, limit=5000)]
            settings = await self._db.get_all_settings(conn)
            chat = [dict(row) for row in await self._load_chat_history_rows(conn, limit=10000, degrade_to_empty=True)]
        for key in ("auth_pin_hash", "vault_key_hash"):
            settings.pop(key, None)
        return JSONResponse(
            {
                "version": 1,
                "exported_at": self._now_iso(),
                "projects": projects,
                "tasks": tasks,
                "prompts": prompts,
                "memory_items": memory,
                "resources_metadata": resources,
                "settings": settings,
                "chat_history": chat,
            }
        )

    async def backup_import(self, request: Request):
        try:
            data = await request.json()
        except Exception:
            raise HTTPException(400, "Invalid JSON body")
        if not isinstance(data, dict) or "version" not in data:
            raise HTTPException(400, "Missing version field — not a valid Axon backup")

        counts: dict[str, int] = {}
        async with self._db.get_db() as conn:
            for task in data.get("tasks", []):
                try:
                    await conn.execute(
                        """INSERT OR IGNORE INTO tasks
                           (project_id, title, detail, status, priority, due_date)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            task.get("project_id", 1),
                            task["title"],
                            task.get("detail", ""),
                            task.get("status", "open"),
                            task.get("priority", "medium"),
                            task.get("due_date"),
                        ),
                    )
                except Exception:
                    continue
            counts["tasks"] = len(data.get("tasks", []))

            for prompt in data.get("prompts", []):
                try:
                    await conn.execute(
                        """INSERT OR IGNORE INTO prompts (project_id, label, body)
                           VALUES (?, ?, ?)""",
                        (prompt.get("project_id", 1), prompt["label"], prompt.get("body", "")),
                    )
                except Exception:
                    continue
            counts["prompts"] = len(data.get("prompts", []))

            for item in data.get("memory_items", []):
                try:
                    await conn.execute(
                        """INSERT OR IGNORE INTO memory_items
                           (workspace_id, memory_key, summary, layer, source, metadata_json)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            item.get("workspace_id", 1),
                            item.get("memory_key", ""),
                            item.get("summary", ""),
                            item.get("layer", "general"),
                            item.get("source", "import"),
                            item.get("metadata_json", "{}"),
                        ),
                    )
                except Exception:
                    continue
            counts["memory_items"] = len(data.get("memory_items", []))

            skip_keys = {"auth_pin_hash", "vault_key_hash"}
            for key, value in data.get("settings", {}).items():
                if key not in skip_keys:
                    await self._db.set_setting(conn, key, value)
            counts["settings"] = len(data.get("settings", {}))
            await conn.commit()

        return {"status": "imported", "counts": counts}

    async def health(self):
        return {"status": "ok", "port": self._port}

    async def generate_pptx_ai(self, body: PptxFromPromptRequest):
        try:
            from pptx_engine import build_deck, deck_from_dict, prompt_to_deck_json
        except ImportError as exc:
            return JSONResponse({"error": f"pptx_engine not available: {exc}"}, status_code=500)

        try:
            import httpx

            def model_fn(system: str, user: str) -> str:
                settings: dict[str, Any] = {}
                try:
                    with self._managed_connection(self._db.DB_PATH, row_factory=self._sqlite_row_factory) as conn:
                        rows = conn.execute("SELECT key, value FROM settings").fetchall()
                        settings = {row["key"]: row["value"] for row in rows}
                except Exception:
                    settings = {}

                ollama_model = settings.get("code_model") or settings.get("ollama_model") or "qwen2.5-coder:1.5b"
                payload = {
                    "model": ollama_model,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    "stream": False,
                    "options": {"temperature": 0.3},
                }
                resp = httpx.post("http://localhost:11434/api/chat", json=payload, timeout=120)
                resp.raise_for_status()
                return resp.json()["message"]["content"]

            deck_json = prompt_to_deck_json(body.prompt, body.context, model_fn)
            if body.output_path:
                deck_json["output_path"] = body.output_path
            if body.theme:
                deck_json["theme"] = body.theme
            spec = deck_from_dict(deck_json)
            out_path = build_deck(spec)
            return JSONResponse(
                {
                    "ok": True,
                    "path": str(out_path),
                    "filename": out_path.name,
                    "slides": len(spec.slides),
                    "title": spec.title,
                }
            )
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    async def generate_pptx_from_data(self, body: PptxFromDataRequest):
        try:
            from pptx_engine import build_deck, deck_from_dict
        except ImportError as exc:
            return JSONResponse({"error": f"pptx_engine not available: {exc}"}, status_code=500)

        try:
            data = dict(body.deck)
            if body.output_path:
                data["output_path"] = body.output_path
            spec = deck_from_dict(data)
            out_path = build_deck(spec)
            return JSONResponse(
                {
                    "ok": True,
                    "path": str(out_path),
                    "filename": out_path.name,
                    "slides": len(spec.slides),
                    "title": spec.title,
                }
            )
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    async def download_pptx(self, path: str):
        import urllib.parse

        file_path = Path(urllib.parse.unquote(path))
        if not file_path.exists() or file_path.suffix != ".pptx":
            raise HTTPException(404, "File not found")
        home = Path.home()
        try:
            file_path.relative_to(home)
        except ValueError:
            raise HTTPException(403, "Access denied")
        return FileResponse(
            str(file_path),
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            filename=file_path.name,
        )


def build_maintenance_router(
    *,
    db_module: Any,
    brain_module: Any,
    gpu_guard_module: Any,
    managed_connection: Callable[..., Any],
    sqlite_row_factory: Any,
    now_iso: Callable[[], str],
    load_chat_history_rows: Callable[..., Awaitable[list[Any]]],
    devbrain_dir: Path,
    devbrain_log: Path,
    pidfile: Path,
    ollama_sh: Path,
    port: int,
    system_action_confirmations: dict[str, str],
):
    handlers = MaintenanceRouteHandlers(
        db_module=db_module,
        brain_module=brain_module,
        gpu_guard_module=gpu_guard_module,
        managed_connection=managed_connection,
        sqlite_row_factory=sqlite_row_factory,
        now_iso=now_iso,
        load_chat_history_rows=load_chat_history_rows,
        devbrain_dir=devbrain_dir,
        devbrain_log=devbrain_log,
        pidfile=pidfile,
        ollama_sh=ollama_sh,
        port=port,
        system_action_confirmations=system_action_confirmations,
    )
    router = APIRouter()
    router.add_api_route("/api/ollama/status", handlers.ollama_status, methods=["GET"])
    router.add_api_route("/api/ollama/runtime-mode", handlers.switch_ollama_runtime_mode, methods=["POST"])
    router.add_api_route("/api/ollama/models", handlers.ollama_models, methods=["GET"])
    router.add_api_route("/api/ollama/recommended", handlers.ollama_recommended, methods=["GET"])
    router.add_api_route("/api/ollama/pull", handlers.ollama_pull, methods=["POST"])
    router.add_api_route("/api/ollama/models/{model_name:path}", handlers.ollama_delete_model, methods=["DELETE"])
    router.add_api_route("/api/system/actions", handlers.system_actions, methods=["GET"])
    router.add_api_route("/api/system/actions/execute", handlers.system_action_execute, methods=["POST"])
    router.add_api_route("/api/backup/export", handlers.backup_export, methods=["GET"])
    router.add_api_route("/api/backup/import", handlers.backup_import, methods=["POST"])
    router.add_api_route("/api/health", handlers.health, methods=["GET"])
    router.add_api_route("/api/generate/pptx/ai", handlers.generate_pptx_ai, methods=["POST"])
    router.add_api_route("/api/generate/pptx", handlers.generate_pptx_from_data, methods=["POST"])
    router.add_api_route("/api/generate/pptx/download", handlers.download_pptx, methods=["GET"])
    return router, handlers
