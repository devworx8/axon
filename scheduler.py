"""
Axon — Scheduler (APScheduler in-process)
Runs periodic background jobs alongside the FastAPI server.
"""

import asyncio
import subprocess
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from axon_core.cli_command import cli_session_persistence_enabled

# Scheduler is a singleton — created once in server.py
scheduler: Optional[AsyncIOScheduler] = None


def get_scheduler() -> AsyncIOScheduler:
    global scheduler
    if scheduler is None:
        scheduler = AsyncIOScheduler(timezone="Africa/Johannesburg")
    return scheduler


# ─── Desktop Notifications ────────────────────────────────────────────────────

def notify(title: str, body: str, urgency: str = "normal"):
    """Send a Linux desktop notification via notify-send."""
    try:
        subprocess.run(
            ["notify-send", "--app-name=Axon", f"--urgency={urgency}",
             "--icon=computer", title, body],
            check=False, capture_output=True
        )
    except FileNotFoundError:
        # notify-send not available — log to stdout instead
        print(f"[Axon NOTIFY] {title}: {body}")


# ─── Job: Project Health Scan ─────────────────────────────────────────────────

async def job_scan_projects(trigger_type: str = "auto"):
    """Scan all registered project roots and update health scores in DB."""
    print(f"[Axon] Running workspace health scan at {datetime.now().strftime('%H:%M')}")
    try:
        import db as devdb
        import scanner

        async with devdb.get_db() as conn:
            settings = await devdb.get_all_settings(conn)
            roots_raw = settings.get("projects_root", "~/Desktop")
            roots = [r.strip() for r in roots_raw.split(",")]

            projects = await scanner.discover_and_scan(roots)

            for proj_data in projects:
                await devdb.upsert_project(conn, proj_data)

            trigger_label = {
                "auto": "Auto-scan (scheduled)",
                "manual": "Manual scan",
                "startup": "Triggered scan",
            }.get(trigger_type, "Triggered scan")
            await devdb.log_event(
                conn, "scan",
                f"{trigger_label}: scanned {len(projects)} projects from {', '.join(roots)}"
            )

        # Notify about unhealthy projects
        stale = [p for p in projects if p["health"] < 50]
        if stale:
            names = ", ".join(p["name"] for p in stale[:3])
            notify(
                "Axon — Workspace Watch",
                f"{len(stale)} workspace(s) need attention: {names}",
                urgency="normal"
            )

        print(f"[Axon] Scan complete: {len(projects)} workspaces, {len(stale)} stale")

    except Exception as e:
        print(f"[Axon] Scan error: {e}")


# ─── Job: Morning Digest ──────────────────────────────────────────────────────

async def job_morning_digest():
    """Generate and notify the daily morning digest."""
    print(f"[Axon] Generating morning brief at {datetime.now().strftime('%H:%M')}")
    try:
        import db as devdb
        import brain

        async with devdb.get_db() as conn:
            settings = await devdb.get_all_settings(conn)
            backend = settings.get("ai_backend", "ollama")
            api_key = settings.get("anthropic_api_key", "")
            cli_path = settings.get("claude_cli_path", "")
            cli_session_persistence = cli_session_persistence_enabled(
                settings.get("claude_cli_session_persistence_enabled")
            )

            if backend == "api" and not api_key:
                print("[Axon] No Anthropic API key — skipping morning brief")
                return
            if backend == "cli" and not brain._find_cli(cli_path):
                print("[Axon] Cloud CLI not found — skipping morning brief")
                return

            projects = [dict(r) for r in await devdb.get_projects(conn, status="active")]
            tasks = [dict(r) for r in await devdb.get_tasks(conn, status="open")]
            activity = [dict(r) for r in await devdb.get_activity(conn, limit=20)]

            digest = await brain.generate_digest(
                projects, tasks, activity,
                api_key=api_key,
                backend=backend,
                cli_path=cli_path,
                cli_session_persistence=cli_session_persistence,
            )

            await devdb.log_event(conn, "digest", digest[:200] + "..." if len(digest) > 200 else digest)

        # Send desktop notification with first paragraph
        first_para = digest.split("\n\n")[0].replace("**", "").replace("#", "").strip()
        notify("Axon — Morning Brief", first_para[:200], urgency="low")

        print("[Axon] Morning brief complete")

    except Exception as e:
        print(f"[Axon] Morning brief error: {e}")


# ─── Job: Task Reminders ──────────────────────────────────────────────────────

async def job_task_reminders():
    """Check for overdue or urgent tasks and send reminders."""
    try:
        import db as devdb
        from datetime import date

        async with devdb.get_db() as conn:
            tasks = [dict(r) for r in await devdb.get_tasks(conn, status="open")]
            today = date.today().isoformat()

            overdue = []
            urgent = []
            for t in tasks:
                if t.get("due_date") and t["due_date"] < today:
                    overdue.append(t)
                elif t.get("priority") in ("urgent", "high"):
                    urgent.append(t)

            if overdue:
                names = "; ".join(t["title"][:40] for t in overdue[:3])
                notify(
                    "Axon — Overdue Missions",
                    f"{len(overdue)} overdue: {names}",
                    urgency="critical"
                )

            elif urgent and len(urgent) > 3:
                notify(
                    "Axon — Urgent Missions",
                    f"{len(urgent)} high-priority missions open",
                    urgency="normal"
                )

    except Exception as e:
        print(f"[Axon] Mission reminder error: {e}")


# ─── Scheduler setup ─────────────────────────────────────────────────────────

def setup_scheduler(
    scan_interval_hours: int = 6,
    digest_hour: int = 8,
) -> AsyncIOScheduler:
    """Configure and return the scheduler (does NOT start it yet)."""
    sched = get_scheduler()

    # Project scan every N hours
    sched.add_job(
        job_scan_projects,
        trigger=IntervalTrigger(hours=scan_interval_hours),
        id="project_scan",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Morning digest at configured hour (Mon–Fri)
    sched.add_job(
        job_morning_digest,
        trigger=CronTrigger(day_of_week="mon-fri", hour=digest_hour, minute=0),
        id="morning_digest",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # Task reminders at 9am and 2pm
    sched.add_job(
        job_task_reminders,
        trigger=CronTrigger(hour="9,14", minute=0),
        id="task_reminders",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Process webhook retry queue every 45 seconds
    from integrations import process_webhook_queue
    sched.add_job(
        process_webhook_queue,
        trigger=IntervalTrigger(seconds=45),
        id="webhook_queue",
        replace_existing=True,
        misfire_grace_time=30,
    )

    return sched


async def trigger_scan_now(trigger_type: str = "manual"):
    """Run a scan immediately (called from API endpoint)."""
    await job_scan_projects(trigger_type=trigger_type)


async def trigger_digest_now():
    """Run the morning digest immediately (called from API endpoint)."""
    await job_morning_digest()
