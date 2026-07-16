"""Structured unittest worker protocol for exact P0 test identifiers."""

from __future__ import annotations

import io
import argparse
import json
import re
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path


_TEST_ID = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*\.){2,}[A-Za-z_][A-Za-z0-9_]*$")
_OUTCOME_STATUSES = frozenset({
    "passed", "failed", "error", "skipped", "expected_failure", "unexpected_success",
})


def _object(value: object, name: str) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise TypeError(f"{name} must be an object")
    return value


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be nonempty text")
    return value


def _test_ids(value: object) -> tuple[str, ...]:
    if type(value) is not list and type(value) is not tuple:
        raise TypeError("test_ids must be an array")
    result = tuple(_text(item, "test_id") for item in value)
    if not result or len(set(result)) != len(result):
        raise ValueError("test_ids must be nonempty and unique")
    if any(_TEST_ID.fullmatch(item) is None for item in result):
        raise ValueError("test_ids must contain exact dotted identifiers")
    return result


@dataclass(frozen=True)
class WorkerRequest:
    schema_version: str
    test_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("unsupported worker request version")
        object.__setattr__(self, "test_ids", _test_ids(self.test_ids))

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "test_ids": list(self.test_ids)}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_dict(cls, value: object) -> WorkerRequest:
        data = _object(value, "WorkerRequest")
        if "schema_version" not in data or "test_ids" not in data:
            raise ValueError("WorkerRequest is missing required fields")
        return cls(_text(data["schema_version"], "schema_version"), _test_ids(data["test_ids"]))

    @classmethod
    def from_json(cls, value: str | bytes) -> WorkerRequest:
        if type(value) not in {str, bytes}:
            raise TypeError("worker request must be JSON text")
        return cls.from_dict(json.loads(value))


@dataclass(frozen=True)
class WorkerOutcome:
    test_id: str
    status: str
    failure_type: str | None = None

    def __post_init__(self) -> None:
        if _TEST_ID.fullmatch(_text(self.test_id, "test_id")) is None:
            raise ValueError("outcome test_id is invalid")
        if self.status not in _OUTCOME_STATUSES:
            raise ValueError("outcome status is invalid")
        if self.status == "passed" and self.failure_type is not None:
            raise ValueError("passed outcomes cannot have a failure type")
        if self.status != "passed":
            _text(self.failure_type, "failure_type")

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"test_id": self.test_id, "status": self.status}
        if self.failure_type is not None:
            result["failure_type"] = self.failure_type
        return result

    @classmethod
    def from_dict(cls, value: object) -> WorkerOutcome:
        data = _object(value, "WorkerOutcome")
        if "test_id" not in data or "status" not in data:
            raise ValueError("WorkerOutcome is missing required fields")
        failure_type = data.get("failure_type")
        if failure_type is not None and type(failure_type) is not str:
            raise TypeError("failure_type must be text")
        return cls(
            _text(data["test_id"], "test_id"),
            _text(data["status"], "status"),
            failure_type,
        )


@dataclass(frozen=True)
class WorkerResult:
    schema_version: str
    tests_run: int
    outcomes: tuple[WorkerOutcome, ...]

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("unsupported worker result version")
        if type(self.tests_run) is not int or self.tests_run < 0:
            raise ValueError("tests_run must be a nonnegative integer")
        if type(self.outcomes) is not tuple or not all(
            isinstance(item, WorkerOutcome) for item in self.outcomes
        ):
            raise TypeError("outcomes must be WorkerOutcome values")
        ids = tuple(item.test_id for item in self.outcomes)
        if len(ids) != len(set(ids)):
            raise ValueError("worker outcomes must have unique test IDs")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "tests_run": self.tests_run,
            "outcomes": [item.to_dict() for item in self.outcomes],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_dict(cls, value: object) -> WorkerResult:
        data = _object(value, "WorkerResult")
        required = ("schema_version", "tests_run", "outcomes")
        if any(key not in data for key in required):
            raise ValueError("WorkerResult is missing required fields")
        outcomes = data["outcomes"]
        if type(outcomes) is not list:
            raise TypeError("outcomes must be an array")
        return cls(
            _text(data["schema_version"], "schema_version"),
            data["tests_run"],  # type: ignore[arg-type]
            tuple(WorkerOutcome.from_dict(item) for item in outcomes),
        )

    @classmethod
    def from_json(cls, value: str | bytes) -> WorkerResult:
        if type(value) not in {str, bytes}:
            raise TypeError("worker result must be JSON text")
        return cls.from_dict(json.loads(value))


class RecordingTestResult(unittest.TestResult):
    """Capture semantic outcomes without serializing assertion text or tracebacks."""

    def __init__(self) -> None:
        super().__init__()
        self._outcomes: dict[str, WorkerOutcome] = {}

    def _record(self, test: unittest.case.TestCase, status: str, failure_type: str | None = None) -> None:
        self._outcomes[test.id()] = WorkerOutcome(test.id(), status, failure_type)

    def addSuccess(self, test: unittest.case.TestCase) -> None:  # noqa: N802
        super().addSuccess(test)
        self._record(test, "passed")

    def addFailure(self, test: unittest.case.TestCase, err: tuple[type[BaseException], BaseException, object]) -> None:  # noqa: N802
        super().addFailure(test, err)  # type: ignore[arg-type]
        self._record(test, "failed", "assertion")

    def addError(self, test: unittest.case.TestCase, err: tuple[type[BaseException], BaseException, object]) -> None:  # noqa: N802
        super().addError(test, err)  # type: ignore[arg-type]
        failure_type = "discovery" if type(test).__name__ == "_FailedTest" else "exception"
        self._record(test, "error", failure_type)

    def addSkip(self, test: unittest.case.TestCase, reason: str) -> None:  # noqa: N802
        super().addSkip(test, reason)
        self._record(test, "skipped", "skip")

    def addExpectedFailure(self, test: unittest.case.TestCase, err: tuple[type[BaseException], BaseException, object]) -> None:  # noqa: N802
        super().addExpectedFailure(test, err)  # type: ignore[arg-type]
        self._record(test, "expected_failure", "expected_failure")

    def addUnexpectedSuccess(self, test: unittest.case.TestCase) -> None:  # noqa: N802
        super().addUnexpectedSuccess(test)
        self._record(test, "unexpected_success", "unexpected_success")

    def addSubTest(self, test: unittest.case.TestCase, subtest: unittest.case._SubTest, err: tuple[type[BaseException], BaseException, object] | None) -> None:  # noqa: N802
        super().addSubTest(test, subtest, err)  # type: ignore[arg-type]
        if err is not None:
            status = "failed" if issubclass(err[0], test.failureException) else "error"
            failure_type = "assertion" if status == "failed" else "exception"
            self._record(test, status, failure_type)

    def ordered_outcomes(
        self,
        test_ids: tuple[str, ...],
        discovery_failures: frozenset[str],
    ) -> tuple[WorkerOutcome, ...]:
        return tuple(
            self._outcomes.get(test_id)
            or WorkerOutcome(test_id, "error", "discovery")
            for test_id in test_ids
            if test_id in self._outcomes or test_id in discovery_failures
        )


def _contains_failed_test(suite: unittest.TestSuite) -> bool:
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            if _contains_failed_test(item):
                return True
        elif type(item).__name__ == "_FailedTest":
            return True
    return False


def execute_worker_request(request: WorkerRequest) -> WorkerResult:
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        loader = unittest.TestLoader()
        loaded = tuple(loader.loadTestsFromName(test_id) for test_id in request.test_ids)
        discovery_failures = frozenset(
            test_id
            for test_id, suite in zip(request.test_ids, loaded, strict=True)
            if _contains_failed_test(suite)
        )
        suite = unittest.TestSuite(loaded)
        result = RecordingTestResult()
        suite.run(result)
    return WorkerResult(
        "1.0.0",
        result.testsRun,
        result.ordered_outcomes(request.test_ids, discovery_failures),
    )


def run_worker_files(request_path: str, result_path: str) -> None:
    """Read one controlled request and publish one structured result document."""
    request_file = Path(request_path)
    result_file = Path(result_path)
    try:
        if request_file.is_symlink():
            raise ValueError("worker request cannot be a symlink")
        request_file = request_file.resolve(strict=True)
        result_parent = result_file.parent.resolve(strict=True)
        if request_file.parent != result_parent or not result_parent.is_dir():
            raise ValueError("worker files must share one isolated directory")
        result_file = result_parent / result_file.name
    except OSError:
        raise ValueError("worker file boundary is invalid") from None
    request = WorkerRequest.from_json(request_file.read_bytes())
    result = execute_worker_request(request)
    with result_file.open("x", encoding="utf-8") as stream:
        stream.write(result.to_json())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one isolated P0 unittest check.")
    parser.add_argument("--request", required=True)
    parser.add_argument("--result", required=True)
    arguments = parser.parse_args(argv)
    try:
        run_worker_files(arguments.request, arguments.result)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
