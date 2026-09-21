from __future__ import annotations

import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from jev_astra_bench.codex_events import ParsedCodexEvents
from jev_astra_bench.codex_runner import CodexAttempt
from jev_astra_bench.model import DecisionResult, TaskSpec
from jev_astra_bench.modes import HarnessContext, run_attempt
from jev_astra_bench.pricing import Pricing
from jev_astra_bench.verification import VerificationResult


class FakeJev:
    def __init__(self, result: DecisionResult):
        self.result = result
        self.calls = 0

    def decide(self, question, state, choices):
        self.calls += 1
        return self.result


def fake_codex(prompt, workspace):
    return CodexAttempt(ParsedCodexEvents("done", 10, 5, 1, 0, True), 0.5, 0, False, ("fake",))


class ModeTests(unittest.TestCase):
    def _context(self, jev):
        return HarnessContext(
            codex_runner=fake_codex,
            jev_client=jev,
            pricing=Pricing(Decimal("1"), Decimal("1"), Decimal("1"), Decimal("0")),
            workspace_factory=lambda task, repeat: Path(tempfile.gettempdir()),
            verifier=lambda task, workspace: VerificationResult(True, "verified", None),
        )

    def test_astra_only_makes_zero_jev_calls(self):
        jev = FakeJev(DecisionResult("ok", "continue", 2, 1))
        result = run_attempt(TaskSpec("t", "code_write", "do", Path("."), ""), "astra_only", 1, self._context(jev))
        self.assertTrue(result.success)
        self.assertEqual(jev.calls, 0)

    def test_observe_preserves_result_and_records_jev(self):
        jev = FakeJev(DecisionResult("ok", "insufficient", 2, 1))
        result = run_attempt(TaskSpec("t", "code_write", "do", Path("."), ""), "astra_jev_observe", 1, self._context(jev))
        self.assertTrue(result.success)
        self.assertEqual(result.jev_calls, 1)

    def test_offload_outage_holds_action(self):
        jev = FakeJev(DecisionResult("unavailable", error_code="timeout"))
        result = run_attempt(TaskSpec("t", "browser", "do", Path("."), ""), "astra_jev_offload", 1, self._context(jev))
        self.assertFalse(result.success)
        self.assertEqual(result.verification_status, "not_checked_by_jev")

    def test_offload_strategy_is_selected_before_astra(self):
        events = []

        class OrderedJev(FakeJev):
            def decide(self, question, state, choices):
                events.append("jev")
                return super().decide(question, state, choices)

        def ordered_codex(prompt, workspace):
            events.append("astra")
            self.assertIn("Inspect the relevant file first", prompt)
            return fake_codex(prompt, workspace)

        jev = OrderedJev(DecisionResult("ok", "inspect_then_edit_test", 2, 0))
        context = self._context(jev)
        context.codex_runner = ordered_codex
        result = run_attempt(TaskSpec("t", "code_write", "do", Path("."), ""), "astra_jev_offload", 1, context)
        self.assertTrue(result.success)
        self.assertEqual(events, ["jev", "astra"])
        self.assertEqual(result.jev_choice, "inspect_then_edit_test")
        self.assertEqual(result.jev_strategy_calls, 1)
        self.assertEqual(result.jev_strategy_choices, ["inspect_then_edit_test"])


if __name__ == "__main__":
    unittest.main()
