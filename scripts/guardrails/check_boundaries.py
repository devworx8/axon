#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.guardrails.common import BANNED_FILENAMES, CRITICAL_HOTSPOTS, load_budget_manifest


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    errors: list[str] = []

    agents = ROOT / "AGENTS.md"
    guardrails = ROOT / "docs/engineering/guardrails.md"
    waivers = ROOT / "docs/engineering/guardrail-waivers.json"
    roadmap = ROOT / "docs/architecture/refactor-roadmap.md"
    module_map = ROOT / "docs/architecture/module-map.md"
    hotspot_manifest_path = ROOT / "scripts/guardrails/hotspot_budgets.json"
    db_fascade = ROOT / "db.py"
    axon_data_init = ROOT / "axon_data/__init__.py"
    hotspot_change_script = ROOT / "scripts/guardrails/check_hotspot_changes.py"
    workflow = ROOT / ".github/workflows/guardrails.yml"

    require(agents.exists(), "Missing root AGENTS.md", errors)
    require(guardrails.exists(), "Missing docs/engineering/guardrails.md", errors)
    require(waivers.exists(), "Missing docs/engineering/guardrail-waivers.json", errors)
    require(roadmap.exists(), "Missing docs/architecture/refactor-roadmap.md", errors)
    require(module_map.exists(), "Missing docs/architecture/module-map.md", errors)
    require(axon_data_init.exists(), "Missing axon_data/__init__.py", errors)
    require(hotspot_manifest_path.exists(), "Missing scripts/guardrails/hotspot_budgets.json", errors)
    require(hotspot_change_script.exists(), "Missing scripts/guardrails/check_hotspot_changes.py", errors)
    require(workflow.exists(), "Missing .github/workflows/guardrails.yml", errors)

    if hotspot_manifest_path.exists():
        try:
            manifest = load_budget_manifest(ROOT)
            critical = set(manifest.get("critical_hotspots", {}).keys())
            for rel in CRITICAL_HOTSPOTS:
                require(rel in critical, f"Critical hotspot missing from manifest: {rel}", errors)
        except ValueError as exc:
            errors.append(str(exc))

    if db_fascade.exists():
        text = db_fascade.read_text(encoding="utf-8")
        require(
            "from axon_data import" in text,
            "db.py must re-export from axon_data",
            errors,
        )
        require("CREATE TABLE" not in text, "db.py must not contain schema DDL", errors)
        require("async def " not in text, "db.py must not contain repository functions", errors)

    tracked_files = (ROOT / ".git").exists()
    if tracked_files:
        import subprocess

        output = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
        for rel in output.splitlines():
            if Path(rel).name in BANNED_FILENAMES:
                errors.append(f"Tracked file uses banned dumping-ground name: {rel}")

    if errors:
        for error in errors:
            print(f"FAIL {error}")
        print("Boundary guardrails failed.")
        return 1

    print("Boundary guardrails passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
