"""Runtime-level mobile actions for Axon Online."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

from axon_data import log_event


def queue_runtime_restart(*, devbrain_dir: str | Path, devbrain_log: str | Path, pidfile: str | Path) -> dict[str, Any]:
    base_dir = Path(devbrain_dir).expanduser().resolve()
    log_path = Path(devbrain_log).expanduser().resolve()
    pid_path = Path(pidfile).expanduser().resolve()
    server_py = base_dir / "server.py"
    python_bin = base_dir / ".venv" / "bin" / "python"
    python_cmd = str(python_bin if python_bin.exists() else "python3")

    command_preview = (
        f"sleep 1; "
        f"kill {os.getpid()} >/dev/null 2>&1 || true; "
        f"sleep 1; "
        f"cd {shlex.quote(str(base_dir))} && "
        f"setsid {shlex.quote(str(python_cmd))} {shlex.quote(str(server_py))} >> {shlex.quote(str(log_path))} 2>&1 < /dev/null & "
        f"echo $! > {shlex.quote(str(pid_path))}"
    )

    with open(os.devnull, "wb") as devnull:
        subprocess.Popen(
            ["/usr/bin/env", "bash", "-lc", command_preview],
            cwd=str(base_dir),
            start_new_session=True,
            stdout=devnull,
            stderr=devnull,
        )

    return {
        "accepted": True,
        "reconnect_after_ms": 4500,
        "command_preview": command_preview,
        "summary": "Axon runtime restart queued. Mobile and desktop clients should reconnect shortly.",
    }


async def log_runtime_restart_requested(db) -> None:
    await log_event(db, "maintenance", "Restart Axon requested from Axon Online mobile control")
