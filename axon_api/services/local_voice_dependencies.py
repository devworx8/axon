"""Local voice dependency discovery helpers extracted from server.py."""
from __future__ import annotations


def python_module_available(name: str, *, importlib_util_module) -> bool:
    try:
        return importlib_util_module.find_spec(name) is not None
    except Exception:
        return False


def resolve_ffmpeg_path(
    *,
    shutil_module,
    python_module_available_fn,
    pathlib_path_cls,
) -> str:
    system_path = shutil_module.which("ffmpeg")
    if system_path:
        return system_path
    if python_module_available_fn("imageio_ffmpeg"):
        try:
            import imageio_ffmpeg

            bundled_path = str(imageio_ffmpeg.get_ffmpeg_exe() or "").strip()
            if bundled_path and pathlib_path_cls(bundled_path).exists():
                return bundled_path
        except Exception:
            return ""
    return ""


def piper_python_available(*, python_module_available_fn) -> bool:
    return python_module_available_fn("piper.voice")
