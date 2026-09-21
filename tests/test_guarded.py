from __future__ import annotations

import sys
import tempfile
import unittest
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from jev_astra_bench.codex_events import ParsedCodexEvents
from jev_astra_bench.codex_runner import CodexAttempt
from jev_astra_bench.guarded import GuardConfig, RETRY_INSTRUCTIONS
from jev_astra_bench.model import DecisionResult, TaskSpec
from jev_astra_bench.modes import HarnessContext, run_attempt
from jev_astra_bench.pricing import Pricing
from jev_astra_bench.verification import VerificationResult


def codex_attempt(*, input_tokens: int = 10, final_text: str = "done") -> CodexAttempt:
    parsed = ParsedCodexEvents(final_text, input_tokens, 5, 1, 0, True, 2, 0)
    return CodexAttempt(parsed, 0.5, 0, False, ("fake",))


class QueuedCodex:
    def __init__(self, *attempts: CodexAttempt) -> None:
        self.attempts = deque(attempts)
        self.prompts: list[str] = []

    def __call__(self, prompt: str, workspace: Path) -> CodexAttempt:
        self.prompts.append(prompt)
        return self.attempts.popleft()


class QueuedVerifier:
    def __init__(self, *results: VerificationResult) -> None:
        self.results = deque(results)

    def __call__(self, task: TaskSpec, workspace: Path) -> VerificationResult:
        return self.results.popleft()


class QueuedJev:
    def __init__(self, *results: DecisionResult) -> None:
        self.results = deque(results)
        self.calls = 0

    def decide(self, question, state, choices) -> DecisionResult:
        self.calls += 1
        return self.results.popleft()


class GuardedModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)
        self.task = TaskSpec("t", "code_write", "Do the task", self.workspace, "check")
        self.verified = VerificationResult(True, "verified", None, ("value.py",), 2, 1)

    def context(self, codex: QueuedCodex, jev: QueuedJev, verifier: QueuedVerifier) -> HarnessContext:
        return HarnessContext(codex, jev, Pricing(), lambda task, repeat: self.workspace, verifier)

    def run_guarded(
        self,
        codex: QueuedCodex,
        jev: QueuedJev,
        verifier: QueuedVerifier,
        *,
        max_passes: int = 2,
        outage_policy: str = "fail_closed",
    ):
        return run_attempt(
            self.task,
            "astra_jev_guarded",
            1,
            self.context(codex, jev, verifier),
            GuardConfig(max_astra_passes=max_passes, outage_policy=outage_policy),
        )

    def run_hybrid(
        self,
        codex: QueuedCodex,
        jev: QueuedJev,
        verifier: QueuedVerifier,
        *,
        max_passes: int = 2,
        outage_policy: str = "fail_closed",
    ):
        return run_attempt(
            self.task,
            "astra_jev_offload_guarded",
            1,
            self.context(codex, jev, verifier),
            GuardConfig(max_astra_passes=max_passes, outage_policy=outage_policy),
        )

    def test_accept_finishes_after_one_pass(self) -> None:
        codex = QueuedCodex(codex_attempt())
        jev = QueuedJev(DecisionResult("ok", "accept", 4, 0))

        result = self.run_guarded(codex, jev, QueuedVerifier(self.verified))

        self.assertTrue(result.success)
        self.assertEqual(result.guard_status, "accepted")
        self.assertEqual(len(result.passes), 1)
        self.assertEqual(result.passes[0].jev_choice, "accept")
        self.assertIsNotNone(result.started_at)

    def test_hybrid_selects_strategy_then_accepts_verified_pass(self) -> None:
        codex = QueuedCodex(codex_attempt())
        jev = QueuedJev(
            DecisionResult("ok", "inspect_then_edit_test", 4, 0),
            DecisionResult("ok", "accept", 4, 0),
        )

        result = self.run_hybrid(codex, jev, QueuedVerifier(self.verified))

        self.assertTrue(result.success)
        self.assertEqual(result.jev_calls, 2)
        self.assertEqual(result.jev_strategy_calls, 1)
        self.assertEqual(result.jev_guard_calls, 1)
        self.assertEqual(result.passes[0].jev_strategy_choices, ("inspect_then_edit_test",))
        self.assertEqual(result.passes[0].jev_guard_choice, "accept")
        self.assertIn("Inspect the relevant file first", codex.prompts[0])

    def test_hybrid_selects_new_strategy_before_retry(self) -> None:
        codex = QueuedCodex(codex_attempt(), codex_attempt())
        jev = QueuedJev(
            DecisionResult("ok", "edit_then_test", 4, 0),
            DecisionResult("ok", "test_only", 4, 0),
            DecisionResult("ok", "accept", 4, 0),
        )
        failed = VerificationResult(False, "tests_failed", "exit_1", ("value.py",), 2, 1)

        result = self.run_hybrid(codex, jev, QueuedVerifier(failed, self.verified))

        self.assertTrue(result.success)
        self.assertEqual(result.jev_strategy_calls, 2)
        self.assertEqual(result.jev_guard_calls, 1)
        self.assertEqual(
            [item.jev_strategy_choices for item in result.passes],
            [("edit_then_test",), ("test_only",)],
        )
        self.assertEqual([item.jev_guard_choice for item in result.passes], [None, "accept"])
        self.assertIn(RETRY_INSTRUCTIONS["retry_tests"], codex.prompts[1])

    def test_hybrid_strategy_outage_fails_before_astra(self) -> None:
        codex = QueuedCodex(codex_attempt())
        jev = QueuedJev(DecisionResult("unavailable", error_code="timeout"))

        result = self.run_hybrid(codex, jev, QueuedVerifier(self.verified))

        self.assertFalse(result.success)
        self.assertEqual(result.guard_status, "not_checked_by_jev")
        self.assertEqual(result.jev_strategy_calls, 1)
        self.assertEqual(result.jev_guard_calls, 0)
        self.assertEqual(codex.prompts, [])

    def test_hybrid_guard_outage_fails_after_verified_astra_pass(self) -> None:
        codex = QueuedCodex(codex_attempt())
        jev = QueuedJev(
            DecisionResult("ok", "edit_then_test", 4, 0),
            DecisionResult("unavailable", error_code="timeout"),
        )

        result = self.run_hybrid(codex, jev, QueuedVerifier(self.verified))

        self.assertFalse(result.success)
        self.assertEqual(result.guard_status, "not_checked_by_jev")
        self.assertEqual(result.jev_strategy_calls, 1)
        self.assertEqual(result.jev_guard_calls, 1)
        self.assertEqual(len(result.passes), 1)

    def test_jev_retry_runs_second_astra_pass_with_reason(self) -> None:
        codex = QueuedCodex(codex_attempt(), codex_attempt())
        jev = QueuedJev(
            DecisionResult("ok", "retry_scope", 4, 0),
            DecisionResult("ok", "accept", 4, 0),
        )

        result = self.run_guarded(codex, jev, QueuedVerifier(self.verified, self.verified))

        self.assertTrue(result.success)
        self.assertEqual(result.retries, 1)
        self.assertEqual(result.astra_input_tokens, 20)
        self.assertEqual([item.jev_choice for item in result.passes], ["retry_scope", "accept"])
        self.assertIn("Reduce the change to the declared scope and preserve passing tests.", codex.prompts[1])
        self.assertIn("Do the task", codex.prompts[1])

    def test_failed_verifier_retries_without_calling_jev(self) -> None:
        codex = QueuedCodex(codex_attempt(), codex_attempt())
        jev = QueuedJev(DecisionResult("ok", "accept", 4, 0))
        failed = VerificationResult(False, "tests_failed", "exit_1", ("value.py",), 2, 1)

        result = self.run_guarded(codex, jev, QueuedVerifier(failed, self.verified))

        self.assertTrue(result.success)
        self.assertEqual(jev.calls, 1)
        self.assertEqual(result.passes[0].jev_choice, "retry_tests")
        self.assertEqual(result.passes[1].jev_choice, "accept")

    def test_unknown_failed_verifier_status_cannot_be_accepted_by_jev(self) -> None:
        codex = QueuedCodex(codex_attempt(), codex_attempt())
        jev = QueuedJev(DecisionResult("ok", "accept", 4, 0))
        failed = VerificationResult(False, "custom_failure", "broken", ("value.py",), 2, 1)

        result = self.run_guarded(codex, jev, QueuedVerifier(failed, self.verified))

        self.assertTrue(result.success)
        self.assertEqual(jev.calls, 1)
        self.assertEqual(result.passes[0].jev_choice, "retry_tests")

    def test_retry_limit_marks_attempt_failed(self) -> None:
        codex = QueuedCodex(codex_attempt(), codex_attempt())
        jev = QueuedJev(
            DecisionResult("ok", "retry_scope", 4, 0),
            DecisionResult("ok", "retry_simplify", 4, 0),
        )

        result = self.run_guarded(codex, jev, QueuedVerifier(self.verified, self.verified))

        self.assertFalse(result.success)
        self.assertEqual(result.guard_status, "retry_limit")
        self.assertEqual(len(result.passes), 2)

    def test_reject_stops_without_retry(self) -> None:
        codex = QueuedCodex(codex_attempt())
        jev = QueuedJev(DecisionResult("ok", "reject", 4, 0))

        result = self.run_guarded(codex, jev, QueuedVerifier(self.verified))

        self.assertFalse(result.success)
        self.assertEqual(result.guard_status, "rejected")
        self.assertEqual(len(codex.prompts), 1)

    def test_fail_closed_marks_jev_outage_unsuccessful(self) -> None:
        codex = QueuedCodex(codex_attempt())
        jev = QueuedJev(DecisionResult("unavailable", error_code="timeout"))

        result = self.run_guarded(codex, jev, QueuedVerifier(self.verified))

        self.assertFalse(result.success)
        self.assertEqual(result.guard_status, "not_checked_by_jev")
        self.assertEqual(result.verification_status, "not_checked_by_jev")

    def test_deterministic_fallback_accepts_verified_result_during_outage(self) -> None:
        codex = QueuedCodex(codex_attempt())
        jev = QueuedJev(DecisionResult("unavailable", error_code="timeout"))

        result = self.run_guarded(
            codex,
            jev,
            QueuedVerifier(self.verified),
            outage_policy="deterministic_fallback",
        )

        self.assertTrue(result.success)
        self.assertEqual(result.guard_status, "deterministic_fallback")

    def test_missing_change_retries_even_when_declared_tests_pass(self) -> None:
        codex = QueuedCodex(codex_attempt(), codex_attempt())
        jev = QueuedJev(DecisionResult("ok", "accept", 4, 0))
        unchanged = VerificationResult(True, "verified", None, (), 0, 0)

        result = self.run_guarded(codex, jev, QueuedVerifier(unchanged, self.verified))

        self.assertTrue(result.success)
        self.assertEqual(jev.calls, 1)
        self.assertEqual(result.passes[0].jev_choice, "retry_missing_change")


if __name__ == "__main__":
    unittest.main()
