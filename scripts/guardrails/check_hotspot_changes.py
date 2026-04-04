#!/usr/bin/env python3
from __future__ import annotations

import sys


ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.guardrails.common import (
    active_waiver_files,
    changed_files,
    detect_compare_range,
    evaluate_critical_hotspot_change,
    line_count,
    load_budget_manifest,
    load_waiver_register,
)


def main() -> int:
    try:
        manifest = load_budget_manifest()
        register = load_waiver_register()
    except ValueError as exc:
        print(f"FAIL {exc}")
        print("Critical hotspot change guardrails failed.")
        return 1
    critical = manifest.get("critical_hotspots", {})
    active_waivers, waiver_errors = active_waiver_files(register, critical)
    failed = False

    for error in waiver_errors:
        print(error)
        failed = True

    compare_range = detect_compare_range()
    changed = changed_files(compare_range=compare_range)
    critical_changed = sorted(rel for rel in changed if rel in critical)

    if compare_range:
        print(f"Using compare range: {compare_range}")
    else:
        print("No compare range detected; checking only waiver validity.")

    for rel in critical_changed:
        current_lines = line_count(ROOT / rel)
        budget = int(critical[rel]["max_lines"])
        error = evaluate_critical_hotspot_change(
            rel,
            lines=current_lines,
            budget=budget,
            has_active_waiver=rel in active_waivers,
        )
        if error:
            print(error)
            failed = True
        elif current_lines < budget:
            print(f"PASS {rel}: shrank from ratchet budget {budget} to {current_lines}")
        else:
            waiver = active_waivers[rel]
            print(
                f"WAIVED {rel}: active waiver until {waiver['expiry']} allows a non-shrinking critical-hotspot change"
            )

    if failed:
        print("Critical hotspot change guardrails failed.")
        return 1

    print("Critical hotspot change guardrails passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
