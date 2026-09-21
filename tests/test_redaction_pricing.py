from __future__ import annotations

import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from jev_astra_bench.aggregate import aggregate_pairs
from jev_astra_bench.model import AttemptRecord
from jev_astra_bench.pricing import Pricing, estimate_cost
from jev_astra_bench.redaction import redact_state


def _record(*, success: bool, cost: str | None = None) -> AttemptRecord:
    return AttemptRecord(
        task_id="code-001",
        mode="astra_only",
        repeat=1,
        duration_s=1.0,
        astra_input_tokens=100,
        astra_cached_input_tokens=0,
        astra_cache_write_input_tokens=0,
        astra_output_tokens=100,
        success=success,
        estimated_cost_usd=cost,
        cost_status="calculated" if cost else "unavailable",
    )


class RedactionPricingTests(unittest.TestCase):
    def test_redaction_removes_credentials_and_local_paths(self) -> None:
        result = redact_state({"api_key": "hidden", "cookie": "hidden", "path": r"C:\private\x", "text": "keep"})
        self.assertEqual(result, {"text": "keep"})

    def test_cost_per_success_uses_all_attempt_costs(self) -> None:
        summary = aggregate_pairs([_record(success=True, cost="1.00"), _record(success=False, cost="2.00")])[0]
        self.assertEqual(summary.cost_per_success_usd, Decimal("3.00"))

    def test_missing_usage_is_not_converted_to_zero(self) -> None:
        record = _record(success=True)
        record.astra_cached_input_tokens = None
        pricing = Pricing(
            astra_input_usd_per_million=Decimal("1"),
            astra_output_usd_per_million=Decimal("1"),
            jev_input_usd_per_million=Decimal("1"),
            extra_services_usd=Decimal("0"),
            astra_cached_input_usd_per_million=Decimal("0.1"),
            astra_cache_write_usd_per_million=Decimal("1.25"),
        )
        estimate = estimate_cost(record, pricing)
        self.assertEqual(estimate.status, "unavailable")
        self.assertIsNone(estimate.amount_usd)

    def test_astra_only_costs_cache_without_requiring_jev_usage(self) -> None:
        record = _record(success=True)
        record.astra_input_tokens = 100
        record.astra_cached_input_tokens = 20
        record.astra_cache_write_input_tokens = 10
        record.astra_output_tokens = 50
        pricing = Pricing(
            astra_input_usd_per_million=Decimal("10"),
            astra_output_usd_per_million=Decimal("50"),
            jev_input_usd_per_million=Decimal("0.042"),
            extra_services_usd=Decimal("0"),
            astra_cached_input_usd_per_million=Decimal("1"),
            astra_cache_write_usd_per_million=Decimal("12.5"),
        )

        estimate = estimate_cost(record, pricing)

        self.assertEqual(estimate.status, "calculated")
        self.assertEqual(estimate.amount_usd, Decimal("0.003345"))

    def test_pricing_loads_toml(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pricing.toml"
            path.write_text(
                'astra_input_usd_per_million = 1.5\n'
                'astra_cached_input_usd_per_million = 0.15\n'
                'astra_cache_write_usd_per_million = 1.875\n'
                'pricing_source = "test"\n',
                encoding="utf-8",
            )
            pricing = Pricing.from_toml(path)
        self.assertEqual(pricing.astra_input_usd_per_million, Decimal("1.5"))
        self.assertEqual(pricing.astra_cached_input_usd_per_million, Decimal("0.15"))
        self.assertEqual(pricing.astra_cache_write_usd_per_million, Decimal("1.875"))
        self.assertEqual(pricing.pricing_source, "test")


if __name__ == "__main__":
    unittest.main()
