from __future__ import annotations

import unittest

from p0_baseline.aggregation import AcceptanceGates, aggregate
from p0_baseline.errors import ErrorCode
from p0_baseline.models import (
    BaselineStatus,
    CheckResult,
    CheckStatus,
    Diagnostic,
)


TIMESTAMP = "2026-07-15T10:00:00+08:00"


def diagnostic_for(status: CheckStatus) -> Diagnostic:
    codes = {
        CheckStatus.FAILED: ErrorCode.CHECK_FAILED,
        CheckStatus.ERROR: ErrorCode.CHECK_ERROR,
        CheckStatus.SKIPPED: ErrorCode.CHECK_SKIPPED,
        CheckStatus.NOT_RUN: ErrorCode.RESULT_MISSING,
        CheckStatus.INTERRUPTED: ErrorCode.CHECK_INTERRUPTED,
    }
    return Diagnostic(
        code=codes[status],
        message=f"controlled {status.value}",
        failure_type="aggregation-test",
        target="aggregation.truth-table",
        recoverable=False,
    )


def check(index: int, status: CheckStatus, *, required: bool = True) -> CheckResult:
    return CheckResult(
        check_id=f"aggregation.case-{index}",
        title=f"Aggregation case {index}",
        required=required,
        requirement_ids=("3.2",),
        status=status,
        started_at=TIMESTAMP,
        finished_at=TIMESTAMP,
        duration_ms=0,
        target="aggregation.truth-table",
        diagnostics=() if status is CheckStatus.PASSED else (diagnostic_for(status),),
        evidence_refs=(f"checks/aggregation.case-{index}.json",),
    )


def passing_gates(**changes: bool) -> AcceptanceGates:
    values = {
        "clean_checkout": True,
        "offline": True,
        "evidence_complete": True,
        "requirement_coverage_complete": True,
        "supported_environment": True,
        "credentials_absent": True,
        "scope_compliant": True,
    }
    values.update(changes)
    return AcceptanceGates(**values)


class AggregationTruthTableTests(unittest.TestCase):
    def test_all_required_checks_pass_and_all_gates_pass(self) -> None:
        result = aggregate(
            (check(1, CheckStatus.PASSED), check(2, CheckStatus.PASSED)),
            gates=passing_gates(),
        )

        self.assertEqual(BaselineStatus.SUCCESS, result.overall_status)
        self.assertEqual(0, result.exit_code)
        self.assertTrue(result.acceptance_eligible)
        self.assertEqual(
            {
                "required_total": 2,
                "passed": 2,
                "failed": 0,
                "error": 0,
                "skipped": 0,
                "not_run": 0,
                "interrupted": 0,
            },
            result.summary.to_dict(),
        )

    def test_single_and_multiple_determinate_failures_return_failure(self) -> None:
        cases = (
            (check(1, CheckStatus.FAILED),),
            (check(1, CheckStatus.PASSED), check(2, CheckStatus.ERROR)),
            (check(1, CheckStatus.FAILED), check(2, CheckStatus.ERROR)),
        )
        for checks in cases:
            with self.subTest(statuses=tuple(item.status for item in checks)):
                result = aggregate(checks, gates=passing_gates())
                self.assertEqual(BaselineStatus.FAILURE, result.overall_status)
                self.assertEqual(1, result.exit_code)
                self.assertFalse(result.acceptance_eligible)

    def test_failure_has_priority_over_every_incomplete_condition(self) -> None:
        result = aggregate(
            (
                check(1, CheckStatus.FAILED),
                check(2, CheckStatus.SKIPPED),
                check(3, CheckStatus.NOT_RUN),
                check(4, CheckStatus.INTERRUPTED),
            ),
            gates=passing_gates(clean_checkout=False, evidence_complete=False),
        )

        self.assertEqual(BaselineStatus.FAILURE, result.overall_status)
        self.assertEqual(1, result.exit_code)
        self.assertEqual(1, result.summary.failed)
        self.assertEqual(1, result.summary.skipped)
        self.assertEqual(1, result.summary.not_run)
        self.assertEqual(1, result.summary.interrupted)

    def test_skip_not_run_and_interrupted_each_return_incomplete(self) -> None:
        for status in (
            CheckStatus.SKIPPED,
            CheckStatus.NOT_RUN,
            CheckStatus.INTERRUPTED,
        ):
            with self.subTest(status=status):
                result = aggregate((check(1, status),), gates=passing_gates())
                self.assertEqual(BaselineStatus.INCOMPLETE, result.overall_status)
                self.assertEqual(2, result.exit_code)
                self.assertFalse(result.acceptance_eligible)

    def test_dirty_checkout_prevents_success_without_becoming_failure(self) -> None:
        result = aggregate(
            (check(1, CheckStatus.PASSED),),
            gates=passing_gates(clean_checkout=False),
        )

        self.assertEqual(BaselineStatus.INCOMPLETE, result.overall_status)
        self.assertEqual(2, result.exit_code)
        self.assertFalse(result.acceptance_eligible)

    def test_each_other_failed_eligibility_gate_prevents_success(self) -> None:
        for gate in (
            "offline",
            "evidence_complete",
            "requirement_coverage_complete",
            "supported_environment",
            "credentials_absent",
            "scope_compliant",
        ):
            with self.subTest(gate=gate):
                result = aggregate(
                    (check(1, CheckStatus.PASSED),),
                    gates=passing_gates(**{gate: False}),
                )
                self.assertEqual(BaselineStatus.INCOMPLETE, result.overall_status)
                self.assertEqual(2, result.exit_code)
                self.assertFalse(result.acceptance_eligible)

    def test_run_level_determinate_failure_wins_over_passing_checks(self) -> None:
        result = aggregate(
            (check(1, CheckStatus.PASSED),),
            gates=passing_gates(),
            determinate_failure=True,
        )

        self.assertEqual(BaselineStatus.FAILURE, result.overall_status)
        self.assertEqual(1, result.exit_code)
        self.assertFalse(result.acceptance_eligible)

    def test_missing_required_results_cannot_vacuously_succeed(self) -> None:
        result = aggregate((), gates=passing_gates())

        self.assertEqual(BaselineStatus.INCOMPLETE, result.overall_status)
        self.assertEqual(0, result.summary.required_total)

    def test_non_required_results_do_not_change_required_aggregation(self) -> None:
        result = aggregate(
            (
                check(1, CheckStatus.PASSED),
                check(2, CheckStatus.FAILED, required=False),
            ),
            gates=passing_gates(),
        )

        self.assertEqual(BaselineStatus.SUCCESS, result.overall_status)
        self.assertEqual(1, result.summary.required_total)
        self.assertEqual(1, result.summary.passed)


if __name__ == "__main__":
    unittest.main()
