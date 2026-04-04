from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from axon_data import get_db, list_companion_devices, revoke_companion_device


TEST_MARKERS = (
    "smoke",
    "codex",
    "vercel",
    "expo control",
    "appwide debug",
)


@dataclass
class PlannedCleanup:
    device_id: int
    name: str
    device_key: str
    reason: str


def _matches_test_device(name: str, device_key: str) -> bool:
    haystack = f"{name} {device_key}".strip().lower()
    return any(marker in haystack for marker in TEST_MARKERS)


async def _load_active_devices():
    async with get_db() as db:
        rows = [dict(row) for row in await list_companion_devices(db, limit=500)]
    return [
        row for row in rows
        if str(row.get("status") or "").strip().lower() != "revoked"
    ]


def _plan_cleanup(rows: list[dict], *, dedupe_names: set[str]) -> list[PlannedCleanup]:
    plans: list[PlannedCleanup] = []
    seen_keepers: dict[str, int] = {}
    sorted_rows = sorted(
        rows,
        key=lambda row: str(row.get("last_seen_at") or row.get("updated_at") or ""),
        reverse=True,
    )
    for row in sorted_rows:
        device_id = int(row.get("id") or 0)
        name = str(row.get("name") or "").strip()
        device_key = str(row.get("device_key") or "").strip()
        lowered_name = name.lower()
        if _matches_test_device(name, device_key):
            plans.append(PlannedCleanup(device_id, name, device_key, "test/smoke device"))
            continue
        if lowered_name in dedupe_names:
            if lowered_name not in seen_keepers:
                seen_keepers[lowered_name] = device_id
                continue
            plans.append(PlannedCleanup(device_id, name, device_key, f"older duplicate of '{name}'"))
    return sorted(plans, key=lambda item: item.device_id)


async def _apply_cleanup(plans: list[PlannedCleanup]) -> None:
    async with get_db() as db:
        for item in plans:
            await revoke_companion_device(db, item.device_id, commit=False)
        await db.commit()


async def main() -> int:
    parser = argparse.ArgumentParser(description="Revoke stale Axon companion smoke/test devices.")
    parser.add_argument("--apply", action="store_true", help="Actually revoke the planned devices.")
    parser.add_argument(
        "--dedupe-name",
        action="append",
        default=[],
        help="Keep the most recent active device with this exact name and revoke older duplicates.",
    )
    args = parser.parse_args()

    rows = await _load_active_devices()
    dedupe_names = {str(name).strip().lower() for name in (args.dedupe_name or []) if str(name).strip()}
    plans = _plan_cleanup(rows, dedupe_names=dedupe_names)

    if not plans:
        print("No stale companion test devices matched.")
        return 0

    print("Planned revocations:")
    for item in plans:
        label = item.name or item.device_key or f"device #{item.device_id}"
        print(f"  - #{item.device_id} {label} [{item.reason}]")

    if not args.apply:
        print("\nDry run only. Re-run with --apply to revoke them.")
        return 0

    await _apply_cleanup(plans)
    print(f"\nRevoked {len(plans)} stale companion device(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
