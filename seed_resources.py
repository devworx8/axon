#!/usr/bin/env python3
"""Seed Axon's resource bank with high-value coding references.

Run from .devbrain/: python3 seed_resources.py
Bypasses HTTP auth by using Axon's DB + resource_bank modules directly.
"""

import asyncio
import ssl
import sys
import urllib.request
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import resource_bank        # noqa: E402
from axon_data import add_resource, get_all_settings, get_db, replace_resource_chunks  # noqa: E402

# ── Resources to fetch & seed ──────────────────────────────────────────────
# (title, url)  — raw GitHub markdown/text URLs
RESOURCES = [
    # ── Python ──
    ("PEP 8 – Python Style Guide",
     "https://raw.githubusercontent.com/python/peps/main/peps/pep-0008.rst"),
    ("PEP 20 – The Zen of Python",
     "https://raw.githubusercontent.com/python/peps/main/peps/pep-0020.rst"),
    ("Python Type Hints Cheat Sheet (mypy)",
     "https://raw.githubusercontent.com/python/mypy/master/docs/source/cheat_sheet_py3.rst"),

    # ── TypeScript / JavaScript ──
    ("Airbnb JavaScript Style Guide",
     "https://raw.githubusercontent.com/airbnb/javascript/master/README.md"),
    ("Clean Code TypeScript (SOLID + Patterns)",
     "https://raw.githubusercontent.com/labs42io/clean-code-typescript/master/README.md"),
    ("TypeScript Deep Dive – Compiler Options",
     "https://raw.githubusercontent.com/basarat/typescript-book/master/docs/project/compilation-context.md"),

    # ── React ──
    ("React – Thinking in React",
     "https://raw.githubusercontent.com/reactjs/react.dev/main/src/content/learn/thinking-in-react.md"),
    ("React – Rules of Hooks",
     "https://raw.githubusercontent.com/reactjs/react.dev/main/src/content/reference/rules/rules-of-hooks.md"),
    ("React – Managing State",
     "https://raw.githubusercontent.com/reactjs/react.dev/main/src/content/learn/managing-state.md"),

    # ── Next.js ──
    ("Next.js – Installation (App Router)",
     "https://raw.githubusercontent.com/vercel/next.js/canary/docs/01-app/01-getting-started/01-installation.mdx"),

    # ── FastAPI ──
    ("FastAPI – First Steps",
     "https://raw.githubusercontent.com/fastapi/fastapi/master/docs/en/docs/tutorial/first-steps.md"),
    ("FastAPI – Path Parameters",
     "https://raw.githubusercontent.com/fastapi/fastapi/master/docs/en/docs/tutorial/path-params.md"),
    ("FastAPI – Dependencies",
     "https://raw.githubusercontent.com/fastapi/fastapi/master/docs/en/docs/tutorial/dependencies/index.md"),
    ("FastAPI – Security Overview",
     "https://raw.githubusercontent.com/fastapi/fastapi/master/docs/en/docs/tutorial/security/index.md"),
    ("FastAPI – Background Tasks",
     "https://raw.githubusercontent.com/fastapi/fastapi/master/docs/en/docs/tutorial/background-tasks.md"),
    ("FastAPI – WebSockets",
     "https://raw.githubusercontent.com/fastapi/fastapi/master/docs/en/docs/advanced/websockets.md"),

    # ── Supabase ──
    ("Supabase – Auth Overview",
     "https://raw.githubusercontent.com/supabase/supabase/master/apps/docs/content/guides/auth.mdx"),
    ("Supabase – Row Level Security",
     "https://raw.githubusercontent.com/supabase/supabase/master/apps/docs/content/guides/database/postgres/row-level-security.mdx"),

    # ── Git / Commits ──
    ("Git Cheat Sheet (GitHub Training Kit)",
     "https://raw.githubusercontent.com/github/training-kit/master/downloads/github-git-cheat-sheet.md"),
    ("Conventional Commits 1.0.0",
     "https://raw.githubusercontent.com/conventional-commits/conventionalcommits.org/master/content/v1.0.0/index.md"),

    # ── Architecture ──
    ("Clean Architecture (.NET – README)",
     "https://raw.githubusercontent.com/jasontaylordev/CleanArchitecture/main/README.md"),

    # ── Security (OWASP) ──
    ("OWASP API Security Top 10 – 2023",
     "https://raw.githubusercontent.com/OWASP/API-Security/master/editions/2023/en/0x11-t10.md"),
    ("OWASP – Authentication Cheat Sheet",
     "https://raw.githubusercontent.com/OWASP/CheatSheetSeries/master/cheatsheets/Authentication_Cheat_Sheet.md"),
    ("OWASP – Input Validation Cheat Sheet",
     "https://raw.githubusercontent.com/OWASP/CheatSheetSeries/master/cheatsheets/Input_Validation_Cheat_Sheet.md"),
    ("OWASP – SQL Injection Prevention",
     "https://raw.githubusercontent.com/OWASP/CheatSheetSeries/master/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.md"),
    ("OWASP – CSRF Prevention Cheat Sheet",
     "https://raw.githubusercontent.com/OWASP/CheatSheetSeries/master/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.md"),

    # ── Testing ──
    ("Testing Library – Guiding Principles",
     "https://raw.githubusercontent.com/testing-library/testing-library-docs/main/docs/guiding-principles.mdx"),
    ("Pytest – Getting Started",
     "https://raw.githubusercontent.com/pytest-dev/pytest/main/doc/en/getting-started.rst"),

    # ── Shell ──
    ("Bash Scripting Cheat Sheet",
     "https://raw.githubusercontent.com/LeCoupa/awesome-cheatsheets/master/languages/bash.sh"),

    # ── Node.js ──
    ("Node.js Best Practices (goldbergyoni)",
     "https://raw.githubusercontent.com/goldbergyoni/nodebestpractices/master/README.md"),

    # ── API Design ──
    ("Microsoft REST API Guidelines",
     "https://raw.githubusercontent.com/microsoft/api-guidelines/vNext/azure/Guidelines.md"),
    ("JSON:API Specification v1.1",
     "https://raw.githubusercontent.com/json-api/json-api/gh-pages/_format/1.1/index.md"),

    # ── Expo / React Native ──
    ("Expo – Getting Started",
     "https://raw.githubusercontent.com/expo/expo/main/docs/pages/get-started/introduction.mdx"),

    # ── Prisma ──
    ("Prisma – Quickstart",
     "https://raw.githubusercontent.com/prisma/docs/main/content/100-getting-started/01-quickstart.mdx"),
]


_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


def _fetch(url: str) -> Optional[bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "AxonSeeder/1.0"})
    try:
        with urllib.request.urlopen(req, context=_ssl_ctx, timeout=25) as resp:
            return resp.read()
    except Exception as exc:
        print(f"  ✗ fetch failed: {exc}")
        return None


async def _ingest(conn, title: str, filename: str, content: bytes, mime: str,
                  source_url: str, settings: dict) -> Optional[int]:
    """Insert resource row + chunks into DB, return resource_id."""
    sha = resource_bank.sha256_bytes(content)
    kind = resource_bank.classify_kind(filename, mime)
    root = resource_bank.ensure_storage_root(settings)
    dest = root / sha[:2] / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)

    text = resource_bank.extract_text(dest, mime)
    summary = resource_bank.summarize_text(title, text) if text else ""
    preview = resource_bank.preview_text(text) if text else ""

    rid = await add_resource(
        conn,
        title=title,
        kind=kind,
        source_type="url",
        source_url=source_url,
        local_path=str(dest),
        mime_type=mime,
        size_bytes=len(content),
        sha256=sha,
        status="ready",
        summary=summary,
        preview_text=preview,
    )

    # Chunk + store
    if text and len(text.strip()) > 50:
        raw_chunks = resource_bank.chunk_text(text)
        chunk_dicts = [
            {"chunk_index": i, "text": c, "content": c, "token_estimate": max(1, len(c) // 4)}
            for i, c in enumerate(raw_chunks)
        ]
        await replace_resource_chunks(conn, rid, chunk_dicts)
        print(f"  ✓ #{rid} — {len(raw_chunks)} chunks ({len(content):,} bytes)")
    else:
        print(f"  ✓ #{rid} — stored (no text extracted)")
    return rid


async def main():
    print(f"🌱 Seeding {len(RESOURCES)} resources into Axon (direct DB)...\n")
    success = 0
    failed = []

    async with get_db() as conn:
        settings = await get_all_settings(conn)

        for i, (title, url) in enumerate(RESOURCES, 1):
            print(f"[{i}/{len(RESOURCES)}] {title}")

            raw = _fetch(url)
            if not raw or len(raw) < 50:
                failed.append((title, url))
                continue

            # Derive filename + mime
            path = url.rsplit("/", 1)[-1]
            safe = resource_bank.sanitize_filename(path) or "doc.md"
            mime = resource_bank.detect_mime_type(safe)

            try:
                await _ingest(conn, title, safe, raw, mime, url, settings)
                success += 1
            except Exception as exc:
                print(f"  ✗ ingest error: {exc}")
                failed.append((title, url))

    print(f"\n{'='*60}")
    print(f"✅ Seeded: {success}/{len(RESOURCES)}")
    if failed:
        print(f"❌ Failed ({len(failed)}):")
        for title, url in failed:
            print(f"  - {title}")
            print(f"    {url}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
