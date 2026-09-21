from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable


@dataclass(slots=True, frozen=True)
class ParsedCodexEvents:
    final_text: str | None
    input_tokens: int | None
    output_tokens: int | None
    tool_calls: int
    malformed_events: int
    completed: bool
    cached_input_tokens: int | None = None
    cache_write_input_tokens: int | None = None


def _walk(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _first_int(mapping: dict, keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def parse_codex_events(lines: Iterable[str]) -> ParsedCodexEvents:
    final_text: str | None = None
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_write_input_tokens: int | None = None
    output_tokens: int | None = None
    tool_calls = 0
    malformed = 0
    completed = False
    for line in lines:
        try:
            event = json.loads(line)
        except (TypeError, json.JSONDecodeError):
            malformed += 1
            continue
        if not isinstance(event, dict):
            malformed += 1
            continue
        if event.get("type") == "turn.completed":
            completed = True
        for item in _walk(event):
            item_type = item.get("type")
            if item_type in {"command_execution", "mcp_tool_call", "tool_call", "web_search_call"}:
                tool_calls += 1
            if item_type in {"agent_message", "assistant_message", "message"}:
                text = item.get("text")
                if isinstance(text, str) and text:
                    final_text = text
            usage = item.get("usage")
            if isinstance(usage, dict):
                current_input = _first_int(usage, ("input_tokens", "prompt_tokens", "input"))
                current_cached = _first_int(usage, ("cached_input_tokens",))
                current_cache_write = _first_int(usage, ("cache_write_input_tokens",))
                current_output = _first_int(usage, ("output_tokens", "completion_tokens", "output"))
                if current_input is not None:
                    input_tokens = current_input
                if current_cached is not None:
                    cached_input_tokens = current_cached
                if current_cache_write is not None:
                    cache_write_input_tokens = current_cache_write
                if current_output is not None:
                    output_tokens = current_output
    return ParsedCodexEvents(
        final_text,
        input_tokens,
        output_tokens,
        tool_calls,
        malformed,
        completed,
        cached_input_tokens,
        cache_write_input_tokens,
    )
