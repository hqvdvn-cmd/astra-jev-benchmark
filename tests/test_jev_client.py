from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from jev_astra_bench.jev_client import JevClient, JevConfig, JevHttpError, build_payload


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, payload):
        self.calls.append(payload)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class JevClientTests(unittest.TestCase):
    def test_valid_choice_is_returned_and_state_is_redacted(self) -> None:
        transport = FakeTransport({"answers": {"choice": {"type": "choice", "choice": "click:submit"}}, "usage": {"input_tokens": 4, "output_tokens": 0}})
        client = JevClient(JevConfig(max_retries=0), transport)
        result = client.decide("Choose", {"api_key": "hidden", "page": "ready"}, ["click:submit", "stop:done"])
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.choice, "click:submit")
        self.assertNotIn("api_key", transport.calls[0]["state"])

    def test_out_of_allow_list_is_invalid(self) -> None:
        client = JevClient(JevConfig(max_retries=0), FakeTransport({"answers": {"choice": {"type": "choice", "choice": "rm:-rf"}}}))
        result = client.decide("Choose", {}, ["stop:done"])
        self.assertEqual(result.status, "invalid_response")
        self.assertEqual(result.error_code, "choice_not_allowed")

    def test_auth_and_validation_errors_do_not_retry(self) -> None:
        transport = FakeTransport(JevHttpError(401))
        result = JevClient(JevConfig(max_retries=2), transport).decide("Choose", {}, ["stop:done"])
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(len(transport.calls), 1)

    def test_rate_limit_retries_once_then_marks_unavailable(self) -> None:
        transport = FakeTransport(JevHttpError(529), JevHttpError(529))
        result = JevClient(JevConfig(max_retries=1), transport).decide("Choose", {}, ["stop:done"])
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(len(transport.calls), 2)

    def test_payload_has_typed_question_and_finite_choices(self) -> None:
        payload = build_payload("Choose", {"safe": True}, ["a", "b"], model="jev-test")
        self.assertEqual(payload["model"], "jev-test")
        self.assertEqual(payload["questions"]["choice"]["type"], "choice")
        self.assertEqual(payload["questions"]["choice"]["instructions"], "Choose")
        self.assertEqual(payload["questions"]["choice"]["criteria"], {"a": None, "b": None})


if __name__ == "__main__":
    unittest.main()
