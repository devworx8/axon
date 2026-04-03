from __future__ import annotations

import os
from pathlib import Path


def axon_tool_root() -> Path:
    return Path.home() / ".devbrain" / "tools"


def npm_prefix_dir() -> Path:
    return axon_tool_root() / "npm"


def npm_bin_dir() -> Path:
    return npm_prefix_dir() / "bin"


def pnpm_home_dir() -> Path:
    return axon_tool_root() / "pnpm"


def bun_install_dir() -> Path:
    return axon_tool_root() / "bun"


def bun_bin_dir() -> Path:
    return bun_install_dir() / "bin"


def pipx_home_dir() -> Path:
    return axon_tool_root() / "pipx"


def pipx_bin_dir() -> Path:
    return pipx_home_dir() / "bin"


def python_user_base_dir() -> Path:
    return axon_tool_root() / "python"


def python_bin_dir() -> Path:
    return python_user_base_dir() / "bin"


def cargo_home_dir() -> Path:
    return axon_tool_root() / "cargo"


def cargo_bin_dir() -> Path:
    return cargo_home_dir() / "bin"


def go_path_dir() -> Path:
    return axon_tool_root() / "go"


def go_bin_dir() -> Path:
    return go_path_dir() / "bin"


def gem_home_dir() -> Path:
    return axon_tool_root() / "gem"


def gem_bin_dir() -> Path:
    return gem_home_dir() / "bin"


def composer_home_dir() -> Path:
    return axon_tool_root() / "composer"


def composer_bin_dir() -> Path:
    return composer_home_dir() / "vendor" / "bin"


def axon_bin_dirs() -> list[Path]:
    return [
        npm_bin_dir(),
        pnpm_home_dir(),
        bun_bin_dir(),
        pipx_bin_dir(),
        python_bin_dir(),
        cargo_bin_dir(),
        go_bin_dir(),
        gem_bin_dir(),
        composer_bin_dir(),
    ]


def axon_binary_path(binary_name: str) -> Path:
    return npm_bin_dir() / str(binary_name or "").strip()


def _split_path(raw_path: str) -> list[str]:
    return [part for part in str(raw_path or "").split(os.pathsep) if part]


def _dedupe_paths(parts: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for part in parts:
        normalized = str(part or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def ensure_tool_dirs() -> None:
    for directory in (
        axon_tool_root(),
        npm_prefix_dir(),
        npm_bin_dir(),
        pnpm_home_dir(),
        bun_install_dir(),
        bun_bin_dir(),
        pipx_home_dir(),
        pipx_bin_dir(),
        python_user_base_dir(),
        python_bin_dir(),
        cargo_home_dir(),
        cargo_bin_dir(),
        go_path_dir(),
        go_bin_dir(),
        gem_home_dir(),
        gem_bin_dir(),
        composer_home_dir(),
        composer_bin_dir(),
    ):
        directory.mkdir(parents=True, exist_ok=True)


def build_tool_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    ensure_tool_dirs()
    env = dict(base_env or os.environ)
    env["AXON_TOOL_ROOT"] = str(axon_tool_root())
    env["NPM_CONFIG_PREFIX"] = str(npm_prefix_dir())
    env["npm_config_prefix"] = str(npm_prefix_dir())
    env["PNPM_HOME"] = str(pnpm_home_dir())
    env["BUN_INSTALL"] = str(bun_install_dir())
    env["PIPX_HOME"] = str(pipx_home_dir())
    env["PIPX_BIN_DIR"] = str(pipx_bin_dir())
    env["PYTHONUSERBASE"] = str(python_user_base_dir())
    env["PIP_USER"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["CARGO_HOME"] = str(cargo_home_dir())
    env["CARGO_INSTALL_ROOT"] = str(cargo_home_dir())
    env["GOPATH"] = str(go_path_dir())
    env["GOBIN"] = str(go_bin_dir())
    env["GEM_HOME"] = str(gem_home_dir())
    env["GEM_PATH"] = str(gem_home_dir())
    env["COMPOSER_HOME"] = str(composer_home_dir())
    env["PATH"] = os.pathsep.join(
        _dedupe_paths(
            [str(path) for path in axon_bin_dirs()] + _split_path(env.get("PATH", ""))
        )
    )
    return env


def npm_install_parts(npm_binary: str, package_name: str) -> list[str]:
    ensure_tool_dirs()
    return [
        str(npm_binary or "npm"),
        "install",
        "--global",
        "--prefix",
        str(npm_prefix_dir()),
        str(package_name or "").strip(),
    ]


def install_scope_label() -> str:
    return str(axon_tool_root())
