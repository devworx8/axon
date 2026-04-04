from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from axon_api.services import auto_sessions as auto_session_service
from axon_api.services import sandbox_sessions


class AutoSessionServiceTests(unittest.TestCase):
    def _git(self, cwd: Path, *args: str) -> str:
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Axon Tests",
            "GIT_AUTHOR_EMAIL": "axon@example.com",
            "GIT_COMMITTER_NAME": "Axon Tests",
            "GIT_COMMITTER_EMAIL": "axon@example.com",
        }
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        if result.returncode != 0:
            raise AssertionError(result.stderr or result.stdout or f"git {' '.join(args)} failed")
        return (result.stdout or "").strip()

    def test_auto_session_apply_copies_changes_back_to_source(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            repo_root = root / "repo"
            auto_root = root / "autos"
            repo_root.mkdir()
            self._git(repo_root, "init")
            (repo_root / "app.txt").write_text("old\n", encoding="utf-8")
            self._git(repo_root, "add", "app.txt")
            self._git(repo_root, "commit", "-m", "init")

            workspace = {"id": 7, "name": "Demo", "path": str(repo_root)}
            with patch.dict(sandbox_sessions.SANDBOX_ROOTS, {"auto": auto_root}, clear=False):
                meta = auto_session_service.ensure_auto_session(
                    "auto-1",
                    workspace,
                    title="Auto demo",
                    detail="Run autonomously",
                    metadata={"status": "completed"},
                )
                sandbox_dir = Path(meta["sandbox_path"])
                (sandbox_dir / "app.txt").write_text("new\n", encoding="utf-8")
                refreshed = auto_session_service.refresh_auto_session("auto-1")
                result = auto_session_service.apply_auto_session("auto-1")

            self.assertEqual(refreshed["status"], "review_ready")
            self.assertTrue(result["applied"])
            self.assertEqual((repo_root / "app.txt").read_text(encoding="utf-8"), "new\n")
            self.assertIn("Applied", result["summary"])

    def test_auto_session_discard_removes_worktree(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            repo_root = root / "repo"
            auto_root = root / "autos"
            repo_root.mkdir()
            self._git(repo_root, "init")
            (repo_root / "app.txt").write_text("old\n", encoding="utf-8")
            self._git(repo_root, "add", "app.txt")
            self._git(repo_root, "commit", "-m", "init")

            workspace = {"id": 8, "name": "Demo", "path": str(repo_root)}
            with patch.dict(sandbox_sessions.SANDBOX_ROOTS, {"auto": auto_root}, clear=False):
                meta = auto_session_service.ensure_auto_session(
                    "auto-2",
                    workspace,
                    title="Auto demo",
                    detail="Run autonomously",
                    metadata={"status": "ready"},
                )
                sandbox_dir = Path(meta["sandbox_path"])
                result = auto_session_service.discard_auto_session("auto-2")

            self.assertTrue(result["discarded"])
            self.assertFalse(sandbox_dir.exists())

    def test_auto_session_apply_detects_source_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            repo_root = root / "repo"
            auto_root = root / "autos"
            repo_root.mkdir()
            self._git(repo_root, "init")
            (repo_root / "app.txt").write_text("old\n", encoding="utf-8")
            self._git(repo_root, "add", "app.txt")
            self._git(repo_root, "commit", "-m", "init")

            workspace = {"id": 9, "name": "Demo", "path": str(repo_root)}
            with patch.dict(sandbox_sessions.SANDBOX_ROOTS, {"auto": auto_root}, clear=False):
                meta = auto_session_service.ensure_auto_session(
                    "auto-3",
                    workspace,
                    title="Auto demo",
                    detail="Run autonomously",
                    metadata={"status": "running"},
                )
                sandbox_dir = Path(meta["sandbox_path"])
                (sandbox_dir / "app.txt").write_text("from sandbox\n", encoding="utf-8")
                (repo_root / "app.txt").write_text("from source\n", encoding="utf-8")
                with self.assertRaises(RuntimeError):
                    auto_session_service.apply_auto_session("auto-3")

    def test_auto_report_uses_evidence_sections(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            repo_root = root / "repo"
            auto_root = root / "autos"
            repo_root.mkdir()
            self._git(repo_root, "init")
            (repo_root / "app.txt").write_text("old\n", encoding="utf-8")
            self._git(repo_root, "add", "app.txt")
            self._git(repo_root, "commit", "-m", "init")

            workspace = {"id": 10, "name": "Demo", "path": str(repo_root)}
            with patch.dict(sandbox_sessions.SANDBOX_ROOTS, {"auto": auto_root}, clear=False):
                auto_session_service.ensure_auto_session(
                    "auto-4",
                    workspace,
                    title="Auto demo",
                    detail="Run autonomously",
                    metadata={
                        "status": "completed",
                        "final_output": "Changed the landing page.",
                        "command_receipts": [{"command": "git diff --stat", "summary": "1 file changed"}],
                        "verification_receipts": [{"command": "npm run build", "label": "npm run build", "summary": "passed"}],
                        "inferred_notes": ["The next step likely touches dashboard polish."],
                    },
                )
                refreshed = auto_session_service.refresh_auto_session("auto-4")

            report = refreshed["report_markdown"]
            self.assertIn("## Verified In This Run", report)
            self.assertIn("## Inferred From Repo State", report)
            self.assertIn("## Not Yet Verified", report)
            self.assertIn("## Next Action Not Yet Taken", report)

    def test_auto_refresh_ignores_codex_runtime_artifact(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            repo_root = root / "repo"
            auto_root = root / "autos"
            repo_root.mkdir()
            self._git(repo_root, "init")
            (repo_root / "README.md").write_text("hello\n", encoding="utf-8")
            self._git(repo_root, "add", "README.md")
            self._git(repo_root, "commit", "-m", "init")

            workspace = {"id": 14, "name": "Demo", "path": str(repo_root)}
            with patch.dict(sandbox_sessions.SANDBOX_ROOTS, {"auto": auto_root}, clear=False):
                meta = auto_session_service.ensure_auto_session(
                    "auto-5",
                    workspace,
                    title="Auto demo",
                    detail="Run autonomously",
                    metadata={"status": "ready"},
                )
                sandbox_dir = Path(meta["sandbox_path"])
                (sandbox_dir / ".codex").write_text("runtime cache\n", encoding="utf-8")
                refreshed = auto_session_service.refresh_auto_session("auto-5")

            self.assertEqual(refreshed["changed_files"], [])
            self.assertEqual(refreshed["status"], "ready")

    def test_auto_refresh_promotes_stale_running_session_to_review_ready(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            repo_root = root / "repo"
            auto_root = root / "autos"
            repo_root.mkdir()
            self._git(repo_root, "init")
            (repo_root / "README.md").write_text("hello\n", encoding="utf-8")
            self._git(repo_root, "add", "README.md")
            self._git(repo_root, "commit", "-m", "init")

            workspace = {"id": 15, "name": "Demo", "path": str(repo_root)}
            with patch.dict(sandbox_sessions.SANDBOX_ROOTS, {"auto": auto_root}, clear=False):
                meta = auto_session_service.ensure_auto_session(
                    "auto-6",
                    workspace,
                    title="Auto demo",
                    detail="Run autonomously",
                    metadata={
                        "status": "running",
                        "last_run_completed_at": "2026-04-01T10:00:00Z",
                        "final_output": "Changed the landing page copy.",
                        "verification_receipts": [{"command": "npm run build", "summary": "passed"}],
                    },
                )
                sandbox_dir = Path(meta["sandbox_path"])
                (sandbox_dir / "README.md").write_text("updated\n", encoding="utf-8")
                refreshed = auto_session_service.refresh_auto_session("auto-6")

            self.assertEqual(refreshed["status"], "review_ready")
            self.assertEqual(refreshed["last_error"], "")

    def test_auto_refresh_marks_stale_running_session_without_handoff_as_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            repo_root = root / "repo"
            auto_root = root / "autos"
            repo_root.mkdir()
            self._git(repo_root, "init")
            (repo_root / "README.md").write_text("hello\n", encoding="utf-8")
            self._git(repo_root, "add", "README.md")
            self._git(repo_root, "commit", "-m", "init")

            workspace = {"id": 16, "name": "Demo", "path": str(repo_root)}
            with patch.dict(sandbox_sessions.SANDBOX_ROOTS, {"auto": auto_root}, clear=False):
                auto_session_service.ensure_auto_session(
                    "auto-7",
                    workspace,
                    title="Auto demo",
                    detail="Run autonomously",
                    metadata={
                        "status": "running",
                        "last_run_completed_at": "2026-04-01T10:00:00Z",
                    },
                )
                refreshed = auto_session_service.refresh_auto_session("auto-7")

            self.assertEqual(refreshed["status"], "error")
            self.assertIn("reviewable handoff", refreshed["last_error"])

    def test_auto_refresh_marks_deleted_or_invalid_worktree_as_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            repo_root = root / "repo"
            auto_root = root / "autos"
            repo_root.mkdir()
            self._git(repo_root, "init")
            (repo_root / "README.md").write_text("hello\n", encoding="utf-8")
            self._git(repo_root, "add", "README.md")
            self._git(repo_root, "commit", "-m", "init")

            workspace = {"id": 17, "name": "Demo", "path": str(repo_root)}
            with patch.dict(sandbox_sessions.SANDBOX_ROOTS, {"auto": auto_root}, clear=False):
                meta = auto_session_service.ensure_auto_session(
                    "auto-8",
                    workspace,
                    title="Auto demo",
                    detail="Run autonomously",
                    metadata={"status": "running"},
                )
                sandbox_dir = Path(meta["sandbox_path"])
                git_dir = sandbox_dir / ".git"
                if git_dir.is_file():
                    git_dir.unlink()
                elif git_dir.exists():
                    shutil.rmtree(git_dir)
                refreshed = auto_session_service.refresh_auto_session("auto-8")

            self.assertEqual(refreshed["status"], "error")
            self.assertIn("valid git worktree", refreshed["last_error"])
            self.assertIn("## Not Yet Verified", refreshed["report_markdown"])


if __name__ == "__main__":
    unittest.main()
