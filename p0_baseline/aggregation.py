"""Pure aggregation of P0 check outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import BaselineStatus, CheckResult, CheckStatus, ResultSummary


@dataclass(frozen=True)
class AcceptanceGates:
    clean_checkout: bool = False
    offline: bool = False
    evidence_complete: bool = False
    requirement_coverage_complete: bool = False
    supported_environment: bool = False
    credentials_absent: bool = False
    scope_compliant: bool = False


@dataclass(frozen=True)
class AggregationResult:
    overall_status: BaselineStatus
    summary: ResultSummary
    acceptance_eligible: bool
    exit_code: int


def aggregate(
    checks: Iterable[CheckResult],
    gates: AcceptanceGates,
    determinate_failure: bool = False,
) -> AggregationResult:
    """Aggregate required check observations into the P0 three-state result."""

    observed = tuple(checks)
    summary = ResultSummary.from_checks(observed)
    required = tuple(item for item in observed if item.required)
    has_failure = any(
        item.status in {CheckStatus.FAILED, CheckStatus.ERROR}
        for item in required
    ) or determinate_failure
    all_gates_pass = all(
        getattr(gates, name) for name in gates.__dataclass_fields__
    )
    success = bool(required) and all(
        item.status is CheckStatus.PASSED for item in required
    ) and all_gates_pass and not determinate_failure
    status = (
        BaselineStatus.FAILURE
        if has_failure
        else BaselineStatus.SUCCESS
        if success
        else BaselineStatus.INCOMPLETE
    )
    return AggregationResult(
        overall_status=status,
        summary=summary,
        acceptance_eligible=status is BaselineStatus.SUCCESS,
        exit_code={
            BaselineStatus.SUCCESS: 0,
            BaselineStatus.FAILURE: 1,
            BaselineStatus.INCOMPLETE: 2,
        }[status],
    )
