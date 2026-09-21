from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import unittest

from jev_astra_bench.model import AttemptRecord, DecisionResult, PassRecord, TaskSpec


class ModelTests(unittest.TestCase):
    def test_attempt_record_serializes_optional_values_without_secrets(self) -> None:
        record = AttemptRecord(task_id="code-001", mode="astra_only", repeat=1)
        payload = record.to_public_dict()
        self.assertEqual(payload["task_id"], "code-001")
        self.assertIsNone(payload["jev_input_tokens"])
        self.assertNotIn("raw_response", payload)

    def test_task_spec_and_decision_result_are_typed_values(self) -> None:
        task = TaskSpec("browser-001", "browser", "Do it", Path("fixture"), "browser")
        decision = DecisionResult("ok", "click:submit")
        self.assertEqual(task.kind, "browser")
        self.assertEqual(decision.choice, "click:submit")

    def test_attempt_record_round_trips_guard_passes(self) -> None:
        original = AttemptRecord(
            "t",
            "astra_jev_guarded",
            1,
            passes=[
                PassRecord(
                    pass_number=1,
                    trigger="initial",
                    duration_s=0.5,
                    astra_input_tokens=10,
                    astra_cached_input_tokens=2,
                    astra_cache_write_input_tokens=0,
                    astra_output_tokens=3,
                    jev_input_tokens=4,
                    jev_output_tokens=0,
                    tool_calls=1,
                    verification_status="verified",
                    failure_reason=None,
                    changed_files=("value.py",),
                    added_lines=2,
                    deleted_lines=1,
                    jev_choice="accept",
                )
            ],
            guard_status="accepted",
            max_astra_passes=2,
        )

        restored = AttemptRecord.from_public_dict(original.to_public_dict())

        self.assertEqual(restored, original)
        self.assertIsInstance(restored.passes[0], PassRecord)

    def test_old_record_without_passes_remains_readable(self) -> None:
        restored = AttemptRecord.from_public_dict({"task_id": "t", "mode": "astra_only", "repeat": 1})

        self.assertEqual(restored.passes, [])

    def test_hybrid_decisions_round_trip_as_bounded_evidence(self) -> None:
        original = AttemptRecord(
            task_id="t",
            mode="astra_jev_offload_guarded",
            repeat=1,
            jev_strategy_choices=["inspect_then_edit_test"],
            jev_strategy_calls=1,
            jev_guard_calls=1,
            passes=[
                PassRecord(
                    pass_number=1,
                    trigger="initial",
                    duration_s=0.5,
                    astra_input_tokens=10,
                    astra_cached_input_tokens=2,
                    astra_cache_write_input_tokens=0,
                    astra_output_tokens=3,
                    jev_input_tokens=8,
                    jev_output_tokens=0,
                    tool_calls=1,
                    verification_status="verified",
                    failure_reason=None,
                    changed_files=("value.py",),
                    added_lines=2,
                    deleted_lines=1,
                    jev_choice="accept",
                    jev_strategy_choices=("inspect_then_edit_test",),
                    jev_guard_choice="accept",
                    jev_strategy_calls=1,
                    jev_guard_calls=1,
                )
            ],
        )

        restored = AttemptRecord.from_public_dict(original.to_public_dict())

        self.assertEqual(restored, original)
        self.assertEqual(restored.passes[0].jev_strategy_choices, ("inspect_then_edit_test",))

    def test_old_record_defaults_hybrid_decision_fields(self) -> None:
        restored = AttemptRecord.from_public_dict({"task_id": "t", "mode": "astra_only", "repeat": 1})

        self.assertEqual(restored.jev_strategy_choices, [])
        self.assertEqual(restored.jev_strategy_calls, 0)
        self.assertEqual(restored.jev_guard_calls, 0)


if __name__ == "__main__":
    unittest.main()
