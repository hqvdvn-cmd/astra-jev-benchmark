from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from jev_astra_bench.model import TaskSpec
from jev_astra_bench.verification import verify_task


class VerificationTests(unittest.TestCase):
    def test_successful_declared_command_is_verified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            task = TaskSpec("code", "code_write", "", workspace, "python -c \"pass\"")
            result = verify_task(task, workspace)
        self.assertTrue(result.success)
        self.assertEqual(result.status, "verified")

    def test_failed_command_is_external_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            task = TaskSpec("code", "code_write", "", workspace, "python -c \"raise SystemExit(2)\"")
            result = verify_task(task, workspace)
        self.assertFalse(result.success)
        self.assertEqual(result.status, "tests_failed")

    def test_change_outside_allow_list_is_rejected_without_git(self) -> None:
        with tempfile.TemporaryDirectory() as baseline_dir, tempfile.TemporaryDirectory() as workspace_dir:
            baseline = Path(baseline_dir)
            workspace = Path(workspace_dir)
            (baseline / "allowed.py").write_text("old", encoding="utf-8")
            (workspace / "allowed.py").write_text("new", encoding="utf-8")
            (workspace / "extra.txt").write_text("unexpected", encoding="utf-8")
            task = TaskSpec("code", "code_write", "", baseline, "", allowed_files=("allowed.py",))
            result = verify_task(task, workspace)
        self.assertFalse(result.success)
        self.assertEqual(result.status, "changed_file_outside_allow_list")
        self.assertIn("extra.txt", result.changed_files)

    def test_verify_task_counts_changed_lines(self) -> None:
        with tempfile.TemporaryDirectory() as baseline_dir, tempfile.TemporaryDirectory() as workspace_dir:
            baseline = Path(baseline_dir)
            workspace = Path(workspace_dir)
            (baseline / "value.py").write_text("a\nb\n", encoding="utf-8")
            (workspace / "value.py").write_text("a\nc\nd\n", encoding="utf-8")
            task = TaskSpec("t", "code_write", "change", baseline, "", allowed_files=("value.py",))

            result = verify_task(task, workspace)

        self.assertEqual(result.added_lines, 2)
        self.assertEqual(result.deleted_lines, 1)
        self.assertEqual(result.changed_lines, 3)


if __name__ == "__main__":
    unittest.main()
