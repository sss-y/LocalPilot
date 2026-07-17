from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from p0_baseline.adapters import (
    InternalAdapter,
    UnittestAdapter,
    VerificationContext,
    not_run_result,
)
from p0_baseline.check_worker import (
    WorkerOutcome,
    WorkerRequest,
    WorkerResult,
    execute_worker_request,
    run_worker_files,
)
from p0_baseline.errors import ErrorCode
from p0_baseline.manifest import CheckDescriptor, load_manifest
from p0_baseline.models import CheckResult, CheckStatus
from p0_baseline.registry import AdapterLookupError, AdapterRegistry
from p0_baseline.safe_subprocess import SafeSubprocessError


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def descriptor(adapter: str = "unittest", check_id: str = "runtime.fake") -> CheckDescriptor:
    source = load_manifest(REPOSITORY_ROOT / "p0_baseline" / "manifest.json").checks[0]
    return replace(
        source,
        check_id=check_id,
        title="Runtime fake",
        requirement_ids=("3.3",),
        asset_refs=("tests/p0/unit/test_check_runtime.py",),
        adapter=adapter,
        test_ids=(
            "tests.p0.fixtures.worker_cases.PassingFixture.test_passes",
        ) if adapter == "unittest" else (),
    )


class CheckWorkerTests(unittest.TestCase):
    def test_real_unittest_decorators_preserve_skip_xfail_and_unexpected_success(self) -> None:
        test_ids = (
            "tests.p0.fixtures.worker_cases.SkippedFixture.test_is_skipped",
            "tests.p0.fixtures.worker_cases.ExpectedFailureFixture.test_is_expected_failure",
            "tests.p0.fixtures.worker_cases.UnexpectedSuccessFixture.test_is_unexpected_success",
        )

        result = execute_worker_request(WorkerRequest("1.0.0", test_ids))

        self.assertEqual(3, result.tests_run)
        self.assertEqual(test_ids, tuple(item.test_id for item in result.outcomes))
        self.assertEqual(
            ("skipped", "expected_failure", "unexpected_success"),
            tuple(item.status for item in result.outcomes),
        )

    def test_exact_test_ids_produce_structured_passed_failed_and_error_outcomes(self) -> None:
        test_ids = (
            "tests.p0.fixtures.worker_cases.PassingFixture.test_passes",
            "tests.p0.fixtures.worker_cases.FailingFixture.test_fails",
            "tests.p0.fixtures.worker_cases.ErrorFixture.test_errors",
        )

        result = execute_worker_request(WorkerRequest("1.0.0", test_ids))

        self.assertEqual(3, result.tests_run)
        self.assertEqual(test_ids, tuple(item.test_id for item in result.outcomes))
        self.assertEqual(
            ("passed", "failed", "error"),
            tuple(item.status for item in result.outcomes),
        )
        self.assertNotIn("controlled failure", result.to_json())
        self.assertNotIn("controlled error", result.to_json())
        self.assertEqual(result, WorkerResult.from_json(result.to_json()))

    def test_unknown_exact_test_id_is_a_structured_discovery_error(self) -> None:
        result = execute_worker_request(
            WorkerRequest("1.0.0", ("tests.p0.fixtures.worker_cases.Missing.test_absent",))
        )

        self.assertEqual(1, result.tests_run)
        self.assertEqual("error", result.outcomes[0].status)
        self.assertEqual("discovery", result.outcomes[0].failure_type)

    def test_worker_outcome_rejects_unsafe_network_target_summaries(self) -> None:
        test_id = "tests.p0.fixtures.worker_cases.PassingFixture.test_passes"
        for target in (
            "https://user:password@example.invalid/path?token=secret",
            "example.invalid?token=secret",
            "user:password@example.invalid",
        ):
            with self.subTest(target=target), self.assertRaises(ValueError):
                WorkerOutcome(
                    test_id,
                    "failed",
                    "network_policy",
                    target,
                    "getaddrinfo",
                    "check-worker",
                )

    def test_network_policy_outcome_requires_the_exact_failed_field_combination(self) -> None:
        test_id = "tests.p0.fixtures.worker_cases.PassingFixture.test_passes"
        for status in (
            "passed",
            "error",
            "skipped",
            "expected_failure",
            "unexpected_success",
        ):
            with self.subTest(status=status), self.assertRaises(ValueError):
                WorkerOutcome(
                    test_id,
                    status,
                    "network_policy",
                    "example.invalid",
                    "getaddrinfo",
                    "check-worker",
                )

        for failure_type in (None, "assertion", "exception", "discovery"):
            status = "passed" if failure_type is None else "failed"
            with self.subTest(failure_type=failure_type), self.assertRaises(ValueError):
                WorkerOutcome(
                    test_id,
                    status,
                    failure_type,
                    "example.invalid",
                    "getaddrinfo",
                    "check-worker",
                )

        for operation, source in (
            ("system", "check-worker"),
            ("getaddrinfo", "Authorization secret"),
            ("getaddrinfo", "CHECK-WORKER"),
            ("getaddrinfo", "parent"),
        ):
            with self.subTest(operation=operation, source=source), self.assertRaises(ValueError):
                WorkerOutcome(
                    test_id,
                    "failed",
                    "network_policy",
                    "example.invalid",
                    operation,
                    source,
                )

        network_fields = ("example.invalid", "getaddrinfo", "check-worker")
        for missing_index in range(3):
            incomplete = list(network_fields)
            incomplete[missing_index] = None
            with self.subTest(missing_index=missing_index), self.assertRaises(
                (TypeError, ValueError)
            ):
                WorkerOutcome(
                    test_id,
                    "failed",
                    "network_policy",
                    *incomplete,
                )

    def test_worker_outcome_json_rejects_unknown_and_partial_network_fields(self) -> None:
        test_id = "tests.p0.fixtures.worker_cases.PassingFixture.test_passes"
        valid = WorkerOutcome(
            test_id,
            "failed",
            "network_policy",
            "example.invalid",
            "getaddrinfo",
            "check-worker",
        ).to_dict()
        self.assertEqual(WorkerOutcome.from_dict(valid).to_dict(), valid)
        self.assertEqual(
            WorkerOutcome(test_id, "passed"),
            WorkerOutcome.from_dict({"test_id": test_id, "status": "passed"}),
        )

        unknown = dict(valid, authorization="Bearer worker-secret")
        with self.assertRaises(ValueError):
            WorkerOutcome.from_dict(unknown)

        for missing in ("target_summary", "operation", "source"):
            partial = dict(valid)
            del partial[missing]
            with self.subTest(missing=missing), self.assertRaises((TypeError, ValueError)):
                WorkerOutcome.from_dict(partial)

    def test_malformed_network_policy_json_becomes_check_error(self) -> None:
        test_id = "tests.p0.fixtures.worker_cases.PassingFixture.test_passes"
        target = replace(descriptor(), test_ids=(test_id,))
        malformed = (
            '{"schema_version":"1.0.0","tests_run":1,"outcomes":['
            f'{{"test_id":"{test_id}","status":"error",'
            '"failure_type":"network_policy","target_summary":"example.invalid",'
            '"operation":"getaddrinfo","source":"check-worker"}}]}'
        )

        with TemporaryDirectory() as directory:
            context = VerificationContext(
                repository_root=REPOSITORY_ROOT,
                run_directory=Path(directory),
                worker_executor=lambda request: malformed,
            )
            result = UnittestAdapter().execute(context, target)

        self.assertIs(result.status, CheckStatus.ERROR)
        self.assertEqual(ErrorCode.CHECK_ERROR, result.diagnostics[0].code)

    def test_worker_uses_request_and_result_files_as_the_authoritative_protocol(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            request_path = root / "request.json"
            result_path = root / "result.json"
            request = WorkerRequest(
                "1.0.0",
                ("tests.p0.fixtures.worker_cases.PassingFixture.test_passes",),
            )
            request_path.write_text(request.to_json(), encoding="utf-8")

            run_worker_files(str(request_path), str(result_path))

            self.assertEqual(
                execute_worker_request(request),
                WorkerResult.from_json(result_path.read_text(encoding="utf-8")),
            )
            with self.assertRaises(FileExistsError):
                run_worker_files(str(request_path), str(result_path))

            other = root / "other"
            other.mkdir()
            with self.assertRaises(ValueError):
                run_worker_files(str(request_path), str(other / "result.json"))


class AdapterTests(unittest.TestCase):
    def _context(self, executor):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        return VerificationContext(
            repository_root=REPOSITORY_ROOT,
            run_directory=Path(self.directory.name),
            worker_executor=executor,
        )

    def test_unittest_adapter_converts_worker_json_without_parsing_terminal_text(self) -> None:
        request_result = execute_worker_request(
            WorkerRequest(
                "1.0.0",
                (
                    "tests.p0.fixtures.worker_cases.PassingFixture.test_passes",
                    "tests.p0.fixtures.worker_cases.FailingFixture.test_fails",
                ),
            )
        )
        target = replace(
            descriptor(),
            test_ids=tuple(item.test_id for item in request_result.outcomes),
        )

        result = UnittestAdapter().execute(
            self._context(lambda request: request_result.to_json()),
            target,
        )

        self.assertIs(result.status, CheckStatus.FAILED)
        self.assertEqual(ErrorCode.CHECK_FAILED, result.diagnostics[0].code)
        self.assertEqual(2, result.observed["tests_run"])

    def test_invalid_worker_json_becomes_a_stable_error_result(self) -> None:
        result = UnittestAdapter().execute(
            self._context(lambda request: "not-json"),
            descriptor(),
        )

        self.assertIs(result.status, CheckStatus.ERROR)
        self.assertEqual(ErrorCode.CHECK_ERROR, result.diagnostics[0].code)
        self.assertNotIn("not-json", result.to_dict().__repr__())

    def test_skip_and_expected_failure_are_incomplete_not_worker_errors(self) -> None:
        test_ids = (
            "tests.p0.fixtures.worker_cases.SkippedFixture.test_is_skipped",
            "tests.p0.fixtures.worker_cases.ExpectedFailureFixture.test_is_expected_failure",
        )
        worker = execute_worker_request(WorkerRequest("1.0.0", test_ids))

        result = UnittestAdapter().execute(
            self._context(lambda request: worker.to_json()),
            replace(descriptor(), test_ids=test_ids),
        )

        self.assertIs(result.status, CheckStatus.SKIPPED)
        self.assertEqual((ErrorCode.CHECK_SKIPPED,), tuple(d.code for d in result.diagnostics))
        self.assertEqual(
            {"expected_failure": 1, "skipped": 1},
            dict(result.observed["outcome_counts"]),
        )

    def test_unexpected_success_is_a_test_classification_error(self) -> None:
        test_id = (
            "tests.p0.fixtures.worker_cases."
            "UnexpectedSuccessFixture.test_is_unexpected_success"
        )
        worker = execute_worker_request(WorkerRequest("1.0.0", (test_id,)))

        result = UnittestAdapter().execute(
            self._context(lambda request: worker.to_json()),
            replace(descriptor(), test_ids=(test_id,)),
        )

        self.assertIs(result.status, CheckStatus.ERROR)
        self.assertEqual(ErrorCode.CHECK_ERROR, result.diagnostics[0].code)
        self.assertEqual("test_classification", result.diagnostics[0].failure_type)

    def test_failed_outcome_has_priority_over_skip_but_preserves_skip_evidence(self) -> None:
        test_ids = (
            "tests.p0.fixtures.worker_cases.FailingFixture.test_fails",
            "tests.p0.fixtures.worker_cases.SkippedFixture.test_is_skipped",
        )
        worker = execute_worker_request(WorkerRequest("1.0.0", test_ids))

        result = UnittestAdapter().execute(
            self._context(lambda request: worker.to_json()),
            replace(descriptor(), test_ids=test_ids),
        )

        self.assertIs(result.status, CheckStatus.FAILED)
        self.assertEqual(
            (ErrorCode.CHECK_FAILED, ErrorCode.CHECK_SKIPPED),
            tuple(d.code for d in result.diagnostics),
        )
        self.assertEqual({"failed": 1, "skipped": 1}, dict(result.observed["outcome_counts"]))

    def test_worker_error_has_priority_over_failure_and_skip(self) -> None:
        test_ids = (
            "tests.p0.fixtures.worker_cases.FailingFixture.test_fails",
            "tests.p0.fixtures.worker_cases.SkippedFixture.test_is_skipped",
            "tests.p0.fixtures.worker_cases.ErrorFixture.test_errors",
        )
        worker = execute_worker_request(WorkerRequest("1.0.0", test_ids))

        result = UnittestAdapter().execute(
            self._context(lambda request: worker.to_json()),
            replace(descriptor(), test_ids=test_ids),
        )

        self.assertIs(result.status, CheckStatus.ERROR)
        self.assertEqual(ErrorCode.CHECK_ERROR, result.diagnostics[0].code)
        self.assertIn(ErrorCode.CHECK_FAILED, tuple(d.code for d in result.diagnostics))
        self.assertIn(ErrorCode.CHECK_SKIPPED, tuple(d.code for d in result.diagnostics))

    def test_inexact_worker_coverage_is_a_check_error(self) -> None:
        requested = (
            "tests.p0.fixtures.worker_cases.PassingFixture.test_passes",
            "tests.p0.fixtures.worker_cases.FailingFixture.test_fails",
        )
        variants = (
            WorkerResult(
                "1.0.0",
                1,
                (
                    WorkerOutcome(requested[0], "passed"),
                    WorkerOutcome(requested[1], "failed", "assertion"),
                ),
            ),
            WorkerResult("1.0.0", 2, (WorkerOutcome(requested[0], "passed"),)),
            WorkerResult(
                "1.0.0",
                2,
                (WorkerOutcome(requested[1], "failed", "assertion"), WorkerOutcome(requested[0], "passed")),
            ),
        )
        for worker in variants:
            with self.subTest(worker=worker):
                result = UnittestAdapter().execute(
                    self._context(lambda request, value=worker: value.to_json()),
                    replace(descriptor(), test_ids=requested),
                )
                self.assertIs(result.status, CheckStatus.ERROR)
                self.assertEqual(ErrorCode.CHECK_ERROR, result.diagnostics[0].code)
                self.assertEqual("result_integrity", result.diagnostics[0].failure_type)

    def test_worker_process_failures_become_check_errors_without_leaking_reason(self) -> None:
        for reason in (
            "P0_WORKER_TIMEOUT",
            "P0_WORKER_EXIT_NONZERO",
            "P0_WORKER_RESULT_MISSING",
            "P0_WORKER_RESULT_INVALID",
        ):
            with self.subTest(reason=reason):
                result = UnittestAdapter().execute(
                    self._context(
                        lambda request, value=reason: (_ for _ in ()).throw(
                            SafeSubprocessError(value)
                        )
                    ),
                    descriptor(),
                )
                self.assertIs(result.status, CheckStatus.ERROR)
                self.assertEqual(ErrorCode.CHECK_ERROR, result.diagnostics[0].code)
                self.assertNotIn(reason, repr(result.to_dict()))

    def test_not_run_result_is_descriptor_consistent_and_incomplete(self) -> None:
        target = descriptor()

        result = not_run_result(target)

        self.assertEqual(target.check_id, result.check_id)
        self.assertEqual(target.title, result.title)
        self.assertIs(target.required, result.required)
        self.assertEqual(target.requirement_ids, result.requirement_ids)
        self.assertIs(result.status, CheckStatus.NOT_RUN)
        self.assertEqual((ErrorCode.RESULT_MISSING,), tuple(d.code for d in result.diagnostics))
        self.assertEqual("not_run", result.diagnostics[0].failure_type)

    def test_adapter_accepts_the_safe_subprocess_structured_result(self) -> None:
        worker = WorkerResult(
            "1.0.0",
            1,
            (
                WorkerOutcome(
                    "tests.p0.fixtures.worker_cases.PassingFixture.test_passes",
                    "passed",
                ),
            ),
        )

        result = UnittestAdapter().execute(self._context(lambda request: worker), descriptor())

        self.assertIs(result.status, CheckStatus.PASSED)

    def test_network_policy_outcome_becomes_a_safe_failed_diagnostic(self) -> None:
        test_id = "tests.p0.fixtures.worker_cases.OfflineNetworkFixture.test_external_dns_is_blocked"
        worker = WorkerResult(
            "1.0.0",
            1,
            (
                WorkerOutcome(
                    test_id,
                    "failed",
                    "network_policy",
                    "example.invalid",
                    "getaddrinfo",
                    "check-worker",
                ),
            ),
        )
        target = replace(descriptor(), test_ids=(test_id,))

        result = UnittestAdapter().execute(
            self._context(lambda request: worker.to_json()),
            target,
        )

        self.assertIs(result.status, CheckStatus.FAILED)
        diagnostic = result.diagnostics[0]
        self.assertEqual(ErrorCode.NETWORK_POLICY_VIOLATION, diagnostic.code)
        self.assertEqual("example.invalid", diagnostic.target)
        self.assertEqual(test_id, diagnostic.details["test_id"])
        self.assertEqual("getaddrinfo", diagnostic.details["operation"])
        self.assertEqual("check-worker", diagnostic.details["source"])

    def test_multiple_network_violations_preserve_each_safe_diagnostic(self) -> None:
        test_ids = (
            "tests.p0.fixtures.worker_cases.OfflineNetworkFixture.test_external_dns_is_blocked",
            "tests.p0.fixtures.worker_cases.OfflineNetworkFixture.test_external_tcp_is_blocked",
        )
        worker = WorkerResult(
            "1.0.0",
            2,
            (
                WorkerOutcome(
                    test_ids[0], "failed", "network_policy", "example.invalid",
                    "getaddrinfo", "check-worker",
                ),
                WorkerOutcome(
                    test_ids[1], "failed", "network_policy", "203.0.113.17",
                    "connect", "check-worker",
                ),
            ),
        )

        result = UnittestAdapter().execute(
            self._context(lambda request: worker.to_json()),
            replace(descriptor(), test_ids=test_ids),
        )

        self.assertIs(result.status, CheckStatus.FAILED)
        self.assertEqual(
            (ErrorCode.NETWORK_POLICY_VIOLATION, ErrorCode.NETWORK_POLICY_VIOLATION),
            tuple(item.code for item in result.diagnostics),
        )
        self.assertEqual(test_ids, tuple(item.details["test_id"] for item in result.diagnostics))

    def test_network_and_ordinary_failure_preserve_both_diagnostics(self) -> None:
        network_id = "tests.p0.fixtures.worker_cases.OfflineNetworkFixture.test_external_dns_is_blocked"
        failed_id = "tests.p0.fixtures.worker_cases.FailingFixture.test_fails"
        worker = WorkerResult(
            "1.0.0",
            2,
            (
                WorkerOutcome(
                    network_id, "failed", "network_policy", "example.invalid",
                    "getaddrinfo", "check-worker",
                ),
                WorkerOutcome(failed_id, "failed", "assertion"),
            ),
        )

        result = UnittestAdapter().execute(
            self._context(lambda request: worker.to_json()),
            replace(descriptor(), test_ids=(network_id, failed_id)),
        )

        self.assertIs(result.status, CheckStatus.FAILED)
        self.assertEqual(
            (ErrorCode.NETWORK_POLICY_VIOLATION, ErrorCode.CHECK_FAILED),
            tuple(item.code for item in result.diagnostics),
        )

    def test_worker_errors_override_network_failure_but_preserve_evidence(self) -> None:
        network_id = "tests.p0.fixtures.worker_cases.OfflineNetworkFixture.test_external_dns_is_blocked"
        for incomplete_status, failure_type in (
            ("error", "exception"),
            ("unexpected_success", "unexpected_success"),
        ):
            incomplete_id = "tests.p0.fixtures.worker_cases.ErrorFixture.test_errors"
            worker = WorkerResult(
                "1.0.0",
                2,
                (
                    WorkerOutcome(
                        network_id, "failed", "network_policy", "example.invalid",
                        "getaddrinfo", "check-worker",
                    ),
                    WorkerOutcome(incomplete_id, incomplete_status, failure_type),
                ),
            )
            with self.subTest(status=incomplete_status):
                result = UnittestAdapter().execute(
                    self._context(lambda request, value=worker: value.to_json()),
                    replace(descriptor(), test_ids=(network_id, incomplete_id)),
                )
                self.assertIs(result.status, CheckStatus.ERROR)
                self.assertEqual(ErrorCode.CHECK_ERROR, result.diagnostics[0].code)
                self.assertIn(
                    ErrorCode.NETWORK_POLICY_VIOLATION,
                    tuple(item.code for item in result.diagnostics),
                )

    def test_internal_adapter_only_executes_explicitly_registered_control_checks(self) -> None:
        def passed(context: VerificationContext, target: CheckDescriptor) -> CheckResult:
            return UnittestAdapter.result_for_status(target, CheckStatus.PASSED)

        adapter = InternalAdapter({"runtime.fake": passed})
        context = self._context(lambda request: "unused")
        self.assertIs(adapter.execute(context, descriptor("internal")).status, CheckStatus.PASSED)

        rejected = adapter.execute(context, descriptor("internal", "runtime.unknown"))
        self.assertIs(rejected.status, CheckStatus.ERROR)
        self.assertEqual(ErrorCode.CHECK_ERROR, rejected.diagnostics[0].code)

    def test_registry_rejects_unknown_adapter_with_stable_diagnostic(self) -> None:
        registry = AdapterRegistry(unittest=UnittestAdapter(), internal=InternalAdapter({}))

        with self.assertRaises(AdapterLookupError) as caught:
            registry.resolve("shell")

        self.assertIs(caught.exception.code, ErrorCode.MANIFEST_INVALID)
        self.assertEqual("adapter", caught.exception.to_diagnostic().failure_type)


if __name__ == "__main__":
    unittest.main()
