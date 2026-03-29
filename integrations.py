"""
Axon — Integrations
GitHub · Slack · Generic webhooks

All integrations are opt-in via Settings.
"""

import asyncio
import json
import os
import subprocess
from datetime import datetime
from typing import Optional
import aiohttp


# ─── GitHub ──────────────────────────────────────────────────────────────────

def _github_env(token: str = "") -> dict:
    """Build env vars for gh/GitHub calls, optionally injecting a saved token."""
    env = dict(os.environ)
    if token:
        env["GH_TOKEN"] = token
        env["GITHUB_TOKEN"] = token
    return env

async def github_get_prs(repo_path: str, token: str = "") -> list[dict]:
    """Fetch open PRs for a local git repo using gh CLI or API."""
    try:
        # Try gh CLI first (handles auth automatically)
        proc = await asyncio.create_subprocess_exec(
            "gh", "pr", "list", "--json",
            "number,title,state,url,author,createdAt,isDraft,reviewDecision",
            "--limit", "10",
            cwd=repo_path,
            env=_github_env(token),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        if proc.returncode == 0:
            return json.loads(stdout.decode())
    except (FileNotFoundError, asyncio.TimeoutError, json.JSONDecodeError):
        pass
    return []


async def github_get_issues(repo_path: str, token: str = "") -> dict:
    """Fetch open issues count and recent issues."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "gh", "issue", "list", "--json", "number,title,state,url,createdAt",
            "--limit", "5", "--state", "open",
            cwd=repo_path,
            env=_github_env(token),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        if proc.returncode == 0:
            issues = json.loads(stdout.decode())
            return {"count": len(issues), "recent": issues}
    except (FileNotFoundError, asyncio.TimeoutError, json.JSONDecodeError):
        pass
    return {"count": 0, "recent": []}


async def github_get_repo_info(repo_path: str, token: str = "") -> dict:
    """Get repo name, default branch, CI status."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "gh", "repo", "view", "--json",
            "name,nameWithOwner,url,defaultBranchRef,description,isPrivate,pushedAt",
            cwd=repo_path,
            env=_github_env(token),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        if proc.returncode == 0:
            return json.loads(stdout.decode())
    except (FileNotFoundError, asyncio.TimeoutError, json.JSONDecodeError):
        pass
    return {}


async def github_get_run_status(repo_path: str, token: str = "") -> dict:
    """Fetch latest CI run status."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "gh", "run", "list", "--limit", "3", "--json",
            "status,conclusion,name,createdAt,url",
            cwd=repo_path,
            env=_github_env(token),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        if proc.returncode == 0:
            runs = json.loads(stdout.decode())
            latest = runs[0] if runs else {}
            return {"runs": runs, "latest": latest}
    except (FileNotFoundError, asyncio.TimeoutError, json.JSONDecodeError):
        pass
    return {"runs": [], "latest": {}}


async def github_full_status(repo_path: str, token: str = "") -> dict:
    """Aggregate GitHub data for a project."""
    repo, prs, issues, ci = await asyncio.gather(
        github_get_repo_info(repo_path, token),
        github_get_prs(repo_path, token),
        github_get_issues(repo_path, token),
        github_get_run_status(repo_path, token),
        return_exceptions=True,
    )
    return {
        "repo": repo if isinstance(repo, dict) else {},
        "prs": prs if isinstance(prs, list) else [],
        "open_pr_count": len(prs) if isinstance(prs, list) else 0,
        "issues": issues if isinstance(issues, dict) else {"count": 0, "recent": []},
        "ci": ci if isinstance(ci, dict) else {"runs": [], "latest": {}},
    }


def is_gh_available() -> bool:
    """Check if GitHub CLI is installed and authenticated."""
    try:
        result = subprocess.run(
            ["gh", "auth", "status"], capture_output=True, timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# ─── Slack ────────────────────────────────────────────────────────────────────

async def slack_send(webhook_url: str, text: str, blocks: Optional[list] = None) -> bool:
    """POST a message to a Slack Incoming Webhook."""
    if not webhook_url or not webhook_url.startswith("https://hooks.slack.com/"):
        return False
    payload: dict = {"text": text}
    if blocks:
        payload["blocks"] = blocks
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                webhook_url, json=payload, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                return resp.status == 200
    except Exception:
        return False


def _digest_to_slack_blocks(digest: str, project_name: str = "") -> list:
    """Convert markdown digest text to Slack Block Kit blocks."""
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "☀️ Axon Morning Brief"},
        }
    ]
    if project_name:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"*Workspace focus:* {project_name}"}]
        })

    # Split into paragraphs and add as sections (strip markdown symbols for Slack mrkdwn)
    for para in digest.split("\n\n")[:6]:
        para = para.strip()
        if not para:
            continue
        # Convert markdown bold to Slack bold
        para = para.replace("**", "*")
        # Cap length
        if len(para) > 2900:
            para = para[:2900] + "…"
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": para}
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": f"✦ Axon · {datetime.now().strftime('%A, %d %B %Y')}"
        }]
    })
    return blocks


async def slack_send_digest(webhook_url: str, digest: str) -> bool:
    """Send a formatted morning digest to Slack."""
    blocks = _digest_to_slack_blocks(digest)
    fallback = digest[:2000].replace("**", "").replace("#", "")
    return await slack_send(webhook_url, fallback, blocks=blocks)


async def slack_send_alert(webhook_url: str, title: str, body: str,
                           urgency: str = "normal") -> bool:
    """Send an alert notification to Slack."""
    emoji = {"critical": "🚨", "high": "⚠️", "normal": "ℹ️"}.get(urgency, "ℹ️")
    text = f"{emoji} *{title}*\n{body}"
    return await slack_send(webhook_url, text)


# ─── Generic Webhooks ────────────────────────────────────────────────────────

async def fire_webhook(url: str, event: str, payload: dict, secret: str = "") -> bool:
    """POST an Axon event payload to any external URL."""
    if not url:
        return False
    body = {
        "event": event,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "data": payload,
    }
    headers = {"Content-Type": "application/json", "X-DevBrain-Event": event}
    if secret:
        import hmac, hashlib
        sig = hmac.new(
            secret.encode(), json.dumps(body).encode(), hashlib.sha256
        ).hexdigest()
        headers["X-DevBrain-Signature"] = f"sha256={sig}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=body, headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                return resp.status < 300
    except Exception:
        return False


async def fire_all_webhooks(webhook_urls_csv: str, event: str,
                             payload: dict, secret: str = "") -> None:
    """Enqueue webhooks for reliable delivery with retry."""
    import db as devdb
    urls = [u.strip() for u in webhook_urls_csv.split(",") if u.strip().startswith("http")]
    if not urls:
        return
    payload_json = json.dumps({
        "event": event,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "data": payload,
    })
    try:
        async with devdb.get_db() as conn:
            for url in urls:
                await devdb.enqueue_webhook(conn, url, event, payload_json, secret)
    except Exception:
        # Fallback: fire-and-forget if DB unavailable
        await asyncio.gather(
            *[fire_webhook(u, event, payload, secret) for u in urls],
            return_exceptions=True,
        )


async def process_webhook_queue() -> int:
    """Process pending webhook jobs. Returns count of jobs processed.
    Call this from the scheduler every 30–60 seconds."""
    import db as devdb
    processed = 0
    try:
        async with devdb.get_db() as conn:
            jobs = await devdb.get_pending_webhooks(conn, limit=20)
            for job in jobs:
                job = dict(job)
                url = job["webhook_url"]
                headers = {"Content-Type": "application/json",
                           "X-DevBrain-Event": job["event"]}
                if job["secret"]:
                    import hmac, hashlib
                    sig = hmac.new(
                        job["secret"].encode(), job["payload_json"].encode(),
                        hashlib.sha256
                    ).hexdigest()
                    headers["X-DevBrain-Signature"] = f"sha256={sig}"
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            url, data=job["payload_json"], headers=headers,
                            timeout=aiohttp.ClientTimeout(total=10)
                        ) as resp:
                            if resp.status < 300:
                                await devdb.mark_webhook_sent(conn, job["id"])
                            else:
                                backoff = 30 * (2 ** job["attempt_count"])
                                await devdb.mark_webhook_failed(
                                    conn, job["id"],
                                    f"HTTP {resp.status}", backoff)
                except Exception as exc:
                    backoff = 30 * (2 ** job["attempt_count"])
                    await devdb.mark_webhook_failed(
                        conn, job["id"], str(exc)[:200], backoff)
                processed += 1
    except Exception:
        pass
    return processed
