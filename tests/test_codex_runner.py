from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from jev_astra_bench.codex_runner import CodexConfig, build_command, run_codex


class CodexRunnerTests(unittest.TestCase):
    def test_command_pins_astra_and_excludes_other_models(self) -> None:
        command = build_command("work", Path("fixture"), CodexConfig())
        self.assertIn("gpt-6-astra", command)
        self.assertNotIn("gpt-5.6-luna", command)
        self.assertNotIn("gpt-5.6-terra", command)
        self.assertNotIn("gpt-5.6-sol", command)
        self.assertNotIn("-a", command)
        self.assertIn('approval_policy="never"', command)
        self.assertNotIn("--ignore-user-config", command)
        self.assertIn("skip_host_skill_discovery", command)
        for feature in ("plugins", "hooks", "apps", "memories", "multi_agent"):
            self.assertIn(feature, command)

    def test_fake_executable_returns_parsed_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            fake = root / "fake_codex.py"
            fake.write_text(
                "import json\n"
                "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'ok'}}))\n"
                "print(json.dumps({'type':'turn.completed','usage':{'input_tokens':3,'output_tokens':2}}))\n",
                encoding="utf-8",
            )
            result = run_codex(
                "work",
                workspace,
                CodexConfig(executable=sys.executable, executable_prefix=(str(fake),), timeout_s=10),
            )
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.parsed.final_text, "ok")
        self.assertEqual(result.parsed.input_tokens, 3)
        self.assertEqual(result.parsed.output_tokens, 2)
        self.assertIn("apply_patch", result.command[-1])

    def test_runner_tells_sandboxed_shells_to_enter_the_exact_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace with spaces"
            workspace.mkdir()
            fake = root / "echo_prompt.py"
            fake.write_text(
                "import json, sys\n"
                "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':sys.argv[-1]}}))\n",
                encoding="utf-8",
            )
            result = run_codex(
                "work",
                workspace,
                CodexConfig(executable=sys.executable, executable_prefix=(str(fake),), timeout_s=10),
            )

        prompt = result.parsed.final_text or ""
        self.assertIn(str(workspace.resolve()), prompt)
        self.assertIn("Set-Location -LiteralPath", prompt)
        self.assertIn("absolute path", prompt)


if __name__ == "__main__":
    unittest.main()
