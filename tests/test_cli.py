from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))

from jev_astra_bench.cli import _make_workspace_dir, main, rotated_modes
from jev_astra_bench.codex_events import ParsedCodexEvents
from jev_astra_bench.codex_runner import CodexAttempt


class CliTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows ACL regression")
    def test_workspace_directory_keeps_inherited_windows_acl(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "workspace-root"
            root.mkdir()
            created = _make_workspace_dir(root, "astra_only", "code-write-001", 1)
            result = subprocess.run(
                ["icacls.exe", str(created)],
                capture_output=True,
                text=True,
                check=True,
            )

        self.assertIn("(I)", result.stdout)

    def test_astra_only_preflight_does_not_require_jev_key(self) -> None:
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}, clear=False):
            code = main(["preflight", "--mode", "astra_only", "--task-id", "code-write-001"])
        self.assertEqual(code, 0)

    def test_simulated_five_mode_run_writes_records_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            code = main([
                "run", "--simulate", "--repeats", "1", "--output", str(output),
                "--mode", "astra_only", "--mode", "astra_jev_observe", "--mode", "astra_jev_offload",
                "--mode", "astra_jev_guarded", "--mode", "astra_jev_offload_guarded",
            ])
            lines = (output / "attempts.jsonl").read_text(encoding="utf-8").splitlines()
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(len(lines), 15)
        self.assertEqual(
            set(report["modes"]),
            {
                "astra_only",
                "astra_jev_observe",
                "astra_jev_offload",
                "astra_jev_guarded",
                "astra_jev_offload_guarded",
            },
        )
        self.assertEqual(report["modes"]["astra_only"]["attempts"], 3)
        self.assertEqual(report["modes"]["astra_jev_guarded"]["attempts"], 3)
        self.assertEqual(report["modes"]["astra_jev_guarded"]["successes"], 3)
        self.assertEqual(report["modes"]["astra_jev_guarded"]["pass_count"], 3)
        self.assertEqual(report["modes"]["astra_jev_guarded"]["retry_count"], 0)
        self.assertIn("astra_jev_offload", report["comparisons_to_astra_only"])
        self.assertIn("astra_jev_guarded", report["comparisons_to_astra_only"])
        self.assertIn("astra_jev_offload_guarded", report["comparisons_to_astra_only"])
        hybrid = report["modes"]["astra_jev_offload_guarded"]
        self.assertEqual(
            hybrid["jev_calls"],
            hybrid["jev_strategy_calls"] + hybrid["jev_guard_calls"],
        )
        self.assertGreaterEqual(hybrid["mean_jev_calls_per_attempt"], 2)
        self.assertEqual(report["run_metadata"]["astra_models"], ["gpt-6-astra"])

    def test_rotated_modes_changes_the_leading_mode_each_repeat(self) -> None:
        modes = ("astra_only", "astra_jev_observe", "astra_jev_offload")

        self.assertEqual(rotated_modes(modes, 1), modes)
        self.assertEqual(
            rotated_modes(modes, 2),
            ("astra_jev_observe", "astra_jev_offload", "astra_only"),
        )

    def test_max_astra_passes_rejects_values_above_three(self) -> None:
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(SystemExit):
            main([
                "run",
                "--simulate",
                "--output",
                str(Path(directory) / "run"),
                "--max-astra-passes",
                "4",
            ])

    def test_max_astra_passes_accepts_explicit_three(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            code = main([
                "run",
                "--simulate",
                "--repeats",
                "1",
                "--task-id",
                "code-write-001",
                "--mode",
                "astra_jev_guarded",
                "--output",
                str(Path(directory) / "run"),
                "--max-astra-passes",
                "3",
            ])

        self.assertEqual(code, 0)

    def test_report_rebuilds_from_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            rebuilt = Path(directory) / "rebuilt.json"
            self.assertEqual(main(["run", "--simulate", "--repeats", "1", "--output", str(run)]), 0)
            self.assertEqual(main(["report", "--input", str(run), "--output", str(rebuilt)]), 0)
            self.assertTrue(rebuilt.exists())

    def test_task_filter_runs_only_selected_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            code = main([
                "run", "--simulate", "--repeats", "1", "--output", str(output),
                "--task-id", "bug-fix-001",
            ])
            lines = (output / "attempts.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(code, 0)
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["task_id"], "bug-fix-001")

    def test_infrastructure_failure_stops_the_run(self) -> None:
        failed = CodexAttempt(
            ParsedCodexEvents(None, None, None, 0, 0, False),
            0.01,
            1,
            False,
            ("fake-codex",),
        )
        with tempfile.TemporaryDirectory() as directory, patch(
            "jev_astra_bench.cli._simulate_codex",
            return_value=failed,
        ):
            output = Path(directory) / "run"
            code = main([
                "run", "--simulate", "--repeats", "1", "--output", str(output),
                "--task-id", "code-write-001", "--mode", "astra_only",
            ])
            lines = (output / "attempts.jsonl").read_text(encoding="utf-8").splitlines()

        self.assertEqual(code, 3)
        self.assertEqual(len(lines), 1)

    def test_resume_replaces_only_infrastructure_failures(self) -> None:
        modes = [
            "astra_only",
            "astra_jev_observe",
            "astra_jev_offload",
            "astra_jev_guarded",
            "astra_jev_offload_guarded",
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            arguments = [
                "run", "--simulate", "--repeats", "1", "--output", str(output),
                *[value for mode in modes for value in ("--mode", mode)],
            ]
            self.assertEqual(main(arguments), 0)
            records = [
                json.loads(line)
                for line in (output / "attempts.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            records[7]["success"] = False
            records[7]["codex_exit_code"] = 1
            records[7]["codex_completed"] = False
            records[7]["verification_status"] = "codex_failed"
            records[7]["failure_reason"] = "exit_1"
            (output / "attempts.jsonl").write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )

            try:
                resumed_code = main([*arguments, "--resume"])
            except SystemExit as error:
                resumed_code = error.code
            self.assertEqual(resumed_code, 0)
            resumed = [
                json.loads(line)
                for line in (output / "attempts.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            archived = list(output.glob("attempts.interrupted-*.jsonl"))

        self.assertEqual(len(resumed), 15)
        self.assertTrue(all(record["success"] for record in resumed))
        self.assertEqual(len(archived), 1)

    def test_custom_workspace_root_contains_retained_failed_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / "fixture"
            fixture.mkdir()
            (fixture / "sample.txt").write_text("sample", encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps({
                    "tasks": [{
                        "task_id": "fails-001",
                        "kind": "code_write",
                        "prompt": "leave the fixture unchanged",
                        "fixture_dir": "fixture",
                        "verifier": "python -c import sys;sys.exit(1)",
                    }]
                }),
                encoding="utf-8",
            )
            output = root / "run"
            workspace_root = root / "authorized-workspaces"
            code = main([
                "run", "--simulate", "--repeats", "1", "--output", str(output),
                "--task-set", str(manifest), "--workspace-root", str(workspace_root),
                "--keep-failed-workspaces",
            ])
            retained = list(workspace_root.glob("*/workspace/sample.txt"))

        self.assertEqual(code, 0)
        self.assertEqual(len(retained), 1)
        self.assertLessEqual(len(retained[0].parent.parent.name), 32)


if __name__ == "__main__":
    unittest.main()
