from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from statistics import mean, median
from typing import Iterable

from .model import AttemptRecord


@dataclass(slots=True, frozen=True)
class PairSummary:
    task_id: str
    mode: str
    attempts: int
    successful_tasks: int
    mean_duration_s: float | None
    median_duration_s: float | None
    total_cost_usd: Decimal | None
    mean_attempt_cost_usd: Decimal | None
    cost_per_success_usd: Decimal | None


def aggregate_pairs(records: Iterable[AttemptRecord]) -> list[PairSummary]:
    groups: dict[tuple[str, str], list[AttemptRecord]] = defaultdict(list)
    for record in records:
        groups[(record.task_id, record.mode)].append(record)
    result: list[PairSummary] = []
    for (task_id, mode), items in sorted(groups.items()):
        durations = [item.duration_s for item in items if item.duration_s is not None]
        costs = [Decimal(item.estimated_cost_usd) for item in items if item.estimated_cost_usd is not None]
        total_cost = sum(costs, Decimal(0)) if len(costs) == len(items) else None
        successes = sum(1 for item in items if item.success)
        result.append(
            PairSummary(
                task_id=task_id,
                mode=mode,
                attempts=len(items),
                successful_tasks=successes,
                mean_duration_s=mean(durations) if durations else None,
                median_duration_s=median(durations) if durations else None,
                total_cost_usd=total_cost,
                mean_attempt_cost_usd=(total_cost / len(items)) if total_cost is not None else None,
                cost_per_success_usd=(total_cost / successes) if total_cost is not None and successes else None,
            )
        )
    return result
