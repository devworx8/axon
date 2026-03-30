#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    errors: list[str] = []

    agents = ROOT / "AGENTS.md"
    guardrails = ROOT / "docs/engineering/guardrails.md"
    roadmap = ROOT / "docs/architecture/refactor-roadmap.md"
    module_map = ROOT / "docs/architecture/module-map.md"
    db_fascade = ROOT / "db.py"
    axon_data_init = ROOT / "axon_data/__init__.py"

    require(agents.exists(), "Missing root AGENTS.md", errors)
    require(guardrails.exists(), "Missing docs/engineering/guardrails.md", errors)
    require(roadmap.exists(), "Missing docs/architecture/refactor-roadmap.md", errors)
    require(module_map.exists(), "Missing docs/architecture/module-map.md", errors)
    require(axon_data_init.exists(), "Missing axon_data/__init__.py", errors)

    if db_fascade.exists():
        text = db_fascade.read_text(encoding="utf-8")
        require(
            "from axon_data import" in text,
            "db.py must re-export from axon_data",
            errors,
        )
        require("CREATE TABLE" not in text, "db.py must not contain schema DDL", errors)
        require("async def " not in text, "db.py must not contain repository functions", errors)

    if errors:
        for error in errors:
            print(f"FAIL {error}")
        print("Boundary guardrails failed.")
        return 1

    print("Boundary guardrails passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
