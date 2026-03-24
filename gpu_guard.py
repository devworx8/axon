"""
Axon GPU safety helpers.

These checks are intentionally lightweight and defensive: they try to detect
when the desktop session is being rendered by the same NVIDIA GPU that Ollama
would use for inference, then flag large local models as risky on low-VRAM
display-attached cards.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _run(cmd: list[str], *, env: dict[str, str] | None = None, timeout: int = 4) -> str:
    try:
        return subprocess.check_output(
            cmd,
            text=True,
            stderr=subprocess.DEVNULL,
            env=env,
            timeout=timeout,
        ).strip()
    except Exception:
        return ""


def _read_proc_environ(pid: str) -> dict[str, str]:
    try:
        entries = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    except Exception:
        return {}

    env: dict[str, str] = {}
    for entry in entries:
        if b"=" not in entry:
            continue
        key, value = entry.split(b"=", 1)
        env[key.decode(errors="ignore")] = value.decode(errors="ignore")
    return env


def _active_display_env() -> dict[str, str]:
    pid = _run(["pgrep", "-n", "gnome-shell"])
    if not pid:
        return {}

    raw = _read_proc_environ(pid)
    display = raw.get("DISPLAY", "")
    xauthority = raw.get("XAUTHORITY", "")
    if not display:
        return {}

    session_type = "wayland" if raw.get("WAYLAND_DISPLAY") else "x11"
    env = {"DISPLAY": display, "SESSION_TYPE": session_type}
    if xauthority:
        env["XAUTHORITY"] = xauthority
    return env


def detect_display_gpu_state() -> dict:
    profile = {
        "available": False,
        "gpu_name": "",
        "memory_total_mib": 0,
        "session_type": "",
        "display": "",
        "display_attached_nvidia": False,
        "display_provider": "",
        "connected_outputs": [],
        "risk_level": "normal",
        "warning": "",
    }

    nvidia = _run(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total",
            "--format=csv,noheader,nounits",
        ]
    )
    if not nvidia:
        return profile

    first = nvidia.splitlines()[0]
    parts = [part.strip() for part in first.split(",", 1)]
    total_mib = 0
    if len(parts) > 1:
        try:
            total_mib = int(float(parts[1]))
        except ValueError:
            total_mib = 0

    profile.update(
        {
            "available": True,
            "gpu_name": parts[0],
            "memory_total_mib": total_mib,
        }
    )

    display_env = _active_display_env()
    if display_env:
        profile["display"] = display_env.get("DISPLAY", "")
        profile["session_type"] = display_env.get("SESSION_TYPE", "")
        env = os.environ.copy()
        env.update(display_env)

        xrandr = _run(["xrandr", "--query"], env=env)
        outputs = []
        for line in xrandr.splitlines():
            if " connected" not in line or line.startswith("Screen "):
                continue
            outputs.append(line.split()[0])

        providers = _run(["xrandr", "--listproviders"], env=env)
        display_attached_nvidia = bool(outputs) and "NVIDIA" in providers.upper()
        profile.update(
            {
                "connected_outputs": outputs,
                "display_provider": "NVIDIA-0" if display_attached_nvidia else "",
                "display_attached_nvidia": display_attached_nvidia,
            }
        )

    outputs_count = len(profile["connected_outputs"])
    if profile["display_attached_nvidia"] and total_mib and total_mib <= 6144:
        profile["risk_level"] = "high"
        profile["warning"] = (
            f"{profile['gpu_name']} is driving {outputs_count} display(s) on "
            f"{profile['session_type'] or 'the desktop'} with {round(total_mib / 1024, 1)} GB VRAM. "
            "Large 7B Ollama loads can blank or reset the desktop."
        )
    elif profile["display_attached_nvidia"] and total_mib and total_mib <= 8192:
        profile["risk_level"] = "medium"
        profile["warning"] = (
            f"{profile['gpu_name']} is both the display GPU and the inference GPU. "
            "Use smaller local models or a lower context window for smoother sessions."
        )

    return profile


def ollama_model_safety(model_name: str, profile: dict | None = None) -> dict:
    profile = profile or detect_display_gpu_state()
    normalized = (model_name or "").lower().strip()
    safety = {
        "model": model_name,
        "risky": False,
        "severity": "none",
        "preferred_num_ctx": 4096,
        "fallbacks": [],
        "warning": "",
    }

    if not normalized:
        return safety

    if profile.get("risk_level") in {"high", "medium"} and ":7b" in normalized:
        safety["preferred_num_ctx"] = 2048

    if not profile.get("display_attached_nvidia"):
        return safety

    if normalized.startswith("deepseek-r1:7b"):
        safety.update(
            {
                "risky": True,
                "severity": "high",
                "preferred_num_ctx": 2048,
                "fallbacks": ["qwen2.5-coder:1.5b", "llama3.2:3b", "phi4-mini"],
                "warning": (
                    "deepseek-r1:7b is risky on a 6GB display-attached NVIDIA GPU. "
                    "Use a smaller model or a lower context window."
                ),
            }
        )
        return safety

    if normalized.startswith("qwen2.5-coder:7b") and profile.get("risk_level") == "high":
        safety.update(
            {
                "risky": True,
                "severity": "medium",
                "preferred_num_ctx": 2048,
                "fallbacks": ["qwen2.5-coder:1.5b", "llama3.2:3b"],
                "warning": (
                    "qwen2.5-coder:7b can be unstable when the same 6GB GPU is "
                    "also driving your displays."
                ),
            }
        )

    return safety


def _matches_model(candidate: str, family: str) -> bool:
    left = candidate.lower().strip()
    right = family.lower().strip()
    return left == right or left.startswith(f"{right}:") or left.startswith(right)


def pick_safe_model(
    requested_model: str,
    available_models: list[str],
    *,
    profile: dict | None = None,
    purpose: str = "chat",
) -> dict:
    profile = profile or detect_display_gpu_state()
    safety = ollama_model_safety(requested_model, profile)
    chosen = requested_model
    note = ""

    if safety["risky"]:
        for fallback in safety["fallbacks"]:
            candidate = next((name for name in available_models if _matches_model(name, fallback)), "")
            if candidate:
                chosen = candidate
                break

        if chosen and chosen != requested_model:
            note = (
                f"Axon switched from `{requested_model}` to `{chosen}` for {purpose} mode "
                "because the active NVIDIA display GPU has limited VRAM and the larger model "
                "can blank the desktop."
            )
        elif safety["warning"]:
            note = safety["warning"]

    return {
        "model": chosen,
        "changed": bool(chosen and chosen != requested_model),
        "note": note,
        "safety": safety,
        "profile": profile,
    }
