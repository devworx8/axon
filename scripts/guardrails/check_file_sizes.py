#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]

EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "models",
    "resources",
}

LEGACY_LIMITS = {
    "server.py": 6027,
    "brain.py": 2875,
    "document_engine.py": 607,
    "ui/index.html": 6089,
    "ui/manual.html": 1046,
    "ui/js/dashboard.js": 2287,
    "ui/js/chat.js": 999,
    "ui/js/voice.js": 913,
}

DEFAULT_LIMITS = {
    ".py": 500,
    ".js": 500,
    ".html": 400,
    ".md": 700,
}

ADVISORY_LIMITS = {
    ".py": 350,
    ".js": 350,
    ".html": 250,
    ".md": 400,
}


def should_skip(path: Path) -> bool:
    parts = set(path.parts)
    return bool(parts & EXCLUDED_PARTS)


def iter_tracked_source_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if should_skip(path.relative_to(ROOT)):
            continue
        if path.suffix.lower() not in DEFAULT_LIMITS:
            continue
        files.append(path)
    return sorted(files)


def line_count(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def main() -> int:
    failed = False
    advisory_hits: list[str] = []
    for path in iter_tracked_source_files():
        rel = path.relative_to(ROOT).as_posix()
        lines = line_count(path)
        hard_limit = LEGACY_LIMITS.get(rel, DEFAULT_LIMITS[path.suffix.lower()])
        advisory_limit = ADVISORY_LIMITS[path.suffix.lower()]
        if lines > hard_limit:
            print(f"FAIL {rel}: {lines} lines exceeds hard limit {hard_limit}")
            failed = True
        elif rel not in LEGACY_LIMITS and lines > advisory_limit:
            advisory_hits.append(
                f"WARN {rel}: {lines} lines exceeds advisory limit {advisory_limit}"
            )

    for warning in advisory_hits:
        print(warning)

    if failed:
        print("File-size guardrails failed.")
        return 1

    print("File-size guardrails passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
