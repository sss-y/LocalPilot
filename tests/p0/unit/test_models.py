from __future__ import annotations

import json
from dataclasses import replace
import unittest

from p0_baseline.errors import ErrorCode
from p0_baseline.models import (
    BaselineReport,
    BaselineStatus,
    CheckResult,
    CheckStatus,
    CoverageStatus,
    Diagnostic,
    EnvironmentSnapshot,
    NetworkMode,
    RequirementCoverage,
    ResultSummary,
    WorkingTreeState,
)


TIMESTAMP = "2026-07-15T10:00:00+08:00"
REVISION = "0123456789abcdef0123456789abcdef01234567"
SUCCESS_REQUIREMENT_IDS = tuple(
    f"{group}.{criterion}"
    for group, total in {1: 5, 2: 6, 3: 6, 4: 6, 5: 6, 6: 9, 7: 6, 8: 6, 9: 6}.items()
    for criterion in range(1, total + 1)
)


def diagnostic(code: ErrorCode = ErrorCode.CHECK_FAILED) -> Diagnostic:
    return Diagnostic(
        code=code,
        message="controlled failure",
        failure_type="assertion",
        target="behavior.cli",
        recoverable=False,
        details={"attempt": 1},
    )


def check(
    status: CheckStatus = CheckStatus.PASSED,
    *,
    required: bool = True,
    requirement_ids: tuple[str, ...] = ("3.2",),
) -> CheckResult:
    diagnostic_codes = {
        CheckStatus.FAILED: ErrorCode.CHECK_FAILED,
        CheckStatus.ERROR: ErrorCode.CHECK_ERROR,
        CheckStatus.SKIPPED: ErrorCode.CHECK_SKIPPED,
        CheckStatus.NOT_RUN: ErrorCode.RESULT_MISSING,
        CheckStatus.INTERRUPTED: ErrorCode.CHECK_INTERRUPTED,
    }
    diagnostics = (
        (diagnostic(diagnostic_codes[status]),)
        if status in diagnostic_codes
        else ()
    )
    return CheckResult(
        check_id="behavior.cli",
        title="CLI behavior",
        required=required,
        requirement_ids=requirement_ids,
        status=status,
        started_at=TIMESTAMP,
        finished_at=TIMESTAMP,
        duration_ms=0,
        target="runagent.py",
        diagnostics=diagnostics,
        evidence_refs=("checks/behavior.cli.json",),
        observed={"tests_run": 1, "categories": ["cli"]},
    )


def environment(**changes: object) -> EnvironmentSnapshot:
    values: dict[str, object] = {
        "revision": REVISION,
        "repository_root": "<repository-root>",
        "working_tree_state": WorkingTreeState.CLEAN,
        "runtime_name": "python",
        "runtime_version": "3.12.13",
        "os": "Darwin",
        "architecture": "arm64",
        "dependency_fingerprint": "sha256:dependencies",
        "code_origins": {"core": "core/__init__.py"},
        "network_mode": NetworkMode.OFFLINE,
        "personal_credentials_loaded": False,
        "supported": True,
        "violations": (),
    }
    values.update(changes)
    return EnvironmentSnapshot(**values)


def all_success_coverage() -> tuple[RequirementCoverage, ...]:
    counts = {1: 5, 2: 6, 3: 6, 4: 6, 5: 6, 6: 9, 7: 6, 8: 6, 9: 6}
    return tuple(
        RequirementCoverage(
            requirement_id=f"{group}.{criterion}",
            status=CoverageStatus.PASSED,
            check_ids=("behavior.cli",),
            evidence_refs=("checks/behavior.cli.json",),
        )
        for group, total in counts.items()
        for criterion in range(1, total + 1)
    )


def report(
    *,
    status: BaselineStatus = BaselineStatus.SUCCESS,
    checks: tuple[CheckResult, ...] | None = None,
    coverage: tuple[RequirementCoverage, ...] | None = None,
    env: EnvironmentSnapshot | None = None,
    acceptance_eligible: bool | None = None,
    run_diagnostics: tuple[Diagnostic, ...] = (),
) -> BaselineReport:
    actual_checks = checks if checks is not None else (
        check(requirement_ids=SUCCESS_REQUIREMENT_IDS),
    )
    actual_coverage = coverage if coverage is not None else all_success_coverage()
    summary = ResultSummary.from_checks(actual_checks)
    return BaselineReport(
        schema_version="1.0.0",
        run_id="p0-test-run",
        revision=REVISION,
        manifest_digest="sha256:manifest",
        started_at=TIMESTAMP,
        finished_at=TIMESTAMP,
        duration_ms=0,
        mode=NetworkMode.OFFLINE,
        environment=env or environment(),
        overall_status=status,
        exit_code={
            BaselineStatus.SUCCESS: 0,
            BaselineStatus.FAILURE: 1,
            BaselineStatus.INCOMPLETE: 2,
        }[status],
        acceptance_eligible=(status is BaselineStatus.SUCCESS)
        if acceptance_eligible is None
        else acceptance_eligible,
        summary=summary,
        checks=actual_checks,
        requirement_coverage=actual_coverage,
        run_diagnostics=run_diagnostics,
        redaction={"enabled": True, "matched_values": 0},
    )


class EnumAndErrorContractTests(unittest.TestCase):
    def test_all_contract_statuses_are_exposed(self) -> None:
        self.assertEqual(
            {"success", "failure", "incomplete"},
            {item.value for item in BaselineStatus},
        )
        self.assertEqual(
            {"passed", "failed", "error", "skipped", "not_run", "interrupted"},
            {item.value for item in CheckStatus},
        )
        self.assertEqual(
            {"passed", "failed", "incomplete"},
            {item.value for item in CoverageStatus},
        )

    def test_minimum_stable_error_code_set_is_complete(self) -> None:
        expected = {
            "P0_MANIFEST_INVALID", "P0_ASSET_MISSING", "P0_ENV_UNSUPPORTED",
            "P0_DEPENDENCY_UNDECLARED", "P0_TEST_DISCOVERY_FAILED",
            "P0_STALE_REFERENCE", "P0_CODE_ORIGIN_MISMATCH",
            "P0_CACHE_DEPENDENCY_DETECTED", "P0_NETWORK_POLICY_VIOLATION",
            "P0_CHECK_FAILED", "P0_CHECK_ERROR", "P0_CHECK_SKIPPED",
            "P0_CHECK_INTERRUPTED", "P0_RESULT_MISSING", "P0_EVIDENCE_INCOMPLETE",
            "P0_DOCUMENTATION_MISMATCH", "P0_SCOPE_VIOLATION",
        }
        self.assertEqual(expected, {item.value for item in ErrorCode})


class ValueObjectTests(unittest.TestCase):
    def test_every_non_passed_check_requires_a_status_consistent_diagnostic(self) -> None:
        for status in CheckStatus:
            if status is CheckStatus.PASSED:
                continue
            with self.subTest(status=status), self.assertRaises(ValueError):
                replace(check(status), diagnostics=())

        inconsistent = (
            (CheckStatus.FAILED, ErrorCode.CHECK_SKIPPED),
            (CheckStatus.ERROR, ErrorCode.RESULT_MISSING),
            (CheckStatus.SKIPPED, ErrorCode.CHECK_ERROR),
            (CheckStatus.NOT_RUN, ErrorCode.CHECK_FAILED),
            (CheckStatus.INTERRUPTED, ErrorCode.CHECK_ERROR),
        )
        for status, code in inconsistent:
            with self.subTest(status=status, code=code), self.assertRaises(ValueError):
                replace(check(status), diagnostics=(diagnostic(code),))

    def test_diagnostic_round_trip_preserves_json_values(self) -> None:
        original = diagnostic()
        encoded = original.to_dict()
        self.assertEqual(original, Diagnostic.from_dict(encoded))
        self.assertEqual(encoded, json.loads(json.dumps(encoded)))

    def test_unknown_optional_fields_are_ignored_for_same_major_consumers(self) -> None:
        encoded = diagnostic().to_dict()
        encoded["future_optional"] = {"value": True}
        self.assertEqual(diagnostic(), Diagnostic.from_dict(encoded))

    def test_non_json_values_are_rejected_without_string_coercion(self) -> None:
        with self.assertRaisesRegex(ValueError, "JSON"):
            Diagnostic(
                code=ErrorCode.CHECK_ERROR,
                message="bad details",
                failure_type="runtime",
                target="worker",
                recoverable=False,
                details={"opaque": object()},
            )

    def test_check_and_requirement_identifier_formats_are_strict(self) -> None:
        for invalid in ("CLI", "cli", "cli..help", "cli.Help", "_cli.help"):
            with self.subTest(check_id=invalid), self.assertRaises(ValueError):
                check().from_dict({**check().to_dict(), "check_id": invalid})
        for invalid in ("REQ-3.2", "3", "3.a", "3.2.1", " 3.2"):
            with self.subTest(requirement_id=invalid), self.assertRaises(ValueError):
                RequirementCoverage(
                    requirement_id=invalid,
                    status=CoverageStatus.PASSED,
                    check_ids=("behavior.cli",),
                    evidence_refs=("evidence.json",),
                )

    def test_timestamp_duration_and_required_diagnostics_are_validated(self) -> None:
        for invalid in ("2026-07-15T10:00:00", "2026-07-15 10:00:00Z", "not-time"):
            with self.subTest(timestamp=invalid), self.assertRaises(ValueError):
                CheckResult.from_dict({**check().to_dict(), "started_at": invalid})
        with self.assertRaises(ValueError):
            CheckResult.from_dict({**check().to_dict(), "duration_ms": -1})
        for status in (CheckStatus.FAILED, CheckStatus.ERROR):
            with self.subTest(status=status), self.assertRaisesRegex(ValueError, "diagnostic"):
                CheckResult.from_dict(
                    {**check().to_dict(), "status": status.value, "diagnostics": []}
                )

    def test_check_round_trip_covers_every_status(self) -> None:
        for status in CheckStatus:
            with self.subTest(status=status):
                original = check(status)
                self.assertEqual(original, CheckResult.from_dict(original.to_dict()))

    def test_environment_round_trip_and_types_are_strict(self) -> None:
        original = environment()
        self.assertEqual(original, EnvironmentSnapshot.from_dict(original.to_dict()))
        with self.assertRaises(TypeError):
            EnvironmentSnapshot.from_dict(
                {**original.to_dict(), "personal_credentials_loaded": 0}
            )
        with self.assertRaises(ValueError):
            EnvironmentSnapshot.from_dict(
                {**original.to_dict(), "supported": False, "violations": []}
            )

    def test_summary_counts_only_required_checks(self) -> None:
        checks = (
            check(CheckStatus.PASSED),
            CheckResult.from_dict(
                {
                    **check(CheckStatus.FAILED, required=False).to_dict(),
                    "check_id": "supplemental.smoke",
                }
            ),
        )
        self.assertEqual(
            ResultSummary(required_total=1, passed=1),
            ResultSummary.from_checks(checks),
        )
        with self.assertRaises(ValueError):
            ResultSummary(required_total=1, passed=0)


class ReportInvariantTests(unittest.TestCase):
    def test_authoritative_success_report_round_trip(self) -> None:
        original = report()
        encoded = original.to_dict()
        self.assertEqual(original, BaselineReport.from_dict(encoded))
        self.assertEqual(encoded, json.loads(json.dumps(encoded)))

    def test_success_does_not_require_legacy_requirement_coverage(self) -> None:
        successful = report(
            checks=(check(requirement_ids=("3.2",)),),
            coverage=(),
        )

        self.assertIs(successful.overall_status, BaselineStatus.SUCCESS)

    def test_legacy_coverage_status_does_not_override_success(self) -> None:
        for status in (CoverageStatus.FAILED, CoverageStatus.INCOMPLETE):
            with self.subTest(status=status):
                legacy = RequirementCoverage(
                    requirement_id="3.2",
                    status=status,
                    check_ids=("behavior.cli",),
                    evidence_refs=("evidence.json",),
                )

                successful = report(
                    checks=(check(requirement_ids=("3.2",)),),
                    coverage=(legacy,),
                )

                self.assertIs(successful.overall_status, BaselineStatus.SUCCESS)

    def test_status_exit_code_truth_table_is_enforced(self) -> None:
        original = report().to_dict()
        for status, correct in (("success", 0), ("failure", 1), ("incomplete", 2)):
            for exit_code in (0, 1, 2):
                if exit_code == correct:
                    continue
                with self.subTest(status=status, exit_code=exit_code), self.assertRaises(ValueError):
                    BaselineReport.from_dict(
                        {**original, "overall_status": status, "exit_code": exit_code}
                    )

    def test_summary_must_match_required_checks(self) -> None:
        encoded = report().to_dict()
        encoded["summary"]["passed"] = 0
        encoded["summary"]["not_run"] = 1
        with self.assertRaisesRegex(ValueError, "summary"):
            BaselineReport.from_dict(encoded)

    def test_success_requires_all_required_checks_to_pass(self) -> None:
        for status in (
            CheckStatus.FAILED,
            CheckStatus.ERROR,
            CheckStatus.SKIPPED,
            CheckStatus.NOT_RUN,
            CheckStatus.INTERRUPTED,
        ):
            with self.subTest(status=status), self.assertRaises(ValueError):
                report(checks=(check(status),))

    def test_acceptance_eligibility_requires_clean_supported_offline_environment(self) -> None:
        invalid_environments = (
            environment(working_tree_state=WorkingTreeState.DIRTY),
            environment(supported=False, violations=(diagnostic(ErrorCode.ENV_UNSUPPORTED),)),
            environment(personal_credentials_loaded=True),
        )
        for env in invalid_environments:
            with self.subTest(env=env), self.assertRaises(ValueError):
                report(env=env)

    def test_failure_and_incomplete_reports_follow_priority_rules(self) -> None:
        failed_report = report(
            status=BaselineStatus.FAILURE,
            checks=(
                check(CheckStatus.FAILED),
                CheckResult.from_dict(
                    {**check(CheckStatus.NOT_RUN).to_dict(), "check_id": "behavior.other"}
                ),
            ),
            coverage=(),
        )
        self.assertEqual(BaselineStatus.FAILURE, failed_report.overall_status)
        incomplete_report = report(
            status=BaselineStatus.INCOMPLETE,
            checks=(check(CheckStatus.SKIPPED),),
            coverage=(),
        )
        self.assertEqual(BaselineStatus.INCOMPLETE, incomplete_report.overall_status)
        with self.assertRaises(ValueError):
            report(
                status=BaselineStatus.INCOMPLETE,
                checks=(check(CheckStatus.ERROR),),
                coverage=(),
            )

    def test_run_level_incomplete_signals_cannot_be_reported_as_success(self) -> None:
        with self.assertRaisesRegex(ValueError, "incomplete"):
            report(
                status=BaselineStatus.SUCCESS,
                checks=(check(requirement_ids=SUCCESS_REQUIREMENT_IDS),),
                run_diagnostics=(diagnostic(ErrorCode.CHECK_SKIPPED),),
            )

    def test_incomplete_requires_an_observed_incomplete_condition(self) -> None:
        with self.assertRaisesRegex(ValueError, "incomplete"):
            report(
                status=BaselineStatus.INCOMPLETE,
                checks=(check(requirement_ids=("3.2",)),),
                coverage=(),
            )

    def test_result_missing_is_incomplete_and_cannot_be_success(self) -> None:
        missing = diagnostic(ErrorCode.RESULT_MISSING)
        incomplete = report(
            status=BaselineStatus.INCOMPLETE,
            checks=(check(requirement_ids=("3.2",)),),
            coverage=(),
            run_diagnostics=(missing,),
        )
        self.assertEqual(BaselineStatus.INCOMPLETE, incomplete.overall_status)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            report(run_diagnostics=(missing,))

    def test_coverage_must_reference_a_check_that_declares_the_requirement(self) -> None:
        false_mapping = RequirementCoverage(
            requirement_id="8.1",
            status=CoverageStatus.PASSED,
            check_ids=("behavior.cli",),
            evidence_refs=("evidence.json",),
        )
        with self.assertRaisesRegex(ValueError, "declare"):
            report(
                status=BaselineStatus.FAILURE,
                checks=(check(CheckStatus.FAILED, requirement_ids=("3.2",)),),
                coverage=(false_mapping,),
            )

    def test_every_coverage_reference_must_declare_the_requirement(self) -> None:
        declaring = check(CheckStatus.FAILED, requirement_ids=("8.1",))
        unrelated = CheckResult.from_dict(
            {
                **check(requirement_ids=("3.2",)).to_dict(),
                "check_id": "behavior.other",
            }
        )
        mixed_mapping = RequirementCoverage(
            requirement_id="8.1",
            status=CoverageStatus.FAILED,
            check_ids=("behavior.cli", "behavior.other"),
            evidence_refs=("evidence.json",),
        )
        with self.assertRaisesRegex(ValueError, "every referenced check"):
            report(
                status=BaselineStatus.FAILURE,
                checks=(declaring, unrelated),
                coverage=(mixed_mapping,),
            )

    def test_supported_flag_and_environment_diagnostic_are_bidirectionally_consistent(self) -> None:
        skipped = diagnostic(ErrorCode.CHECK_SKIPPED)
        unsupported = diagnostic(ErrorCode.ENV_UNSUPPORTED)
        with self.assertRaisesRegex(ValueError, "ENV_UNSUPPORTED"):
            environment(supported=False, violations=(skipped,))
        with self.assertRaisesRegex(ValueError, "ENV_UNSUPPORTED"):
            environment(supported=True, violations=(unsupported,))

        unsupported_environment = environment(
            supported=False,
            violations=(unsupported,),
        )
        failure = report(
            status=BaselineStatus.FAILURE,
            checks=(),
            coverage=(),
            env=unsupported_environment,
        )
        self.assertEqual(BaselineStatus.FAILURE, failure.overall_status)
        with self.assertRaisesRegex(ValueError, "failure"):
            report(
                status=BaselineStatus.INCOMPLETE,
                checks=(),
                coverage=(),
                env=unsupported_environment,
            )

    def test_redaction_ignores_future_optional_fields(self) -> None:
        encoded = report().to_dict()
        encoded["redaction"]["future_optional"] = {"algorithm": "v2"}
        decoded = BaselineReport.from_dict(encoded)
        self.assertEqual(
            {"enabled": True, "matched_values": 0},
            decoded.to_dict()["redaction"],
        )

    def test_manifest_failure_can_be_authoritative_without_checks(self) -> None:
        result = report(
            status=BaselineStatus.FAILURE,
            checks=(),
            coverage=(),
            run_diagnostics=(diagnostic(ErrorCode.MANIFEST_INVALID),),
        )
        self.assertEqual(0, result.summary.required_total)

    def test_invalid_mutated_object_cannot_serialize_authoritative_dict(self) -> None:
        result = report()
        object.__setattr__(result, "exit_code", 1)
        with self.assertRaises(ValueError):
            result.to_dict()

if __name__ == "__main__":
    unittest.main()
