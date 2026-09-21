from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from jev_astra_bench.codex_events import parse_codex_events


class CodexEventTests(unittest.TestCase):
    def test_parses_message_usage_and_tool_calls(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "codex-events.jsonl"
        parsed = parse_codex_events(fixture.read_text(encoding="utf-8").splitlines())
        self.assertEqual(parsed.final_text, "Готово")
        self.assertEqual(parsed.input_tokens, 120)
        self.assertEqual(parsed.cached_input_tokens, 30)
        self.assertEqual(parsed.cache_write_input_tokens, 5)
        self.assertEqual(parsed.output_tokens, 80)
        self.assertEqual(parsed.tool_calls, 1)
        self.assertTrue(parsed.completed)

    def test_malformed_and_missing_usage_are_explicit(self) -> None:
        parsed = parse_codex_events(["not json", json.dumps({"type": "turn.completed"})])
        self.assertEqual(parsed.malformed_events, 1)
        self.assertIsNone(parsed.input_tokens)
        self.assertIsNone(parsed.cached_input_tokens)
        self.assertIsNone(parsed.cache_write_input_tokens)
        self.assertIsNone(parsed.output_tokens)

    def test_later_partial_usage_does_not_erase_cache_counts(self) -> None:
        parsed = parse_codex_events(
            [
                json.dumps(
                    {
                        "usage": {
                            "input_tokens": 100,
                            "cached_input_tokens": 40,
                            "cache_write_input_tokens": 10,
                        }
                    }
                ),
                json.dumps({"usage": {"input_tokens": 120, "output_tokens": 20}}),
            ]
        )

        self.assertEqual(parsed.input_tokens, 120)
        self.assertEqual(parsed.cached_input_tokens, 40)
        self.assertEqual(parsed.cache_write_input_tokens, 10)
        self.assertEqual(parsed.output_tokens, 20)


if __name__ == "__main__":
    unittest.main()
