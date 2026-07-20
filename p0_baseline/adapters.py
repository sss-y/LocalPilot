"""Controlled adapters that normalize check observations into contract results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic_ns
from types import MappingProxyType
from typing import Callable, Mapping, Protocol

from .check_worker import WorkerOutcome, WorkerRequest, WorkerResult
from .errors import ErrorCode
from .manifest import CheckDescriptor
from .models import CheckResult, CheckStatus, Diagnostic
from .safe_subprocess import SafeSubprocessError


WorkerExecutor = Callable[[WorkerRequest], WorkerResult | str | bytes]
InternalCheck = Callable[["VerificationContext", CheckDescriptor], CheckResult]


@dataclass(frozen=True)
class VerificationContext:
    repository_root: Path
    run_directory: Path
    worker_executor: WorkerExecutor

    def __post_init__(self) -> None:
        for value, name in (
            (self.repository_root, "repository_root"),
            (self.run_directory, "run_directory"),
        ):
            if not isinstance(value, Path) or not value.is_absolute():
                raise ValueError(f"{name} must be an absolute Path")
            if not value.is_dir():
                raise ValueError(f"{name} must identify an existing directory")
        if not callable(self.worker_executor):
            raise TypeError("worker_executor must be callable")


class Adapter(Protocol):
    def execute(self, context: VerificationContext, descriptor: CheckDescriptor) -> CheckResult: ...


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _diagnostic(
    code: ErrorCode,
    descriptor: CheckDescriptor,
    failure_type: str,
    *,
    message: str = "Required check did not produce a passing structured result.",
    details: Mapping[str, object] | None = None,
) -> Diagnostic:
    return Diagnostic(
        code=code,
        message=message,
        failure_type=failure_type,
        target=descriptor.check_id,
        recoverable=False,
        details=details,
    )


def not_run_result(descriptor: CheckDescriptor) -> CheckResult:
    """Build a required-check placeholder before an adapter has been started."""

    started_at = _timestamp()
    started_ns = monotonic_ns()
    return _result(
        descriptor,
        CheckStatus.NOT_RUN,
        started_at=started_at,
        started_ns=started_ns,
        diagnostics=(
            _diagnostic(
                ErrorCode.RESULT_MISSING,
                descriptor,
                "not_run",
                message="Required check was not started, so no result is available.",
            ),
        ),
    )


def _observed(worker: WorkerResult) -> Mapping[str, object]:
    statuses = sorted({item.status for item in worker.outcomes})
    return {
        "tests_run": worker.tests_run,
        "outcome_counts": {
            status: sum(item.status == status for item in worker.outcomes)
            for status in statuses
        },
    }


def _outcome_diagnostic(
    code: ErrorCode,
    descriptor: CheckDescriptor,
    failure_type: str,
    outcomes: tuple[WorkerOutcome, ...],
) -> Diagnostic:
    return _diagnostic(
        code,
        descriptor,
        failure_type,
        details={
            "test_ids": [item.test_id for item in outcomes],
        },
    )


def _result(
    descriptor: CheckDescriptor,
    status: CheckStatus,
    *,
    started_at: str,
    started_ns: int,
    diagnostics: tuple[Diagnostic, ...] = (),
    observed: Mapping[str, object] | None = None,
) -> CheckResult:
    return CheckResult(
        check_id=descriptor.check_id,
        title=descriptor.title,
        required=descriptor.required,
        requirement_ids=descriptor.requirement_ids,
        status=status,
        started_at=started_at,
        finished_at=_timestamp(),
        duration_ms=max(0, (monotonic_ns() - started_ns) // 1_000_000),
        target=descriptor.check_id,
        diagnostics=diagnostics,
        evidence_refs=(),
        observed=observed,
    )


class UnittestAdapter:
    name = "unittest"

    @staticmethod
    def result_for_status(descriptor: CheckDescriptor, status: CheckStatus) -> CheckResult:
        started_at = _timestamp()
        started_ns = monotonic_ns()
        diagnostics: tuple[Diagnostic, ...] = ()
        if status is CheckStatus.FAILED:
            diagnostics = (_diagnostic(ErrorCode.CHECK_FAILED, descriptor, "assertion"),)
        elif status is CheckStatus.ERROR:
            diagnostics = (_diagnostic(ErrorCode.CHECK_ERROR, descriptor, "worker"),)
        elif status is CheckStatus.SKIPPED:
            diagnostics = (_diagnostic(ErrorCode.CHECK_SKIPPED, descriptor, "skip"),)
        elif status is CheckStatus.NOT_RUN:
            diagnostics = (_diagnostic(ErrorCode.RESULT_MISSING, descriptor, "not_run"),)
        elif status is CheckStatus.INTERRUPTED:
            diagnostics = (
                _diagnostic(ErrorCode.CHECK_INTERRUPTED, descriptor, "interrupted"),
            )
        return _result(
            descriptor,
            status,
            started_at=started_at,
            started_ns=started_ns,
            diagnostics=diagnostics,
        )

    def execute(self, context: VerificationContext, descriptor: CheckDescriptor) -> CheckResult:
        started_at = _timestamp()
        started_ns = monotonic_ns()
        try:
            if descriptor.adapter != self.name:
                raise ValueError("descriptor adapter mismatch")
            request = WorkerRequest("1.0.0", descriptor.test_ids)
            worker_output = context.worker_executor(request)
            worker = (
                worker_output
                if isinstance(worker_output, WorkerResult)
                else WorkerResult.from_json(worker_output)
            )
            outcome_ids = tuple(item.test_id for item in worker.outcomes)
            observed = _observed(worker)
            if worker.tests_run != len(descriptor.test_ids) or outcome_ids != descriptor.test_ids:
                return _result(
                    descriptor,
                    CheckStatus.ERROR,
                    started_at=started_at,
                    started_ns=started_ns,
                    diagnostics=(
                        _diagnostic(
                            ErrorCode.CHECK_ERROR,
                            descriptor,
                            "result_integrity",
                            message="Worker result does not cover the exact requested test IDs.",
                        ),
                    ),
                    observed=observed,
                )

            network_violations = tuple(
                item for item in worker.outcomes if item.failure_type == "network_policy"
            )
            ordinary_failures = tuple(
                item
                for item in worker.outcomes
                if item.status == "failed" and item.failure_type != "network_policy"
            )
            worker_errors = tuple(item for item in worker.outcomes if item.status == "error")
            unexpected_successes = tuple(
                item for item in worker.outcomes if item.status == "unexpected_success"
            )
            incomplete_outcomes = tuple(
                item
                for item in worker.outcomes
                if item.status in {"skipped", "expected_failure"}
            )
            network_diagnostics = tuple(
                Diagnostic(
                    code=ErrorCode.NETWORK_POLICY_VIOLATION,
                    message="Offline network policy blocked an attempted connection.",
                    failure_type="network_policy",
                    target=item.target_summary or "<opaque-host>",
                    recoverable=False,
                    details={
                        "test_id": item.test_id,
                        "operation": item.operation,
                        "source": item.source,
                    },
                )
                for item in network_violations
            )
            error_diagnostics: tuple[Diagnostic, ...] = ()
            if worker_errors:
                error_diagnostics += (
                    _outcome_diagnostic(
                        ErrorCode.CHECK_ERROR, descriptor, "worker", worker_errors
                    ),
                )
            if unexpected_successes:
                error_diagnostics += (
                    _outcome_diagnostic(
                        ErrorCode.CHECK_ERROR,
                        descriptor,
                        "test_classification",
                        unexpected_successes,
                    ),
                )
            failure_diagnostics: tuple[Diagnostic, ...] = network_diagnostics
            if ordinary_failures:
                failure_diagnostics += (
                    _outcome_diagnostic(
                        ErrorCode.CHECK_FAILED,
                        descriptor,
                        "assertion",
                        ordinary_failures,
                    ),
                )
            incomplete_diagnostics: tuple[Diagnostic, ...] = ()
            if incomplete_outcomes:
                incomplete_diagnostics = (
                    _outcome_diagnostic(
                        ErrorCode.CHECK_SKIPPED,
                        descriptor,
                        "skip",
                        incomplete_outcomes,
                    ),
                )

            if error_diagnostics:
                status = CheckStatus.ERROR
                diagnostics = error_diagnostics + failure_diagnostics + incomplete_diagnostics
            elif failure_diagnostics:
                status = CheckStatus.FAILED
                diagnostics = failure_diagnostics + incomplete_diagnostics
            elif incomplete_diagnostics:
                status = CheckStatus.SKIPPED
                diagnostics = incomplete_diagnostics
            else:
                status = CheckStatus.PASSED
                diagnostics = ()
            return _result(
                descriptor,
                status,
                started_at=started_at,
                started_ns=started_ns,
                diagnostics=diagnostics,
                observed=observed,
            )
        except SafeSubprocessError as exc:
            if exc.reason == "P0_WORKER_TIMEOUT":
                return _result(
                    descriptor,
                    CheckStatus.INTERRUPTED,
                    started_at=started_at,
                    started_ns=started_ns,
                    diagnostics=(
                        _diagnostic(
                            ErrorCode.CHECK_INTERRUPTED,
                            descriptor,
                            "interrupted",
                        ),
                    ),
                )
            return _result(
                descriptor,
                CheckStatus.ERROR,
                started_at=started_at,
                started_ns=started_ns,
                diagnostics=(_diagnostic(ErrorCode.CHECK_ERROR, descriptor, "worker"),),
            )
        except Exception:
            return _result(
                descriptor,
                CheckStatus.ERROR,
                started_at=started_at,
                started_ns=started_ns,
                diagnostics=(_diagnostic(ErrorCode.CHECK_ERROR, descriptor, "worker"),),
            )


class InternalAdapter:
    name = "internal"

    def __init__(self, checks: Mapping[str, InternalCheck]) -> None:
        if not isinstance(checks, Mapping) or any(
            type(key) is not str or not callable(value) for key, value in checks.items()
        ):
            raise TypeError("internal checks must be an explicit name-to-callable mapping")
        self._checks = MappingProxyType(dict(checks))

    def execute(self, context: VerificationContext, descriptor: CheckDescriptor) -> CheckResult:
        started_at = _timestamp()
        started_ns = monotonic_ns()
        try:
            if descriptor.adapter != self.name or descriptor.check_id not in self._checks:
                raise ValueError("internal check is not registered")
            result = self._checks[descriptor.check_id](context, descriptor)
            if not isinstance(result, CheckResult):
                raise TypeError("internal check returned an invalid result")
            if (
                result.check_id != descriptor.check_id
                or result.title != descriptor.title
                or result.required is not descriptor.required
                or result.requirement_ids != descriptor.requirement_ids
            ):
                raise ValueError("internal check result does not match its descriptor")
            return result
        except Exception:
            return _result(
                descriptor,
                CheckStatus.ERROR,
                started_at=started_at,
                started_ns=started_ns,
                diagnostics=(_diagnostic(ErrorCode.CHECK_ERROR, descriptor, "internal"),),
            )
