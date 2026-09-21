from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from .model import DecisionResult
from .redaction import redact_state


class JevTransport(Protocol):
    def request(self, payload: Mapping[str, object]) -> Mapping[str, object]: ...


class JevHttpError(Exception):
    def __init__(self, status: int, message: str = "") -> None:
        super().__init__(message or f"Jev HTTP {status}")
        self.status = status


@dataclass(slots=True, frozen=True)
class JevConfig:
    endpoint: str = "https://api.typesafe.ai/v1/systemone"
    model: str = "jev-1.13.0"
    timeout_s: float = 10.0
    max_retries: int = 1
    api_key_env: str = "TYPESAFE_API_KEY"


def build_payload(
    question: str,
    state: Mapping[str, object],
    allowed_choices: Sequence[str],
    *,
    model: str,
) -> dict[str, object]:
    return {
        "model": model,
        "state": redact_state(dict(state)),
        "questions": {
            "choice": {
                "type": "choice",
                "instructions": question,
                "criteria": {choice: None for choice in allowed_choices},
            }
        },
    }


def parse_decision(payload: Mapping[str, object], allowed_choices: Sequence[str]) -> DecisionResult:
    answers = payload.get("answers")
    answer = answers.get("choice") if isinstance(answers, Mapping) else None
    if not isinstance(answer, Mapping) or answer.get("type") != "choice":
        return DecisionResult("invalid_response", error_code="choice_answer_missing")
    choice = answer.get("choice")
    if not isinstance(choice, str) or choice not in allowed_choices:
        return DecisionResult("invalid_response", error_code="choice_not_allowed")
    usage = payload.get("usage")
    input_tokens = output_tokens = None
    if isinstance(usage, Mapping):
        if isinstance(usage.get("input_tokens"), int):
            input_tokens = usage["input_tokens"]
        if isinstance(usage.get("output_tokens"), int):
            output_tokens = usage["output_tokens"]
    return DecisionResult("ok", choice, input_tokens, output_tokens)


class UrllibJevTransport:
    def __init__(self, config: JevConfig) -> None:
        self.config = config

    def request(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        api_key = os.environ.get(self.config.api_key_env)
        if not api_key:
            raise JevHttpError(0, "missing_api_key")
        request = urllib.request.Request(
            self.config.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_s) as response:
                decoded = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise JevHttpError(error.code) from error
        except (urllib.error.URLError, TimeoutError, socket.timeout) as error:
            raise JevHttpError(0, "transport_error") from error
        if not isinstance(decoded, Mapping):
            raise JevHttpError(0, "response_not_object")
        return decoded


class JevClient:
    def __init__(self, config: JevConfig, transport: JevTransport | None = None) -> None:
        self.config = config
        self.transport = transport or UrllibJevTransport(config)

    def decide(
        self,
        question: str,
        state: Mapping[str, object],
        allowed_choices: Sequence[str],
    ) -> DecisionResult:
        if not allowed_choices:
            return DecisionResult("invalid_response", error_code="empty_allow_list")
        payload = build_payload(question, state, allowed_choices, model=self.config.model)
        attempts = 0
        while True:
            try:
                response = self.transport.request(payload)
                return parse_decision(response, allowed_choices)
            except JevHttpError as error:
                retryable = error.status in {429, 529, 0} and str(error) != "missing_api_key"
                if retryable and attempts < self.config.max_retries:
                    attempts += 1
                    time.sleep(min(0.25 * attempts, 1.0))
                    continue
                code = f"http_{error.status}" if error.status else str(error)
                return DecisionResult("unavailable", error_code=code)
            except (ValueError, TypeError, json.JSONDecodeError):
                return DecisionResult("invalid_response", error_code="malformed_response")
