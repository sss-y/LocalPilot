"""Immutable contract models for authoritative P0 acceptance evidence.

This module validates already-observed values.  It deliberately performs no
I/O, executes no checks, and makes no platform-support decisions.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

from .errors import FAILURE_ERROR_CODES, ErrorCode


_REQUIREMENT_ID = re.compile(r"^[0-9]+\.[0-9]+$")
_CHECK_ID = re.compile(r"^[a-z][a-z0-9]*(\.[a-z0-9][a-z0-9_-]*)+$")
_RFC3339 = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)
_SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
                     r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

class BaselineStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    INCOMPLETE = "incomplete"


class CheckStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"
    NOT_RUN = "not_run"
    INTERRUPTED = "interrupted"


class CoverageStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    INCOMPLETE = "incomplete"


class WorkingTreeState(str, Enum):
    CLEAN = "clean"
    DIRTY = "dirty"
    UNKNOWN = "unknown"


class NetworkMode(str, Enum):
    OFFLINE = "offline"


def _expect_dict(value: object, name: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise TypeError(f"{name} must be an object")
    if any(type(key) is not str for key in value):
        raise TypeError(f"{name} keys must be strings")
    return value


def _known_fields(data: object, required: Sequence[str], name: str) -> dict[str, Any]:
    source = _expect_dict(data, name)
    missing = [key for key in required if key not in source]
    if missing:
        raise ValueError(f"{name} missing required fields: {', '.join(missing)}")
    # IC-10 14.3 requires same-major consumers to ignore future optional fields.
    return {key: source[key] for key in required}


def _nonempty_string(value: object, name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be a string")
    if not value.strip():
        raise ValueError(f"{name} must not be empty")
    return value


def _boolean(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a boolean")
    return value


def _nonnegative_integer(value: object, name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")
    return value


def _enum(value: object, enum_type: type[Enum], name: str) -> Any:
    if type(value) is not str:
        raise TypeError(f"{name} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"invalid {name}: {value!r}") from exc


def _require_enum(value: object, enum_type: type[Enum], name: str) -> None:
    if not isinstance(value, enum_type):
        raise TypeError(f"{name} must be {enum_type.__name__}")


def _requirement_id(value: object) -> str:
    result = _nonempty_string(value, "requirement_id")
    if _REQUIREMENT_ID.fullmatch(result) is None:
        raise ValueError(f"invalid requirement_id: {result!r}")
    return result


def _check_id(value: object) -> str:
    result = _nonempty_string(value, "check_id")
    if _CHECK_ID.fullmatch(result) is None:
        raise ValueError(f"invalid check_id: {result!r}")
    return result


def _timestamp(value: object, name: str) -> str:
    result = _nonempty_string(value, name)
    if _RFC3339.fullmatch(result) is None:
        raise ValueError(f"{name} must be an RFC 3339 timestamp with timezone")
    try:
        datetime.fromisoformat(result.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid RFC 3339 timestamp") from exc
    return result


def _as_string_tuple(value: object, name: str, *, nonempty: bool = False) -> tuple[str, ...]:
    if type(value) not in {list, tuple}:
        raise TypeError(f"{name} must be an array")
    result = tuple(_nonempty_string(item, f"{name} item") for item in value)
    if nonempty and not result:
        raise ValueError(f"{name} must not be empty")
    return result


def _freeze_json(value: object, name: str = "JSON value") -> object:
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{name} must contain finite JSON numbers")
        return value
    if type(value) in {list, tuple}:
        return tuple(_freeze_json(item, name) for item in value)
    if type(value) in {dict, MappingProxyType}:
        if any(type(key) is not str for key in value):
            raise ValueError(f"{name} JSON object keys must be strings")
        return MappingProxyType({key: _freeze_json(item, name) for key, item in value.items()})
    raise ValueError(f"{name} must contain only JSON-serializable values")


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True)
class Diagnostic:
    code: ErrorCode
    message: str
    failure_type: str
    target: str
    recoverable: bool
    details: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        self._validate()
        if self.details is not None:
            object.__setattr__(self, "details", _freeze_json(dict(self.details), "details"))

    def _validate(self) -> None:
        _require_enum(self.code, ErrorCode, "code")
        _nonempty_string(self.message, "message")
        _nonempty_string(self.failure_type, "failure_type")
        _nonempty_string(self.target, "target")
        _boolean(self.recoverable, "recoverable")
        if self.details is not None:
            _freeze_json(dict(self.details) if isinstance(self.details, Mapping) else self.details, "details")

    def to_dict(self) -> dict[str, object]:
        self._validate()
        result: dict[str, object] = {
            "code": self.code.value,
            "message": self.message,
            "failure_type": self.failure_type,
            "target": self.target,
            "recoverable": self.recoverable,
        }
        if self.details is not None:
            result["details"] = _thaw_json(self.details)
        return result

    @classmethod
    def from_dict(cls, data: object) -> Diagnostic:
        source = _expect_dict(data, "Diagnostic")
        required = ("code", "message", "failure_type", "target", "recoverable")
        values = _known_fields(source, required, "Diagnostic")
        return cls(
            code=_enum(values["code"], ErrorCode, "code"),
            message=_nonempty_string(values["message"], "message"),
            failure_type=_nonempty_string(values["failure_type"], "failure_type"),
            target=_nonempty_string(values["target"], "target"),
            recoverable=_boolean(values["recoverable"], "recoverable"),
            details=source.get("details"),
        )


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    title: str
    required: bool
    requirement_ids: tuple[str, ...]
    status: CheckStatus
    started_at: str
    finished_at: str
    duration_ms: int
    target: str
    diagnostics: tuple[Diagnostic, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    observed: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        self._validate()
        if self.observed is not None:
            object.__setattr__(self, "observed", _freeze_json(dict(self.observed), "observed"))

    def _validate(self) -> None:
        _check_id(self.check_id)
        _nonempty_string(self.title, "title")
        _boolean(self.required, "required")
        ids = _as_string_tuple(self.requirement_ids, "requirement_ids", nonempty=True)
        for item in ids:
            _requirement_id(item)
        if len(set(ids)) != len(ids):
            raise ValueError("requirement_ids must not contain duplicates")
        _require_enum(self.status, CheckStatus, "status")
        started = _timestamp(self.started_at, "started_at")
        finished = _timestamp(self.finished_at, "finished_at")
        if datetime.fromisoformat(finished.replace("Z", "+00:00")) < datetime.fromisoformat(
            started.replace("Z", "+00:00")
        ):
            raise ValueError("finished_at must not precede started_at")
        _nonnegative_integer(self.duration_ms, "duration_ms")
        _nonempty_string(self.target, "target")
        if type(self.diagnostics) is not tuple or not all(
            isinstance(item, Diagnostic) for item in self.diagnostics
        ):
            raise TypeError("diagnostics must be a tuple of Diagnostic")
        if self.status is not CheckStatus.PASSED and not self.diagnostics:
            raise ValueError("non-passed checks require at least one diagnostic")
        diagnostic_codes = {item.code for item in self.diagnostics}
        if self.status in {CheckStatus.FAILED, CheckStatus.ERROR}:
            if not diagnostic_codes & FAILURE_ERROR_CODES:
                raise ValueError("failed and error checks require a failure diagnostic")
        elif self.status is CheckStatus.SKIPPED:
            if (
                ErrorCode.CHECK_SKIPPED not in diagnostic_codes
                or diagnostic_codes & FAILURE_ERROR_CODES
            ):
                raise ValueError("skipped checks require only incomplete diagnostics")
        elif self.status is CheckStatus.NOT_RUN:
            if (
                not diagnostic_codes
                & {ErrorCode.RESULT_MISSING, ErrorCode.CHECK_INTERRUPTED}
                or diagnostic_codes & FAILURE_ERROR_CODES
            ):
                raise ValueError("not_run checks require only incomplete diagnostics")
        elif self.status is CheckStatus.INTERRUPTED:
            if (
                ErrorCode.CHECK_INTERRUPTED not in diagnostic_codes
                or diagnostic_codes & FAILURE_ERROR_CODES
            ):
                raise ValueError("interrupted checks require only incomplete diagnostics")
        _as_string_tuple(self.evidence_refs, "evidence_refs")
        if self.observed is not None:
            _freeze_json(dict(self.observed) if isinstance(self.observed, Mapping) else self.observed, "observed")

    def to_dict(self) -> dict[str, object]:
        self._validate()
        result: dict[str, object] = {
            "check_id": self.check_id, "title": self.title, "required": self.required,
            "requirement_ids": list(self.requirement_ids), "status": self.status.value,
            "started_at": self.started_at, "finished_at": self.finished_at,
            "duration_ms": self.duration_ms, "target": self.target,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "evidence_refs": list(self.evidence_refs),
        }
        if self.observed is not None:
            result["observed"] = _thaw_json(self.observed)
        return result

    @classmethod
    def from_dict(cls, data: object) -> CheckResult:
        source = _expect_dict(data, "CheckResult")
        fields = (
            "check_id", "title", "required", "requirement_ids", "status", "started_at",
            "finished_at", "duration_ms", "target", "diagnostics", "evidence_refs",
        )
        values = _known_fields(source, fields, "CheckResult")
        diagnostics = values["diagnostics"]
        if type(diagnostics) is not list:
            raise TypeError("diagnostics must be an array")
        return cls(
            check_id=_check_id(values["check_id"]),
            title=_nonempty_string(values["title"], "title"),
            required=_boolean(values["required"], "required"),
            requirement_ids=tuple(_requirement_id(item) for item in _as_string_tuple(values["requirement_ids"], "requirement_ids", nonempty=True)),
            status=_enum(values["status"], CheckStatus, "status"),
            started_at=_timestamp(values["started_at"], "started_at"),
            finished_at=_timestamp(values["finished_at"], "finished_at"),
            duration_ms=_nonnegative_integer(values["duration_ms"], "duration_ms"),
            target=_nonempty_string(values["target"], "target"),
            diagnostics=tuple(Diagnostic.from_dict(item) for item in diagnostics),
            evidence_refs=_as_string_tuple(values["evidence_refs"], "evidence_refs"),
            observed=source.get("observed"),
        )


@dataclass(frozen=True)
class EnvironmentSnapshot:
    revision: str
    repository_root: str
    working_tree_state: WorkingTreeState
    runtime_name: str
    runtime_version: str
    os: str
    architecture: str
    dependency_fingerprint: str
    code_origins: Mapping[str, str]
    network_mode: NetworkMode
    personal_credentials_loaded: bool
    supported: bool
    violations: tuple[Diagnostic, ...] = ()

    def __post_init__(self) -> None:
        self._validate()
        object.__setattr__(self, "code_origins", MappingProxyType(dict(self.code_origins)))

    def _validate(self) -> None:
        for name in ("revision", "repository_root", "runtime_name", "runtime_version", "os", "architecture", "dependency_fingerprint"):
            _nonempty_string(getattr(self, name), name)
        _require_enum(self.working_tree_state, WorkingTreeState, "working_tree_state")
        _require_enum(self.network_mode, NetworkMode, "network_mode")
        if not isinstance(self.code_origins, Mapping) or any(
            type(key) is not str or type(value) is not str or not key or not value
            for key, value in self.code_origins.items()
        ):
            raise TypeError("code_origins must map nonempty strings to nonempty strings")
        _boolean(self.personal_credentials_loaded, "personal_credentials_loaded")
        _boolean(self.supported, "supported")
        if type(self.violations) is not tuple or not all(isinstance(item, Diagnostic) for item in self.violations):
            raise TypeError("violations must be a tuple of Diagnostic")
        has_unsupported_diagnostic = any(
            item.code is ErrorCode.ENV_UNSUPPORTED for item in self.violations
        )
        if not self.supported and not has_unsupported_diagnostic:
            raise ValueError(
                "supported=false requires a P0_ENV_UNSUPPORTED violation"
            )
        if self.supported and has_unsupported_diagnostic:
            raise ValueError(
                "supported=true cannot contain a P0_ENV_UNSUPPORTED violation"
            )

    def to_dict(self) -> dict[str, object]:
        self._validate()
        return {
            "revision": self.revision, "repository_root": self.repository_root,
            "working_tree_state": self.working_tree_state.value,
            "runtime_name": self.runtime_name, "runtime_version": self.runtime_version,
            "os": self.os, "architecture": self.architecture,
            "dependency_fingerprint": self.dependency_fingerprint,
            "code_origins": dict(self.code_origins), "network_mode": self.network_mode.value,
            "personal_credentials_loaded": self.personal_credentials_loaded,
            "supported": self.supported,
            "violations": [item.to_dict() for item in self.violations],
        }

    @classmethod
    def from_dict(cls, data: object) -> EnvironmentSnapshot:
        fields = (
            "revision", "repository_root", "working_tree_state", "runtime_name", "runtime_version",
            "os", "architecture", "dependency_fingerprint", "code_origins", "network_mode",
            "personal_credentials_loaded", "supported", "violations",
        )
        values = _known_fields(data, fields, "EnvironmentSnapshot")
        origins = _expect_dict(values["code_origins"], "code_origins")
        violations = values["violations"]
        if type(violations) is not list:
            raise TypeError("violations must be an array")
        return cls(
            revision=_nonempty_string(values["revision"], "revision"),
            repository_root=_nonempty_string(values["repository_root"], "repository_root"),
            working_tree_state=_enum(values["working_tree_state"], WorkingTreeState, "working_tree_state"),
            runtime_name=_nonempty_string(values["runtime_name"], "runtime_name"),
            runtime_version=_nonempty_string(values["runtime_version"], "runtime_version"),
            os=_nonempty_string(values["os"], "os"), architecture=_nonempty_string(values["architecture"], "architecture"),
            dependency_fingerprint=_nonempty_string(values["dependency_fingerprint"], "dependency_fingerprint"),
            code_origins={_nonempty_string(key, "code origin key"): _nonempty_string(value, "code origin") for key, value in origins.items()},
            network_mode=_enum(values["network_mode"], NetworkMode, "network_mode"),
            personal_credentials_loaded=_boolean(values["personal_credentials_loaded"], "personal_credentials_loaded"),
            supported=_boolean(values["supported"], "supported"),
            violations=tuple(Diagnostic.from_dict(item) for item in violations),
        )


@dataclass(frozen=True)
class ResultSummary:
    required_total: int = 0
    passed: int = 0
    failed: int = 0
    error: int = 0
    skipped: int = 0
    not_run: int = 0
    interrupted: int = 0

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        values = [getattr(self, field_name) for field_name in self.__dataclass_fields__]
        for field_name, value in zip(self.__dataclass_fields__, values):
            _nonnegative_integer(value, field_name)
        if sum(values[1:]) != self.required_total:
            raise ValueError("summary status counts must equal required_total")

    @classmethod
    def from_checks(cls, checks: Iterable[CheckResult]) -> ResultSummary:
        required = tuple(item for item in checks if item.required)
        counts = {status.value: 0 for status in CheckStatus}
        for item in required:
            counts[item.status.value] += 1
        return cls(required_total=len(required), **counts)

    def to_dict(self) -> dict[str, int]:
        self._validate()
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, data: object) -> ResultSummary:
        fields = tuple(cls.__dataclass_fields__)
        values = _known_fields(data, fields, "ResultSummary")
        return cls(**{name: _nonnegative_integer(values[name], name) for name in fields})


@dataclass(frozen=True)
class RequirementCoverage:
    requirement_id: str
    status: CoverageStatus
    check_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        _requirement_id(self.requirement_id)
        _require_enum(self.status, CoverageStatus, "status")
        check_ids = _as_string_tuple(self.check_ids, "check_ids", nonempty=True)
        for item in check_ids:
            _check_id(item)
        if len(set(check_ids)) != len(check_ids):
            raise ValueError("check_ids must not contain duplicates")
        _as_string_tuple(self.evidence_refs, "evidence_refs", nonempty=True)

    def to_dict(self) -> dict[str, object]:
        self._validate()
        return {"requirement_id": self.requirement_id, "status": self.status.value,
                "check_ids": list(self.check_ids), "evidence_refs": list(self.evidence_refs)}

    @classmethod
    def from_dict(cls, data: object) -> RequirementCoverage:
        fields = ("requirement_id", "status", "check_ids", "evidence_refs")
        values = _known_fields(data, fields, "RequirementCoverage")
        return cls(
            requirement_id=_requirement_id(values["requirement_id"]),
            status=_enum(values["status"], CoverageStatus, "status"),
            check_ids=tuple(_check_id(item) for item in _as_string_tuple(values["check_ids"], "check_ids", nonempty=True)),
            evidence_refs=_as_string_tuple(values["evidence_refs"], "evidence_refs", nonempty=True),
        )


@dataclass(frozen=True)
class BaselineReport:
    schema_version: str
    run_id: str
    revision: str
    manifest_digest: str
    started_at: str
    finished_at: str
    duration_ms: int
    mode: NetworkMode
    environment: EnvironmentSnapshot
    overall_status: BaselineStatus
    exit_code: int
    acceptance_eligible: bool
    summary: ResultSummary
    checks: tuple[CheckResult, ...]
    requirement_coverage: tuple[RequirementCoverage, ...]
    run_diagnostics: tuple[Diagnostic, ...]
    redaction: Mapping[str, object]

    def __post_init__(self) -> None:
        self._validate()
        object.__setattr__(
            self,
            "redaction",
            MappingProxyType(
                {
                    "enabled": self.redaction["enabled"],
                    "matched_values": self.redaction["matched_values"],
                }
            ),
        )

    def _validate(self) -> None:
        if type(self.schema_version) is not str or _SEMVER.fullmatch(self.schema_version) is None:
            raise ValueError("schema_version must be semantic version text")
        if self.schema_version != "1.0.0":
            raise ValueError("initial BaselineReport schema_version must be 1.0.0")
        if type(self.run_id) is not str or _RUN_ID.fullmatch(self.run_id) is None:
            raise ValueError("run_id must be a non-sensitive stable identifier")
        _nonempty_string(self.revision, "revision")
        _nonempty_string(self.manifest_digest, "manifest_digest")
        started = _timestamp(self.started_at, "started_at")
        finished = _timestamp(self.finished_at, "finished_at")
        if datetime.fromisoformat(finished.replace("Z", "+00:00")) < datetime.fromisoformat(started.replace("Z", "+00:00")):
            raise ValueError("finished_at must not precede started_at")
        _nonnegative_integer(self.duration_ms, "duration_ms")
        _require_enum(self.mode, NetworkMode, "mode")
        if not isinstance(self.environment, EnvironmentSnapshot):
            raise TypeError("environment must be EnvironmentSnapshot")
        if self.environment.revision != self.revision:
            raise ValueError("environment revision must match report revision")
        _require_enum(self.overall_status, BaselineStatus, "overall_status")
        if type(self.exit_code) is not int or self.exit_code != {
            BaselineStatus.SUCCESS: 0, BaselineStatus.FAILURE: 1,
            BaselineStatus.INCOMPLETE: 2,
        }[self.overall_status]:
            raise ValueError("exit_code must match overall_status")
        _boolean(self.acceptance_eligible, "acceptance_eligible")
        if not isinstance(self.summary, ResultSummary):
            raise TypeError("summary must be ResultSummary")
        if type(self.checks) is not tuple or not all(isinstance(item, CheckResult) for item in self.checks):
            raise TypeError("checks must be a tuple of CheckResult")
        if type(self.requirement_coverage) is not tuple or not all(isinstance(item, RequirementCoverage) for item in self.requirement_coverage):
            raise TypeError("requirement_coverage must be a tuple of RequirementCoverage")
        if type(self.run_diagnostics) is not tuple or not all(isinstance(item, Diagnostic) for item in self.run_diagnostics):
            raise TypeError("run_diagnostics must be a tuple of Diagnostic")
        if self.summary != ResultSummary.from_checks(self.checks):
            raise ValueError("summary must match required checks")
        check_ids = [item.check_id for item in self.checks]
        if len(set(check_ids)) != len(check_ids):
            raise ValueError("checks must have unique check_id values")
        requirement_ids = [item.requirement_id for item in self.requirement_coverage]
        if len(set(requirement_ids)) != len(requirement_ids):
            raise ValueError("requirement_coverage must have unique requirement_id values")
        known_checks = set(check_ids)
        if any(not set(item.check_ids).issubset(known_checks) for item in self.requirement_coverage):
            raise ValueError("requirement coverage references an unknown check_id")
        checks_by_id = {item.check_id: item for item in self.checks}
        if any(
            any(
                coverage.requirement_id not in checks_by_id[check_id].requirement_ids
                for check_id in coverage.check_ids
            )
            for coverage in self.requirement_coverage
        ):
            raise ValueError(
                "every referenced check must declare the coverage requirement_id"
            )
        redaction = dict(self.redaction) if isinstance(self.redaction, Mapping) else self.redaction
        _expect_dict(redaction, "redaction")
        if not {"enabled", "matched_values"}.issubset(redaction):
            raise ValueError("redaction requires enabled and matched_values fields")
        if not _boolean(redaction["enabled"], "redaction.enabled"):
            raise ValueError("authoritative reports require redaction enabled")
        _nonnegative_integer(redaction["matched_values"], "redaction.matched_values")

        required_statuses = {item.status for item in self.checks if item.required}
        definite_failure = bool(
            required_statuses & {CheckStatus.FAILED, CheckStatus.ERROR}
            or any(item.code in FAILURE_ERROR_CODES for item in (*self.environment.violations, *self.run_diagnostics))
        )
        incomplete_condition = bool(
            required_statuses
            & {CheckStatus.SKIPPED, CheckStatus.NOT_RUN, CheckStatus.INTERRUPTED}
            or any(
                item.code not in FAILURE_ERROR_CODES
                for item in (*self.environment.violations, *self.run_diagnostics)
            )
            or self.environment.working_tree_state is not WorkingTreeState.CLEAN
            or self.environment.personal_credentials_loaded
        )
        if definite_failure and self.overall_status is not BaselineStatus.FAILURE:
            raise ValueError("failure conditions require overall_status=failure")
        if self.overall_status is BaselineStatus.FAILURE and not definite_failure:
            raise ValueError("failure report requires a determinate failure")
        if not definite_failure and incomplete_condition and self.overall_status is not BaselineStatus.INCOMPLETE:
            raise ValueError("incomplete conditions require overall_status=incomplete")
        if self.overall_status is BaselineStatus.INCOMPLETE and not incomplete_condition:
            raise ValueError("incomplete report requires an observed incomplete condition")
        if self.acceptance_eligible != (self.overall_status is BaselineStatus.SUCCESS):
            raise ValueError("acceptance_eligible is true only for authoritative success")
        if self.overall_status is BaselineStatus.SUCCESS:
            if required_statuses != {CheckStatus.PASSED} or not self.checks:
                raise ValueError("success requires every required check to pass")
            if self.mode is not NetworkMode.OFFLINE or self.environment.network_mode is not NetworkMode.OFFLINE:
                raise ValueError("success requires offline mode")
            if self.environment.working_tree_state is not WorkingTreeState.CLEAN:
                raise ValueError("success requires a clean working tree")
            if not self.environment.supported or self.environment.personal_credentials_loaded:
                raise ValueError("success requires a supported credential-free environment")

    def to_dict(self) -> dict[str, object]:
        self._validate()
        return {
            "schema_version": self.schema_version, "run_id": self.run_id,
            "revision": self.revision, "manifest_digest": self.manifest_digest,
            "started_at": self.started_at, "finished_at": self.finished_at,
            "duration_ms": self.duration_ms, "mode": self.mode.value,
            "environment": self.environment.to_dict(), "overall_status": self.overall_status.value,
            "exit_code": self.exit_code, "acceptance_eligible": self.acceptance_eligible,
            "summary": self.summary.to_dict(), "checks": [item.to_dict() for item in self.checks],
            "requirement_coverage": [item.to_dict() for item in self.requirement_coverage],
            "run_diagnostics": [item.to_dict() for item in self.run_diagnostics],
            "redaction": _thaw_json(self.redaction),
        }

    @classmethod
    def from_dict(cls, data: object) -> BaselineReport:
        fields = (
            "schema_version", "run_id", "revision", "manifest_digest", "started_at",
            "finished_at", "duration_ms", "mode", "environment", "overall_status",
            "exit_code", "acceptance_eligible", "summary", "checks",
            "requirement_coverage", "run_diagnostics", "redaction",
        )
        values = _known_fields(data, fields, "BaselineReport")
        for name in ("checks", "requirement_coverage", "run_diagnostics"):
            if type(values[name]) is not list:
                raise TypeError(f"{name} must be an array")
        return cls(
            schema_version=_nonempty_string(values["schema_version"], "schema_version"),
            run_id=_nonempty_string(values["run_id"], "run_id"),
            revision=_nonempty_string(values["revision"], "revision"),
            manifest_digest=_nonempty_string(values["manifest_digest"], "manifest_digest"),
            started_at=_timestamp(values["started_at"], "started_at"),
            finished_at=_timestamp(values["finished_at"], "finished_at"),
            duration_ms=_nonnegative_integer(values["duration_ms"], "duration_ms"),
            mode=_enum(values["mode"], NetworkMode, "mode"),
            environment=EnvironmentSnapshot.from_dict(values["environment"]),
            overall_status=_enum(values["overall_status"], BaselineStatus, "overall_status"),
            exit_code=_nonnegative_integer(values["exit_code"], "exit_code"),
            acceptance_eligible=_boolean(values["acceptance_eligible"], "acceptance_eligible"),
            summary=ResultSummary.from_dict(values["summary"]),
            checks=tuple(CheckResult.from_dict(item) for item in values["checks"]),
            requirement_coverage=tuple(RequirementCoverage.from_dict(item) for item in values["requirement_coverage"]),
            run_diagnostics=tuple(Diagnostic.from_dict(item) for item in values["run_diagnostics"]),
            redaction=_expect_dict(values["redaction"], "redaction"),
        )
