from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from jev_astra_bench.browser import BrowserResult, FakeBrowserAdapter
from jev_astra_bench.browser_runner import run_browser_attempt
from jev_astra_bench.codex_events import ParsedCodexEvents
from jev_astra_bench.codex_runner import CodexAttempt
from jev_astra_bench.guarded import GuardConfig
from jev_astra_bench.model import DecisionResult, TaskSpec
from jev_astra_bench.pricing import Pricing


class BrowserJev:
    def __init__(self):
        self.calls = 0

    def decide(self, question, state, choices):
        self.calls += 1
        choice = "click:submit" if "click:submit" in choices else "fill:email" if "fill:email" in choices else choices[0]
        return DecisionResult("ok", choice, 3, 0)


class ResultJev:
    def __init__(self, result: DecisionResult):
        self.result = result
        self.calls = 0

    def decide(self, question, state, choices):
        self.calls += 1
        return self.result


class TrackingBrowserAdapter(FakeBrowserAdapter):
    def __init__(self):
        super().__init__()
        self.resets = 0

    def reset(self) -> None:
        self.resets += 1
        super().reset()


class FailsFirstBrowserActionAdapter(TrackingBrowserAdapter):
    def __init__(self):
        super().__init__()
        self.failed = False

    def perform(self, choice):
        if not self.failed:
            self.failed = True
            return BrowserResult(False, self.snapshot().state, "temporary_failure")
        return super().perform(choice)


def astra_browser(prompt, workspace):
    if "Extract the email" in prompt:
        text = json.dumps({"value": "test@example.com"})
    elif "fill:email" in prompt and "email_filled=True" not in prompt:
        text = json.dumps({"choice": "fill:email", "value": "test@example.com"})
    else:
        text = json.dumps({"choice": "click:submit"})
    return CodexAttempt(ParsedCodexEvents(text, 10, 4, 0, 0, True), 0.01, 0, False, ("fake",))


class BrowserRunnerTests(unittest.TestCase):
    def setUp(self):
        self.task = TaskSpec("browser", "browser", "Use test@example.com", Path("."), "")

    def test_astra_only_reaches_factual_submitted_state(self):
        result = run_browser_attempt(self.task, "astra_only", 1, astra_browser, None, Pricing(), FakeBrowserAdapter())
        self.assertTrue(result.success)
        self.assertEqual(result.verification_status, "verified")
        self.assertEqual(result.jev_calls, 0)

    def test_offload_uses_astra_for_value_and_jev_for_actions(self):
        result = run_browser_attempt(self.task, "astra_jev_offload", 1, astra_browser, BrowserJev(), Pricing(), FakeBrowserAdapter())
        self.assertTrue(result.success)
        self.assertEqual(result.jev_calls, 2)
        self.assertEqual(result.astra_input_tokens, 10)

    def test_guarded_browser_accepts_submitted_state(self):
        jev = ResultJev(DecisionResult("ok", "accept", 3, 0))

        result = run_browser_attempt(
            self.task,
            "astra_jev_guarded",
            1,
            astra_browser,
            jev,
            Pricing(),
            FakeBrowserAdapter(),
            GuardConfig(),
        )

        self.assertTrue(result.success)
        self.assertEqual(result.guard_status, "accepted")
        self.assertEqual(len(result.passes), 1)
        self.assertEqual(result.passes[0].jev_choice, "accept")

    def test_hybrid_browser_offloads_actions_then_guards_submitted_state(self):
        jev = BrowserJev()

        result = run_browser_attempt(
            self.task,
            "astra_jev_offload_guarded",
            1,
            astra_browser,
            jev,
            Pricing(),
            FakeBrowserAdapter(),
            GuardConfig(),
        )

        self.assertTrue(result.success)
        self.assertEqual(jev.calls, 3)
        self.assertEqual(result.jev_strategy_calls, 2)
        self.assertEqual(result.jev_guard_calls, 1)
        self.assertEqual(result.passes[0].jev_strategy_choices, ("fill:email", "click:submit"))
        self.assertEqual(result.passes[0].jev_guard_choice, "accept")

    def test_hybrid_browser_resets_and_reselects_actions_on_retry(self):
        adapter = FailsFirstBrowserActionAdapter()
        jev = BrowserJev()

        result = run_browser_attempt(
            self.task,
            "astra_jev_offload_guarded",
            1,
            astra_browser,
            jev,
            Pricing(),
            adapter,
            GuardConfig(),
        )

        self.assertTrue(result.success)
        self.assertEqual(adapter.resets, 1)
        self.assertEqual(result.retries, 1)
        self.assertEqual(result.jev_strategy_calls, 3)
        self.assertEqual(result.jev_guard_calls, 1)
        self.assertEqual(
            [item.jev_strategy_choices for item in result.passes],
            [("fill:email",), ("fill:email", "click:submit")],
        )

    def test_guarded_browser_resets_and_retries_after_failed_first_pass(self):
        adapter = TrackingBrowserAdapter()
        responses = iter(
            [
                json.dumps({"choice": "wait:missing"}),
                json.dumps({"choice": "fill:email", "value": "test@example.com"}),
                json.dumps({"choice": "click:submit"}),
            ]
        )

        def queued_astra(prompt, workspace):
            return CodexAttempt(
                ParsedCodexEvents(next(responses), 10, 4, 0, 0, True, 2, 0),
                0.01,
                0,
                False,
                ("fake",),
            )

        result = run_browser_attempt(
            self.task,
            "astra_jev_guarded",
            1,
            queued_astra,
            ResultJev(DecisionResult("ok", "accept", 3, 0)),
            Pricing(),
            adapter,
            GuardConfig(),
        )

        self.assertTrue(result.success)
        self.assertEqual(result.retries, 1)
        self.assertEqual(adapter.resets, 1)
        self.assertEqual([item.jev_choice for item in result.passes], ["retry_tests", "accept"])

    def test_guarded_browser_outage_fails_closed(self):
        result = run_browser_attempt(
            self.task,
            "astra_jev_guarded",
            1,
            astra_browser,
            ResultJev(DecisionResult("unavailable", error_code="timeout")),
            Pricing(),
            FakeBrowserAdapter(),
            GuardConfig(),
        )

        self.assertFalse(result.success)
        self.assertEqual(result.guard_status, "not_checked_by_jev")


if __name__ == "__main__":
    unittest.main()
