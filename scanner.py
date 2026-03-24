"""
Axon — Workspace Scanner
Walks known project directories, detects stacks, scores health.
"""

import asyncio
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
import json
import re

# ─── Stack detection signatures ─────────────────────────────────────────────

STACK_SIGNATURES = [
    # (file_to_check, stack_label)
    ("app.json",                "expo"),          # Expo / React Native
    ("expo.json",               "expo"),
    ("next.config.js",          "nextjs"),
    ("next.config.ts",          "nextjs"),
    ("next.config.mjs",         "nextjs"),
    ("vite.config.ts",          "vite"),
    ("vite.config.js",          "vite"),
    ("svelte.config.js",        "svelte"),
    ("nuxt.config.ts",          "nuxt"),
    ("angular.json",            "angular"),
    ("pyproject.toml",          "python"),
    ("setup.py",                "python"),
    ("requirements.txt",        "python"),
    ("Cargo.toml",              "rust"),
    ("go.mod",                  "go"),
    ("pom.xml",                 "java"),
    ("build.gradle",            "java"),
    ("Package.swift",           "swift"),
    ("package.json",            "node"),          # fallback if no framework detected
    ("Dockerfile",              "docker"),
    ("docker-compose.yml",      "docker"),
    ("docker-compose.yaml",     "docker"),
]

SKIP_DIRS = {
    "node_modules", ".git", ".next", "__pycache__", ".expo",
    "dist", "build", ".cache", "venv", ".venv", "env",
    ".turbo", "coverage", ".nyc_output",
}


def detect_stack(project_path: Path) -> str:
    """Return the primary tech stack label for a project directory."""
    for filename, label in STACK_SIGNATURES:
        if (project_path / filename).exists():
            # Differentiate React Native from plain Node
            if label == "node":
                pkg_json = project_path / "package.json"
                try:
                    data = json.loads(pkg_json.read_text())
                    deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                    if "react-native" in deps or "expo" in deps:
                        return "expo"
                    if "next" in deps:
                        return "nextjs"
                    if "react" in deps:
                        return "react"
                    if "vue" in deps:
                        return "vue"
                    if "@sveltejs/kit" in deps:
                        return "svelte"
                except Exception:
                    pass
            return label
    return "unknown"


def count_todos(project_path: Path, max_files: int = 2000) -> int:
    """Count TODO/FIXME/HACK comments across source files."""
    TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)
    count = 0
    checked = 0
    extensions = {".ts", ".tsx", ".js", ".jsx", ".py", ".go", ".rs", ".swift",
                  ".kt", ".java", ".vue", ".svelte", ".md"}
    try:
        for f in project_path.rglob("*"):
            if checked >= max_files:
                break
            if f.is_file() and f.suffix in extensions:
                # skip vendor/build dirs
                parts = set(f.parts)
                if parts & SKIP_DIRS:
                    continue
                try:
                    text = f.read_text(errors="ignore")
                    count += len(TODO_RE.findall(text))
                    checked += 1
                except Exception:
                    pass
    except Exception:
        pass
    return count


def get_git_info(project_path: Path) -> dict:
    """Return branch, last commit message, and age in days."""
    result = {"git_branch": None, "last_commit": None, "last_commit_age_days": None}
    if not (project_path / ".git").exists():
        return result
    try:
        branch = subprocess.check_output(
            ["git", "-C", str(project_path), "branch", "--show-current"],
            stderr=subprocess.DEVNULL, text=True
        ).strip()
        result["git_branch"] = branch or "detached"

        log = subprocess.check_output(
            ["git", "-C", str(project_path), "log", "-1",
             "--format=%s|||%aI"],   # subject|ISO date
            stderr=subprocess.DEVNULL, text=True
        ).strip()
        if log and "|||" in log:
            subject, iso_date = log.split("|||", 1)
            result["last_commit"] = subject[:120]
            commit_dt = datetime.fromisoformat(iso_date.strip())
            now = datetime.now(tz=timezone.utc)
            if commit_dt.tzinfo is None:
                commit_dt = commit_dt.replace(tzinfo=timezone.utc)
            result["last_commit_age_days"] = round((now - commit_dt).total_seconds() / 86400, 1)
    except Exception:
        pass
    return result


def score_health(git_age_days: Optional[float], todo_count: int,
                 has_git: bool, status: str) -> int:
    """
    Calculate a 0–100 health score for a project.
    Higher = healthier.
    """
    if status in ("archived", "done"):
        return 50  # neutral — intentionally inactive

    score = 100

    # Git staleness penalty
    if not has_git:
        score -= 10
    elif git_age_days is not None:
        if git_age_days > 30:
            score -= 30
        elif git_age_days > 14:
            score -= 15
        elif git_age_days > 7:
            score -= 5

    # TODO debt penalty
    if todo_count > 50:
        score -= 20
    elif todo_count > 20:
        score -= 10
    elif todo_count > 10:
        score -= 5

    return max(0, min(100, score))


def scan_project(project_path: Path) -> dict:
    """Synchronously scan one project directory and return a data dict."""
    path = project_path.resolve()
    name = path.name

    stack = detect_stack(path)
    git = get_git_info(path)
    todos = count_todos(path)
    has_git = git["git_branch"] is not None
    health = score_health(git["last_commit_age_days"], todos, has_git, "active")

    return {
        "name": name,
        "path": str(path),
        "stack": stack,
        "description": None,
        "git_branch": git["git_branch"],
        "last_commit": git["last_commit"],
        "last_commit_age_days": git["last_commit_age_days"],
        "todo_count": todos,
        "health": health,
    }


async def discover_and_scan(roots: list[str]) -> list[dict]:
    """
    Walk root directories, find project folders, scan each.
    Returns list of project dicts.
    """
    loop = asyncio.get_event_loop()
    projects = []
    visited = set()

    for root_str in roots:
        root = Path(root_str).expanduser().resolve()
        if not root.exists():
            continue

        # Check if root itself is a project
        if _looks_like_project(root) and str(root) not in visited:
            visited.add(str(root))
            result = await loop.run_in_executor(None, scan_project, root)
            projects.append(result)
            continue

        # Otherwise scan immediate children
        try:
            for child in sorted(root.iterdir()):
                if child.is_dir() and child.name not in SKIP_DIRS and not child.name.startswith("."):
                    if _looks_like_project(child) and str(child) not in visited:
                        visited.add(str(child))
                        result = await loop.run_in_executor(None, scan_project, child)
                        projects.append(result)
        except PermissionError:
            pass

    return projects


def _looks_like_project(path: Path) -> bool:
    """Heuristic: does this directory look like a software project?"""
    markers = [
        "package.json", "pyproject.toml", "requirements.txt", "Cargo.toml",
        "go.mod", "pom.xml", ".git", "app.json", "next.config.js",
        "next.config.ts", "next.config.mjs", "Makefile", "CMakeLists.txt",
    ]
    return any((path / m).exists() for m in markers)


def health_label(score: int) -> str:
    if score >= 80:
        return "🟢 Healthy"
    if score >= 60:
        return "🟡 OK"
    if score >= 40:
        return "🟠 Needs attention"
    return "🔴 Stale"


def format_age(days: Optional[float]) -> str:
    if days is None:
        return "no git"
    if days < 1:
        return "today"
    if days < 2:
        return "yesterday"
    if days < 7:
        return f"{int(days)}d ago"
    if days < 30:
        return f"{int(days // 7)}w ago"
    return f"{int(days // 30)}mo ago"
