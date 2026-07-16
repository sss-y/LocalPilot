"""Typed, fail-closed loader for the P0 test asset manifest.

This validates the approved manifest contract.  Asset existence, Git tracking,
full Requirement coverage, and digest calculation belong to ManifestIntegrity.
"""

from __future__ import annotations

import json
import hashlib
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .errors import ErrorCode
from .models import Diagnostic


_SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_CHECK_ID = re.compile(r"^[a-z][a-z0-9]*(\.[a-z0-9][a-z0-9_-]*)+$")
_TEST_ID = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*\.){2,}[A-Za-z_][A-Za-z0-9_]*$")
REQUIREMENT_IDS = tuple(
    f"{group}.{criterion}"
    for group, total in {1: 5, 2: 6, 3: 6, 4: 6, 5: 6, 6: 9, 7: 6, 8: 6, 9: 6}.items()
    for criterion in range(1, total + 1)
)
_VALID_REQUIREMENTS = frozenset(REQUIREMENT_IDS)
_APPROVED_ENVIRONMENT = {
    "environment_id": "darwin-arm64-cpython-3.12",
    "os": "Darwin",
    "architecture": "arm64",
    "runtime_name": "CPython",
    "runtime_version": "3.12.x",
}
_SCHEMA_ANNOTATIONS = frozenset({
    "$schema", "$id", "$defs", "title", "description", "$comment",
    "default", "examples", "deprecated", "readOnly", "writeOnly",
})
_SCHEMA_ASSERTIONS = frozenset({
    "$ref", "type", "required", "properties", "additionalProperties",
    "items", "enum", "const", "pattern", "minLength", "minItems",
    "maxItems", "minimum", "uniqueItems", "allOf", "anyOf", "not",
    "if", "then", "format", "contains", "minContains", "maxContains",
})


class ManifestValidationError(ValueError):
    """Stable failure boundary for malformed or unsupported manifests."""

    code = ErrorCode.MANIFEST_INVALID

    def __init__(self, message: str = "P0 manifest could not be validated.") -> None:
        super().__init__(message)

    def to_diagnostic(self) -> Diagnostic:
        return Diagnostic(
            code=self.code,
            message="Required check manifest could not be validated.",
            failure_type="manifest",
            target="localpilot.p0-baseline",
            recoverable=False,
        )


class ManifestIntegrityError(ValueError):
    """Stable failure boundary for untrusted or incomplete manifest assets."""

    def __init__(self, code: ErrorCode, target: str) -> None:
        self.code = code
        self.target = target
        super().__init__("P0 manifest integrity validation failed.")

    def to_diagnostic(self) -> Diagnostic:
        failure_type = "asset" if self.code is ErrorCode.ASSET_MISSING else "manifest"
        return Diagnostic(
            code=self.code,
            message="Required manifest integrity validation failed.",
            failure_type=failure_type,
            target=self.target,
            recoverable=False,
        )


class _SchemaMismatch(Exception):
    pass


def _invalid(message: str) -> None:
    raise ManifestValidationError(message)


def _object(value: object, fields: tuple[str, ...], name: str) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid(f"{name} must be an object")
    missing = [field for field in fields if field not in value]
    if missing:
        _invalid(f"{name} is missing required fields")
    return value


def _array(value: object, name: str, *, nonempty: bool = False) -> list[Any]:
    if type(value) is not list:
        _invalid(f"{name} must be an array")
    if nonempty and not value:
        _invalid(f"{name} must not be empty")
    return value


def _string(value: object, name: str) -> str:
    if type(value) is not str or not value.strip():
        _invalid(f"{name} must be a nonempty string")
    return value


def _boolean(value: object, name: str) -> bool:
    if type(value) is not bool:
        _invalid(f"{name} must be a boolean")
    return value


def _choice(value: object, choices: frozenset[str], name: str) -> str:
    result = _string(value, name)
    if result not in choices:
        _invalid(f"{name} has an unsupported value")
    return result


def _relative_path(value: object, name: str) -> str:
    result = _string(value, name)
    parts = result.split("/")
    if (
        result.startswith("/")
        or re.match(r"^[A-Za-z]:/", result) is not None
        or "\\" in result
        or any(part in {"", ".", ".."} for part in parts)
    ):
        _invalid(f"{name} must be a repository-relative POSIX path")
    return result


def _requirement_ids(value: object, name: str) -> tuple[str, ...]:
    items = _array(value, name, nonempty=True)
    result = tuple(_string(item, f"{name} item") for item in items)
    if len(set(result)) != len(result) or any(item not in _VALID_REQUIREMENTS for item in result):
        _invalid(f"{name} contains an invalid RequirementId")
    return result


def _string_tuple(value: object, name: str, *, nonempty: bool = False) -> tuple[str, ...]:
    items = _array(value, name, nonempty=nonempty)
    result = tuple(_string(item, f"{name} item") for item in items)
    if len(set(result)) != len(result):
        _invalid(f"{name} must not contain duplicates")
    return result


def _version(value: object, name: str) -> tuple[str, int]:
    result = _string(value, name)
    match = _SEMVER.fullmatch(result)
    if match is None:
        _invalid(f"{name} must be semantic version text")
    return result, int(match.group(1))


@dataclass(frozen=True)
class AssetDescriptor:
    path: str
    kind: str
    required: bool
    requirement_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "kind": self.kind,
            "required": self.required,
            "requirement_ids": list(self.requirement_ids),
        }


@dataclass(frozen=True)
class CheckDescriptor:
    check_id: str
    title: str
    category: str
    required: bool
    requirement_ids: tuple[str, ...]
    asset_refs: tuple[str, ...]
    network_policy: str
    timeout_ms: int
    migration_status: str
    adapter: str
    test_ids: tuple[str, ...]
    allow_loopback: bool

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "check_id": self.check_id,
            "title": self.title,
            "category": self.category,
            "required": self.required,
            "requirement_ids": list(self.requirement_ids),
            "asset_refs": list(self.asset_refs),
            "network_policy": self.network_policy,
            "timeout_ms": self.timeout_ms,
            "migration_status": self.migration_status,
            "adapter": self.adapter,
            "allow_loopback": self.allow_loopback,
        }
        if self.adapter == "unittest":
            result["test_ids"] = list(self.test_ids)
        return result


@dataclass(frozen=True)
class EnvironmentConstraint:
    environment_id: str
    os: str
    architecture: str
    runtime_name: str
    runtime_version: str

    def to_dict(self) -> dict[str, str]:
        return {
            "environment_id": self.environment_id,
            "os": self.os,
            "architecture": self.architecture,
            "runtime_name": self.runtime_name,
            "runtime_version": self.runtime_version,
        }


@dataclass(frozen=True)
class BaselineManifest:
    schema_version: str
    manifest_id: str
    required_assets: tuple[AssetDescriptor, ...]
    checks: tuple[CheckDescriptor, ...]
    supported_environments: tuple[EnvironmentConstraint, ...]
    dependency_lock: str
    dependency_fingerprint: str
    evidence_schema_version: str
    supported_environment_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "required_assets": [item.to_dict() for item in self.required_assets],
            "checks": [item.to_dict() for item in self.checks],
            "supported_environments": [item.to_dict() for item in self.supported_environments],
            "dependency_lock": self.dependency_lock,
            "dependency_fingerprint": self.dependency_fingerprint,
            "evidence_schema_version": self.evidence_schema_version,
            "supported_environment_id": self.supported_environment_id,
        }


@dataclass(frozen=True)
class RequirementMapping:
    requirement_id: str
    check_ids: tuple[str, ...]


@dataclass(frozen=True)
class ManifestIntegrity:
    asset_paths: tuple[str, ...]
    requirement_coverage: tuple[RequirementMapping, ...]
    manifest_digest: str


def _asset(value: object) -> AssetDescriptor:
    fields = ("path", "kind", "required", "requirement_ids")
    data = _object(value, fields, "AssetDescriptor")
    required = _boolean(data["required"], "AssetDescriptor.required")
    if not required:
        _invalid("P0 assets must be required")
    return AssetDescriptor(
        path=_relative_path(data["path"], "AssetDescriptor.path"),
        kind=_choice(data["kind"], frozenset({"test", "fixture", "config", "documentation"}), "AssetDescriptor.kind"),
        required=required,
        requirement_ids=_requirement_ids(data["requirement_ids"], "AssetDescriptor.requirement_ids"),
    )


def _check(value: object) -> CheckDescriptor:
    fields = (
        "check_id", "title", "category", "required", "requirement_ids",
        "asset_refs", "network_policy", "timeout_ms", "migration_status",
        "adapter", "allow_loopback",
    )
    data = _object(value, fields, "CheckDescriptor")
    check_id = _string(data["check_id"], "CheckDescriptor.check_id")
    if _CHECK_ID.fullmatch(check_id) is None:
        _invalid("CheckDescriptor.check_id has an invalid format")
    required = _boolean(data["required"], "CheckDescriptor.required")
    if not required:
        _invalid("P0 checks must be required")
    timeout_ms = data["timeout_ms"]
    if type(timeout_ms) is not int or timeout_ms <= 0:
        _invalid("CheckDescriptor.timeout_ms must be a positive integer")
    adapter = _choice(data["adapter"], frozenset({"unittest", "internal"}), "CheckDescriptor.adapter")
    if "command" in data or "shell_command" in data:
        _invalid("check commands are not permitted")
    if adapter == "unittest" and "test_ids" not in data:
        _invalid("unittest checks require exact test_ids")
    if adapter == "internal" and "test_ids" in data:
        _invalid("internal checks must not declare unittest test_ids")
    test_ids = _string_tuple(
        data.get("test_ids", []),
        "CheckDescriptor.test_ids",
        nonempty=adapter == "unittest",
    )
    if adapter == "unittest" and any(_TEST_ID.fullmatch(item) is None for item in test_ids):
        _invalid("unittest test_ids must be exact dotted test identifiers")
    allow_loopback = _boolean(data["allow_loopback"], "CheckDescriptor.allow_loopback")
    if allow_loopback:
        _invalid("loopback requires a separately approved controlled fixture")
    return CheckDescriptor(
        check_id=check_id,
        title=_string(data["title"], "CheckDescriptor.title"),
        category=_choice(data["category"], frozenset({"asset", "environment", "discovery", "behavior", "documentation", "scope"}), "CheckDescriptor.category"),
        required=required,
        requirement_ids=_requirement_ids(data["requirement_ids"], "CheckDescriptor.requirement_ids"),
        asset_refs=tuple(_relative_path(item, "CheckDescriptor.asset_refs item") for item in _array(data["asset_refs"], "CheckDescriptor.asset_refs")),
        network_policy=_choice(data["network_policy"], frozenset({"offline"}), "CheckDescriptor.network_policy"),
        timeout_ms=timeout_ms,
        migration_status=_choice(data["migration_status"], frozenset({"stable", "transitional"}), "CheckDescriptor.migration_status"),
        adapter=adapter,
        test_ids=test_ids,
        allow_loopback=allow_loopback,
    )


def _environment(value: object) -> EnvironmentConstraint:
    fields = ("environment_id", "os", "architecture", "runtime_name", "runtime_version")
    data = _object(value, fields, "EnvironmentConstraint")
    values = {field: _string(data[field], f"EnvironmentConstraint.{field}") for field in fields}
    if values != _APPROVED_ENVIRONMENT:
        _invalid("supported environment has not completed independent approval")
    return EnvironmentConstraint(**values)


def parse_manifest(data: object) -> BaselineManifest:
    fields = (
        "schema_version", "manifest_id", "required_assets", "checks",
        "supported_environments", "dependency_lock", "dependency_fingerprint",
        "evidence_schema_version", "supported_environment_id",
    )
    try:
        validate_json_schema(
            data,
            Path(__file__).with_name("schemas") / "manifest.schema.json",
        )
        source = _object(data, fields, "BaselineManifest")
        schema_version, schema_major = _version(source["schema_version"], "schema_version")
        evidence_version, evidence_major = _version(source["evidence_schema_version"], "evidence_schema_version")
        if schema_major != 1 or evidence_major != schema_major:
            _invalid("manifest and evidence schemas must use supported major version 1")
        manifest_id = _string(source["manifest_id"], "manifest_id")
        if manifest_id != "localpilot.p0-baseline":
            _invalid("manifest_id must identify the LocalPilot P0 baseline")
        assets = tuple(_asset(item) for item in _array(source["required_assets"], "required_assets", nonempty=True))
        if len({item.path for item in assets}) != len(assets):
            _invalid("required asset paths must be unique")
        checks = tuple(_check(item) for item in _array(source["checks"], "checks", nonempty=True))
        if len({item.check_id for item in checks}) != len(checks):
            _invalid("check_id values must be unique")
        environments = tuple(_environment(item) for item in _array(source["supported_environments"], "supported_environments", nonempty=True))
        if len(environments) != 1:
            _invalid("exactly one independently approved environment is supported")
        supported_environment_id = _string(source["supported_environment_id"], "supported_environment_id")
        if supported_environment_id != environments[0].environment_id:
            _invalid("supported_environment_id must reference the unique supported environment")
        return BaselineManifest(
            schema_version=schema_version,
            manifest_id=manifest_id,
            required_assets=assets,
            checks=checks,
            supported_environments=environments,
            dependency_lock=_relative_path(source["dependency_lock"], "dependency_lock"),
            dependency_fingerprint=_string(source["dependency_fingerprint"], "dependency_fingerprint"),
            evidence_schema_version=evidence_version,
            supported_environment_id=supported_environment_id,
        )
    except ManifestValidationError:
        raise
    except BaseException:
        raise ManifestValidationError() from None


def load_manifest(path: str | Path) -> BaselineManifest:
    try:
        source = json.loads(Path(path).read_text(encoding="utf-8"))
    except BaseException:
        raise ManifestValidationError() from None
    return parse_manifest(source)


def _git(repository_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(repository_root), *args],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise ManifestIntegrityError(ErrorCode.MANIFEST_INVALID, "repository") from None


def _validate_repository(repository_root: str | Path) -> Path:
    try:
        root = Path(repository_root).resolve(strict=True)
    except OSError:
        raise ManifestIntegrityError(ErrorCode.MANIFEST_INVALID, "repository") from None
    if not root.is_dir():
        raise ManifestIntegrityError(ErrorCode.MANIFEST_INVALID, "repository")
    discovered = _git(root, "rev-parse", "--show-toplevel")
    if discovered.returncode != 0:
        raise ManifestIntegrityError(ErrorCode.MANIFEST_INVALID, "repository")
    try:
        git_root = Path(discovered.stdout.strip()).resolve(strict=True)
    except OSError:
        raise ManifestIntegrityError(ErrorCode.MANIFEST_INVALID, "repository") from None
    if git_root != root:
        raise ManifestIntegrityError(ErrorCode.MANIFEST_INVALID, "repository")
    if _git(root, "rev-parse", "--verify", "HEAD").returncode != 0:
        raise ManifestIntegrityError(ErrorCode.MANIFEST_INVALID, "repository")
    return root


def _validate_asset(root: Path, relative: str) -> None:
    candidate = root / relative
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
        if not resolved.is_file():
            raise OSError
        with resolved.open("rb") as stream:
            stream.read(1)
    except (OSError, ValueError):
        raise ManifestIntegrityError(ErrorCode.ASSET_MISSING, relative) from None

    ignored = _git(root, "check-ignore", "--no-index", "--quiet", "--", relative)
    if ignored.returncode == 0:
        raise ManifestIntegrityError(ErrorCode.ASSET_MISSING, relative)
    if ignored.returncode != 1:
        raise ManifestIntegrityError(ErrorCode.MANIFEST_INVALID, "repository")

    tracked = _git(root, "cat-file", "-t", f"HEAD:{relative}")
    if tracked.returncode != 0 or tracked.stdout.strip() != "blob":
        raise ManifestIntegrityError(ErrorCode.ASSET_MISSING, relative)


def _requirement_coverage(manifest: BaselineManifest) -> tuple[RequirementMapping, ...]:
    mapping = {
        requirement_id: tuple(
            check.check_id
            for check in manifest.checks
            if requirement_id in check.requirement_ids
        )
        for requirement_id in REQUIREMENT_IDS
    }
    missing = tuple(key for key, check_ids in mapping.items() if not check_ids)
    if missing:
        raise ManifestIntegrityError(ErrorCode.MANIFEST_INVALID, missing[0])
    return tuple(
        RequirementMapping(requirement_id, mapping[requirement_id])
        for requirement_id in REQUIREMENT_IDS
    )


def _manifest_digest(manifest: BaselineManifest) -> str:
    canonical = json.dumps(
        manifest.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def validate_manifest_integrity(
    manifest: BaselineManifest,
    repository_root: str | Path,
) -> ManifestIntegrity:
    """Validate assets against HEAD and return stable coverage and digest data."""
    try:
        normalized = parse_manifest(manifest.to_dict())
    except (AttributeError, ManifestValidationError):
        raise ManifestIntegrityError(ErrorCode.MANIFEST_INVALID, "manifest") from None
    if normalized != manifest:
        raise ManifestIntegrityError(ErrorCode.MANIFEST_INVALID, "manifest")
    manifest = normalized
    root = _validate_repository(repository_root)
    asset_paths = tuple(asset.path for asset in manifest.required_assets)
    asset_set = frozenset(asset_paths)
    if manifest.dependency_lock not in asset_set:
        raise ManifestIntegrityError(ErrorCode.ASSET_MISSING, manifest.dependency_lock)
    for check in manifest.checks:
        for reference in check.asset_refs:
            if reference not in asset_set:
                raise ManifestIntegrityError(ErrorCode.ASSET_MISSING, reference)
    for path in asset_paths:
        _validate_asset(root, path)
    return ManifestIntegrity(
        asset_paths=asset_paths,
        requirement_coverage=_requirement_coverage(manifest),
        manifest_digest=_manifest_digest(manifest),
    )


def validate_json_schema(instance: object, schema_path: str | Path) -> None:
    """Validate using the fail-closed Draft 2020-12 subset used by P0 schemas."""
    try:
        schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
        if type(schema) is not dict:
            raise ManifestValidationError("schema root must be an object")
        _validate_schema_definition(schema, schema, set())
        _validate_schema_node(instance, schema, schema)
    except ManifestValidationError:
        raise
    except _SchemaMismatch:
        raise ManifestValidationError("JSON document does not satisfy its P0 schema") from None
    except BaseException:
        raise ManifestValidationError("P0 schema could not be evaluated") from None


def _validate_schema_definition(
    schema: object,
    root: dict[str, Any],
    seen: set[int],
) -> None:
    """Audit every schema branch before instance-dependent evaluation."""
    if type(schema) is bool:
        return
    if type(schema) is not dict:
        raise ManifestValidationError("JSON Schema nodes must be objects or booleans")
    identity = id(schema)
    if identity in seen:
        return
    seen.add(identity)
    unsupported = set(schema) - _SCHEMA_ANNOTATIONS - _SCHEMA_ASSERTIONS
    if unsupported:
        raise ManifestValidationError("P0 schema contains an unsupported keyword")

    if "$ref" in schema:
        _validate_schema_definition(_resolve_ref(root, schema["$ref"]), root, seen)
    if "type" in schema and (
        type(schema["type"]) is not str
        or schema["type"]
        not in {"object", "array", "string", "integer", "number", "boolean", "null"}
    ):
        raise ManifestValidationError("P0 schema type declaration is unsupported")
    if "required" in schema:
        required = schema["required"]
        if (
            type(required) is not list
            or any(type(name) is not str for name in required)
            or len(set(required)) != len(required)
        ):
            raise ManifestValidationError("schema required must contain unique strings")
    if "enum" in schema and (type(schema["enum"]) is not list or not schema["enum"]):
        raise ManifestValidationError("schema enum must be a nonempty array")
    if "pattern" in schema:
        if type(schema["pattern"]) is not str:
            raise ManifestValidationError("schema pattern must be text")
        try:
            re.compile(schema["pattern"])
        except re.error:
            raise ManifestValidationError("schema pattern is invalid") from None
    if "format" in schema and schema["format"] != "date-time":
        raise ManifestValidationError("P0 schema format is unsupported")
    for keyword in ("minLength", "minItems", "maxItems", "minContains", "maxContains"):
        if keyword in schema and (
            type(schema[keyword]) is not int or schema[keyword] < 0
        ):
            raise ManifestValidationError(f"schema {keyword} must be nonnegative")
    if "minimum" in schema and type(schema["minimum"]) not in {int, float}:
        raise ManifestValidationError("schema minimum must be numeric")
    if "uniqueItems" in schema and type(schema["uniqueItems"]) is not bool:
        raise ManifestValidationError("schema uniqueItems must be boolean")

    for keyword in ("properties", "$defs"):
        if keyword not in schema:
            continue
        mapping = schema[keyword]
        if type(mapping) is not dict or any(type(name) is not str for name in mapping):
            raise ManifestValidationError(f"schema {keyword} must be an object")
        for child in mapping.values():
            _validate_schema_definition(child, root, seen)
    for keyword in ("items", "additionalProperties", "not", "if", "then", "contains"):
        if keyword in schema:
            _validate_schema_definition(schema[keyword], root, seen)
    for keyword in ("allOf", "anyOf"):
        if keyword not in schema:
            continue
        children = schema[keyword]
        if type(children) is not list or not children:
            raise ManifestValidationError(f"schema {keyword} must be nonempty")
        for child in children:
            _validate_schema_definition(child, root, seen)


def _resolve_ref(root: dict[str, Any], reference: object) -> object:
    if type(reference) is not str or not reference.startswith("#/"):
        raise ManifestValidationError("only local JSON Schema references are supported")
    current: object = root
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if type(current) is not dict or part not in current:
            raise ManifestValidationError("JSON Schema reference could not be resolved")
        current = current[part]
    return current


def _matches_schema(instance: object, schema: object, root: dict[str, Any]) -> bool:
    try:
        _validate_schema_node(instance, schema, root)
        return True
    except _SchemaMismatch:
        return False


def _json_equal(left: object, right: object) -> bool:
    """Compare JSON values without treating booleans as numbers."""
    if type(left) is bool or type(right) is bool:
        return type(left) is type(right) and left == right
    if type(left) is list and type(right) is list:
        return len(left) == len(right) and all(
            _json_equal(left_item, right_item)
            for left_item, right_item in zip(left, right)
        )
    if type(left) is dict and type(right) is dict:
        return set(left) == set(right) and all(
            _json_equal(left[key], right[key]) for key in left
        )
    return left == right


def _validate_schema_node(instance: object, schema: object, root: dict[str, Any]) -> None:
    if type(schema) is bool:
        if not schema:
            raise _SchemaMismatch
        return
    if type(schema) is not dict:
        raise ManifestValidationError("JSON Schema nodes must be objects or booleans")
    unsupported = set(schema) - _SCHEMA_ANNOTATIONS - _SCHEMA_ASSERTIONS
    if unsupported:
        raise ManifestValidationError("P0 schema contains an unsupported keyword")
    if "$ref" in schema:
        _validate_schema_node(instance, _resolve_ref(root, schema["$ref"]), root)
    if "allOf" in schema:
        for child in _array(schema["allOf"], "schema allOf"):
            _validate_schema_node(instance, child, root)
    if "anyOf" in schema:
        children = _array(schema["anyOf"], "schema anyOf", nonempty=True)
        if not any(_matches_schema(instance, child, root) for child in children):
            raise _SchemaMismatch
    if "not" in schema and _matches_schema(instance, schema["not"], root):
        raise _SchemaMismatch
    if "if" in schema and _matches_schema(instance, schema["if"], root) and "then" in schema:
        _validate_schema_node(instance, schema["then"], root)

    expected_type = schema.get("type")
    type_matches = {
        "object": type(instance) is dict,
        "array": type(instance) is list,
        "string": type(instance) is str,
        "integer": type(instance) is int,
        "number": type(instance) in {int, float},
        "boolean": type(instance) is bool,
        "null": instance is None,
    }
    if expected_type is not None:
        if type(expected_type) is not str or expected_type not in type_matches:
            raise ManifestValidationError("P0 schema type declaration is unsupported")
        if not type_matches[expected_type]:
            raise _SchemaMismatch
    if "const" in schema and not _json_equal(instance, schema["const"]):
        raise _SchemaMismatch
    if "enum" in schema:
        choices = _array(schema["enum"], "schema enum", nonempty=True)
        if not any(_json_equal(instance, choice) for choice in choices):
            raise _SchemaMismatch
    if "pattern" in schema:
        if type(instance) is not str or type(schema["pattern"]) is not str or re.search(schema["pattern"], instance) is None:
            raise _SchemaMismatch
    if "minLength" in schema:
        if type(instance) is not str or type(schema["minLength"]) is not int or len(instance) < schema["minLength"]:
            raise _SchemaMismatch
    if "format" in schema:
        if schema["format"] != "date-time":
            raise ManifestValidationError("P0 schema format is unsupported")
        if type(instance) is not str:
            raise _SchemaMismatch
        try:
            parsed = datetime.fromisoformat(instance.replace("Z", "+00:00"))
        except ValueError:
            raise _SchemaMismatch from None
        if "T" not in instance or parsed.utcoffset() is None:
            raise _SchemaMismatch
    if "minimum" in schema:
        if type(instance) not in {int, float} or type(schema["minimum"]) not in {int, float} or instance < schema["minimum"]:
            raise _SchemaMismatch
    if "minItems" in schema:
        if type(instance) is not list or type(schema["minItems"]) is not int or len(instance) < schema["minItems"]:
            raise _SchemaMismatch
    if "maxItems" in schema:
        if type(instance) is not list or type(schema["maxItems"]) is not int or len(instance) > schema["maxItems"]:
            raise _SchemaMismatch
    if schema.get("uniqueItems") is True:
        if type(instance) is not list or any(
            any(_json_equal(item, previous) for previous in instance[:index])
            for index, item in enumerate(instance)
        ):
            raise _SchemaMismatch
    if "contains" in schema:
        if type(instance) is not list:
            raise _SchemaMismatch
        matches = sum(
            _matches_schema(item, schema["contains"], root) for item in instance
        )
        minimum = schema.get("minContains", 1)
        maximum = schema.get("maxContains")
        if type(minimum) is not int or minimum < 0:
            raise ManifestValidationError("schema minContains must be nonnegative")
        if maximum is not None and (type(maximum) is not int or maximum < 0):
            raise ManifestValidationError("schema maxContains must be nonnegative")
        if matches < minimum or (maximum is not None and matches > maximum):
            raise _SchemaMismatch
    if "items" in schema and type(instance) is list:
        for item in instance:
            _validate_schema_node(item, schema["items"], root)
    if type(instance) is dict:
        required = schema.get("required", [])
        for name in _array(required, "schema required"):
            if type(name) is not str:
                raise ManifestValidationError("schema required names must be strings")
            if name not in instance:
                raise _SchemaMismatch
        properties = schema.get("properties", {})
        if type(properties) is not dict:
            raise ManifestValidationError("schema properties must be an object")
        for name, child in properties.items():
            if name in instance:
                _validate_schema_node(instance[name], child, root)
        additional = schema.get("additionalProperties", True)
        for name, value in instance.items():
            if name in properties:
                continue
            if additional is False:
                raise _SchemaMismatch
            if additional is not True:
                _validate_schema_node(value, additional, root)
