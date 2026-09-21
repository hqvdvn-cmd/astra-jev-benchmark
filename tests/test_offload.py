from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from jev_astra_bench.model import TaskSpec
from jev_astra_bench.offload import strategy_instruction, strategy_prompt


class OffloadStrategyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.task = TaskSpec("t", "code_write", "Do the task", Path("."), "check")

    def test_strategy_prompt_combines_task_strategy_and_retry_evidence(self) -> None:
        prompt = strategy_prompt(
            self.task,
            "edit_then_test",
            "Reduce the change to the declared scope and preserve passing tests.",
        )

        self.assertIn("Do the task", prompt)
        self.assertIn("Make the smallest required edit", prompt)
        self.assertIn("previous pass", prompt)
        self.assertIn("Reduce the change to the declared scope", prompt)

    def test_unknown_strategy_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            strategy_instruction("unknown")


if __name__ == "__main__":
    unittest.main()
