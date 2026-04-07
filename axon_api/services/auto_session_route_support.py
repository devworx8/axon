"""Support helpers for auto-session route handlers."""

from __future__ import annotations

from typing import Any, Callable


def auto_session_title(message: str, workspace_name: str = "") -> str:
    text = " ".join(str(message or "").strip().split())
    return text[:120] if text else f"{workspace_name or 'Workspace'} Auto session".strip()


def auto_resume_prompt(session_meta: dict[str, Any], resume_message: str = "") -> str:
    text = " ".join(str(resume_message or "").strip().split())
    prompt_lines = [
        "Continue the existing Axon Auto session in this sandbox.",
        "Do not ask whether to continue or start over.",
        "Stay inside the sandbox and either make the next concrete change or report a real blocker with receipts.",
    ]
    if text and text.lower() not in {"continue", "please continue", "resume", "retry"}:
        prompt_lines.extend(["", f"Resume instruction: {text}"])
    prior = str(session_meta.get("report_markdown") or session_meta.get("final_output") or "").strip()
    if prior:
        prompt_lines.extend(["", "Previous session state:", prior[:4000]])
    return "\n".join(prompt_lines).strip()


def refresh_listed_auto_sessions(
    rows: list[dict[str, Any]],
    refresh_auto_session: Callable[[str], dict[str, Any] | None],
) -> list[dict[str, Any]]:
    refreshed_rows: list[dict[str, Any]] = []
    for row in rows:
        session_id = str(row.get("session_id") or "").strip()
        if not session_id:
            continue
        status = str(row.get("status") or "").strip().lower()
        if status not in {"running", "completed", "ready", "error", "approval_required"} and not row.get("last_run_completed_at"):
            refreshed_rows.append(row)
            continue
        try:
            refreshed_rows.append(refresh_auto_session(session_id) or row)
        except Exception as exc:
            degraded = dict(row)
            degraded["status"] = "error"
            degraded["last_error"] = str(exc)
            refreshed_rows.append(degraded)
    return refreshed_rows


def stopped_auto_session_meta(session_meta: dict[str, Any], now_iso: Callable[[], str], detail: str = "Stopped by user.") -> dict[str, Any]:
    meta = dict(session_meta or {})
    final_output = str(meta.get("final_output") or "").strip()
    if detail and detail not in final_output:
        final_output = "\n\n".join(part for part in (final_output, detail) if part).strip()
    meta.update(
        {
            "status": "error",
            "detail": detail,
            "last_error": detail,
            "final_output": final_output,
            "last_run_completed_at": now_iso(),
        }
    )
    return meta
