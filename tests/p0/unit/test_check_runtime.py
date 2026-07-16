from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from p0_baseline.adapters import InternalAdapter, UnittestAdapter, VerificationContext
from p0_baseline.check_worker import (
    WorkerRequest,
    WorkerResult,
    execute_worker_request,
    run_worker_files,
)
from p0_baseline.errors import ErrorCode
from p0_baseline.manifest import CheckDescriptor, load_manifest
from p0_baseline.models import CheckResult, CheckStatus
from p0_baseline.registry import AdapterLookupError, AdapterRegistry


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
