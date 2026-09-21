from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from jev_astra_bench.model import AttemptRecord


class EvidenceExportTests(unittest.TestCase):
    def test_export_redacts_sensitive_fields_and_hashes_every_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            payload = AttemptRecord(
                "task",
                "astra_jev_offload_guarded",
                1,
                success=True,
                duration_s=1.0,
                astra_input_tokens=100,
                astra_cached_input_tokens=20,
                astra_cache_write_input_tokens=0,
                astra_output_tokens=10,
                jev_strategy_choices=["inspect_then_edit_test"],
                jev_strategy_calls=1,
                jev_guard_calls=1,
            ).to_public_dict()
            payload["api_key"] = "test_key_example_secret"
            payload["local_path"] = r"C:\Users\private\workspace"
            payload["pricing_source"] = "https://developers.openai.com/api/docs/pricing"
            (source / "attempts.jsonl").write_text(
                json.dumps(payload, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            output = root / "evidence"
            output.mkdir()
            (output / "sample").mkdir()
            script = Path(__file__).parents[1] / "scripts" / "export-evidence.py"

            command = [
                sys.executable,
                str(script),
                "--input",
                f"sample={source}",
                "--output",
                str(output),
                "--date",
                "2026-09-21",
                "--source-commit",
                "abc123",
            ]
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            exported = (output / "sample" / "attempts.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("test_key_example_secret", exported)
            self.assertNotIn(r"C:\Users\private", exported)
            self.assertIn("https://developers.openai.com/api/docs/pricing", exported)
            exported_record = json.loads(exported)
            self.assertEqual(exported_record["astra_input_tokens"], 100)
            self.assertEqual(exported_record["astra_cached_input_tokens"], 20)
            self.assertEqual(exported_record["jev_strategy_choices"], ["inspect_then_edit_test"])
            self.assertEqual(exported_record["jev_strategy_calls"], 1)
            self.assertEqual(exported_record["jev_guard_calls"], 1)
            report = json.loads((output / "combined-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["records"], 1)
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["records"], 1)
            self.assertEqual(manifest["source_commit"], "abc123")
            for relative, expected_hash in manifest["sha256"].items():
                actual_hash = hashlib.sha256((output / relative).read_bytes()).hexdigest()
                self.assertEqual(actual_hash, expected_hash)

            replacement = subprocess.run(
                [*command, "--replace"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(replacement.returncode, 0, replacement.stderr)


if __name__ == "__main__":
    unittest.main()
