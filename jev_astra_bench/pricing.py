from __future__ import annotations

import tomllib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal

from .model import AttemptRecord


@dataclass(slots=True, frozen=True)
class Pricing:
    astra_input_usd_per_million: Decimal | None = None
    astra_output_usd_per_million: Decimal | None = None
    jev_input_usd_per_million: Decimal | None = None
    extra_services_usd: Decimal | None = None
    pricing_source: str | None = None
    pricing_date: str | None = None
    astra_cached_input_usd_per_million: Decimal | None = None
    astra_cache_write_usd_per_million: Decimal | None = None

    @classmethod
    def from_toml(cls, path: Path) -> "Pricing":
        with path.open("rb") as handle:
            data = tomllib.load(handle)
        def decimal(name: str) -> Decimal | None:
            value = data.get(name)
            return None if value in (None, "", 0, 0.0, "0", "0.0") else Decimal(str(value))
        return cls(
            astra_input_usd_per_million=decimal("astra_input_usd_per_million"),
            astra_output_usd_per_million=decimal("astra_output_usd_per_million"),
            jev_input_usd_per_million=decimal("jev_input_usd_per_million"),
            extra_services_usd=decimal("extra_services_usd"),
            pricing_source=data.get("pricing_source"),
            pricing_date=data.get("pricing_date"),
            astra_cached_input_usd_per_million=decimal("astra_cached_input_usd_per_million"),
            astra_cache_write_usd_per_million=decimal("astra_cache_write_usd_per_million"),
        )


@dataclass(slots=True, frozen=True)
class CostEstimate:
    amount_usd: Decimal | None
    status: Literal["calculated", "partial", "unavailable"]
    missing_components: tuple[str, ...] = ()


def _token_cost(tokens: int | None, price: Decimal | None) -> Decimal | None:
    if tokens is None or price is None:
        return None
    return Decimal(tokens) * price / Decimal(1_000_000)


def estimate_cost(record: AttemptRecord, pricing: Pricing) -> CostEstimate:
    cache_pricing_present = (
        pricing.astra_cached_input_usd_per_million is not None
        or pricing.astra_cache_write_usd_per_million is not None
    )
    if cache_pricing_present:
        if record.astra_input_tokens is None:
            uncached_input_tokens = None
        elif record.astra_cached_input_tokens is None or record.astra_cache_write_input_tokens is None:
            uncached_input_tokens = None
        else:
            uncached_input_tokens = (
                record.astra_input_tokens
                - record.astra_cached_input_tokens
                - record.astra_cache_write_input_tokens
            )
            if uncached_input_tokens < 0:
                return CostEstimate(None, "unavailable", ("astra_input_breakdown",))
    else:
        uncached_input_tokens = record.astra_input_tokens

    components = {
        "astra_input": _token_cost(uncached_input_tokens, pricing.astra_input_usd_per_million),
        "astra_cached_input": (
            _token_cost(record.astra_cached_input_tokens, pricing.astra_cached_input_usd_per_million)
            if cache_pricing_present
            else Decimal(0)
        ),
        "astra_cache_write": (
            _token_cost(record.astra_cache_write_input_tokens, pricing.astra_cache_write_usd_per_million)
            if cache_pricing_present
            else Decimal(0)
        ),
        "astra_output": _token_cost(record.astra_output_tokens, pricing.astra_output_usd_per_million),
        "jev_input": (
            Decimal(0)
            if record.jev_calls == 0
            else _token_cost(record.jev_input_tokens, pricing.jev_input_usd_per_million)
        ),
        "extra_services": pricing.extra_services_usd if pricing.extra_services_usd is not None else Decimal(0),
    }
    required = {
        "astra_input": uncached_input_tokens is not None,
        "astra_cached_input": not cache_pricing_present or record.astra_cached_input_tokens is not None,
        "astra_cache_write": not cache_pricing_present or record.astra_cache_write_input_tokens is not None,
        "astra_output": record.astra_output_tokens is not None,
        "jev_input": record.jev_calls == 0 or record.jev_input_tokens is not None,
    }
    missing = tuple(name for name, present in required.items() if not present or components[name] is None)
    if missing:
        return CostEstimate(None, "unavailable", missing)
    return CostEstimate(sum(components.values(), Decimal(0)), "calculated")
