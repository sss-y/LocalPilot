from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from p0_baseline.errors import ErrorCode
from p0_baseline.manifest import (
    ManifestValidationError,
    load_manifest,
    parse_manifest,
    validate_json_schema,
)
from tests.p0.unit.test_models import report


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPOSITORY_ROOT / "p0_baseline" / "manifest.json"
MANIFEST_SCHEMA_PATH = REPOSITORY_ROOT / "p0_baseline" / "schemas" / "manifest.schema.json"
REPORT_SCHEMA_PATH = REPOSITORY_ROOT / "p0_baseline" / "schemas" / "report.schema.json"


def valid_manifest() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "manifest_id": "localpilot.p0-baseline",
        "required_assets": [
            {
                "path": "tests/p0/unit/test_cli_entrypoint.py",
                "kind": "test",
                "required": True,
                "requirement_ids": ["5.1"],
            }
        ],
        "checks": [
            {
                "check_id": "cli.entrypoint",
                "title": "CLI entrypoint",
                "category": "behavior",
                "required": True,
                "requirement_ids": ["5.1", "5.2"],
                "asset_refs": ["tests/p0/unit/test_cli_entrypoint.py"],
                "network_policy": "offline",
                "timeout_ms": 10000,
                "migration_status": "stable",
                "adapter": "unittest",
                "test_ids": [
                    "tests.p0.unit.test_cli_entrypoint.CliEntrypointTests.test_help_from_repository_root_returns_zero"
                ],
                "allow_loopback": False,
            }
        ],
        "supported_environments": [
            {
                "environment_id": "darwin-arm64-cpython-3.12",
                "os": "Darwin",
                "architecture": "arm64",
                "runtime_name": "CPython",
                "runtime_version": "3.12.x",
            }
        ],
        "dependency_lock": "requirements-p0.lock",
        "dependency_fingerprint": "sha256:baseline",
        "evidence_schema_version": "1.0.0",
        "supported_environment_id": "darwin-arm64-cpython-3.12",
    }


class ManifestLoaderTests(unittest.TestCase):
    def assertInvalid(self, data: object) -> None:  # noqa: N802
        with self.assertRaises(ManifestValidationError) as caught:
            parse_manifest(data)
        self.assertIs(caught.exception.code, ErrorCode.MANIFEST_INVALID)
        diagnostic = caught.exception.to_diagnostic()
        self.assertIs(diagnostic.code, ErrorCode.MANIFEST_INVALID)
        self.assertEqual("manifest", diagnostic.failure_type)

    def assertSchemaInvalid(self, data: object, path: Path = MANIFEST_SCHEMA_PATH) -> None:  # noqa: N802
        with self.assertRaises(ManifestValidationError):
            validate_json_schema(data, path)

    def test_manifest_schema_rejects_adapter_condition_violations(self) -> None:
        data = valid_manifest()
        data["checks"][0]["adapter"] = "internal"  # type: ignore[index]
        self.assertSchemaInvalid(data)

        data = valid_manifest()
        data["checks"][0]["test_ids"] = []  # type: ignore[index]
        self.assertSchemaInvalid(data)

    def test_manifest_schema_rejects_unknown_requirement_paths_commands_and_loopback(self) -> None:
        mutations = (
            ("requirement_ids", ["9.99"]),
            ("asset_path", "./tests/p0/unit/test_cli_entrypoint.py"),
            ("command", "python -m unittest"),
            ("allow_loopback", True),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                data = valid_manifest()
                if field == "requirement_ids":
                    data["checks"][0][field] = value  # type: ignore[index]
                elif field == "asset_path":
                    data["required_assets"][0]["path"] = value  # type: ignore[index]
                else:
                    data["checks"][0][field] = value  # type: ignore[index]
                self.assertSchemaInvalid(data)

    def test_report_schema_rejects_unknown_requirement_id(self) -> None:
        data = report().to_dict()
        data["requirement_coverage"][0]["requirement_id"] = "99.99"  # type: ignore[index]
        self.assertSchemaInvalid(data, REPORT_SCHEMA_PATH)

    def test_report_schema_rejects_model_invariant_violations(self) -> None:
        mutations = (
            ("boolean exit code", lambda data: data.__setitem__("exit_code", True)),
            ("naive timestamp", lambda data: data.__setitem__("started_at", "2026-01-01T00:00:00")),
            ("status exit mismatch", lambda data: data.__setitem__("exit_code", 1)),
            (
                "duplicate coverage check id",
                lambda data: data["requirement_coverage"][0].__setitem__(
                    "check_ids", ["behavior.cli", "behavior.cli"]
                ),
            ),
            (
                "failed check without diagnostic",
                lambda data: data["checks"][0].__setitem__("status", "failed"),
            ),
        )
        for name, mutate in mutations:
            with self.subTest(name=name):
                data = report().to_dict()
                mutate(data)
                self.assertSchemaInvalid(data, REPORT_SCHEMA_PATH)

    def test_current_manifest_loads_as_immutable_descriptors(self) -> None:
        manifest = load_manifest(MANIFEST_PATH)

        self.assertEqual("localpilot.p0-baseline", manifest.manifest_id)
        self.assertGreater(len(manifest.required_assets), 0)
        self.assertGreater(len(manifest.checks), 0)
        self.assertIsInstance(manifest.required_assets, tuple)
        self.assertIsInstance(manifest.checks[0].test_ids, tuple)
        with self.assertRaises(FrozenInstanceError):
            manifest.manifest_id = "changed"  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            manifest.checks[0].title = "changed"  # type: ignore[misc]

    def test_descriptor_round_trip_and_unknown_optional_fields(self) -> None:
        data = valid_manifest()
        data["future_optional"] = {"accepted": True}
        data["checks"][0]["future_check_option"] = "accepted"  # type: ignore[index]

        manifest = parse_manifest(data)

        self.assertEqual(manifest, parse_manifest(manifest.to_dict()))
        self.assertNotIn("future_optional", manifest.to_dict())
        self.assertNotIn("future_check_option", manifest.to_dict()["checks"][0])

    def test_duplicate_check_id_is_rejected(self) -> None:
        data = valid_manifest()
        duplicate = dict(data["checks"][0])  # type: ignore[index]
        duplicate["title"] = "Different object with the same check id"
        data["checks"].append(duplicate)  # type: ignore[union-attr]
        # JSON Schema uniqueItems cannot express uniqueness by one object property;
        # the Loader's semantic layer owns cross-item check_id uniqueness.
        self.assertInvalid(data)

    def test_schema_subset_rejects_unsupported_keywords_fail_closed(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "unsupported.schema.json"
            schemas = (
                {"type": "object", "unevaluatedProperties": False},
                {
                    "type": "object",
                    "properties": {
                        "absent_optional": {"unevaluatedProperties": False}
                    },
                },
            )
            for schema in schemas:
                with self.subTest(schema=schema):
                    path.write_text(json.dumps(schema), encoding="utf-8")
                    self.assertSchemaInvalid({}, path)

    def test_absolute_parent_and_backslash_paths_are_rejected(self) -> None:
        for path in ("/tmp/test.py", "C:/temp/test.py", "../test.py", "tests/../secret", "tests\\p0\\test.py"):
            with self.subTest(path=path):
                data = valid_manifest()
                data["required_assets"][0]["path"] = path  # type: ignore[index]
                self.assertInvalid(data)

    def test_unknown_adapter_and_non_exact_unittest_ids_are_rejected(self) -> None:
        for adapter, test_ids in (
            ("shell", ["tests.p0.unit.test_cli_entrypoint.CliEntrypointTests.test_help"]),
            ("unittest", ["tests.p0.*"]),
            ("unittest", ["python -m unittest tests.p0"]),
            ("unittest", []),
            ("internal", ["tests.p0.unit.test_cli.SomeTest.test_method"]),
        ):
            with self.subTest(adapter=adapter, test_ids=test_ids):
                data = valid_manifest()
                data["checks"][0]["adapter"] = adapter  # type: ignore[index]
                data["checks"][0]["test_ids"] = test_ids  # type: ignore[index]
                self.assertInvalid(data)

    def test_internal_adapter_requires_no_test_ids(self) -> None:
        data = valid_manifest()
        data["checks"][0]["adapter"] = "internal"  # type: ignore[index]
        del data["checks"][0]["test_ids"]  # type: ignore[index]
        self.assertEqual("internal", parse_manifest(data).checks[0].adapter)

    def test_only_approved_supported_environment_is_accepted(self) -> None:
        mutations = (
            ("os", "Linux"),
            ("architecture", "x86_64"),
            ("runtime_name", "PyPy"),
            ("runtime_version", "3.11.x"),
            ("environment_id", "another-environment"),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                data = valid_manifest()
                data["supported_environments"][0][field] = value  # type: ignore[index]
                self.assertInvalid(data)

        data = valid_manifest()
        data["supported_environments"].append(dict(data["supported_environments"][0]))  # type: ignore[union-attr,index]
        self.assertInvalid(data)

    def test_supported_environment_id_must_reference_the_unique_constraint(self) -> None:
        data = valid_manifest()
        data["supported_environment_id"] = "missing"
        self.assertInvalid(data)

    def test_known_fields_have_strict_types_and_values(self) -> None:
        mutations = (
            ("required_assets", "not-an-array"),
            ("manifest_id", 1),
            ("dependency_lock", True),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                data = valid_manifest()
                data[field] = value
                self.assertInvalid(data)

        for field, value in (
            ("required", False),
            ("timeout_ms", 0),
            ("network_policy", "online"),
            ("migration_status", "experimental"),
            ("allow_loopback", 1),
            ("category", "unknown"),
        ):
            with self.subTest(field=field):
                data = valid_manifest()
                data["checks"][0][field] = value  # type: ignore[index]
                self.assertInvalid(data)

    def test_requirement_and_check_identifiers_are_validated(self) -> None:
        for field, value in (("check_id", "CLI"), ("check_id", "cli")):
            with self.subTest(value=value):
                data = valid_manifest()
                data["checks"][0][field] = value  # type: ignore[index]
                self.assertInvalid(data)
        data = valid_manifest()
        data["checks"][0]["requirement_ids"] = ["REQ-5.1"]  # type: ignore[index]
        self.assertInvalid(data)

    def test_manifest_and_evidence_versions_must_be_supported_same_major(self) -> None:
        for manifest_version, evidence_version in (("2.0.0", "2.0.0"), ("1.1", "1.0.0"), ("1.0.0", "2.0.0")):
            with self.subTest(manifest_version=manifest_version, evidence_version=evidence_version):
                data = valid_manifest()
                data["schema_version"] = manifest_version
                data["evidence_schema_version"] = evidence_version
                self.assertInvalid(data)

    def test_loader_reads_utf8_json_and_normalizes_decode_failures(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(valid_manifest()), encoding="utf-8")
            self.assertEqual(parse_manifest(valid_manifest()), load_manifest(path))
            path.write_bytes(b"\xff\xfe")
            with self.assertRaises(ManifestValidationError) as caught:
                load_manifest(path)
            self.assertIs(caught.exception.code, ErrorCode.MANIFEST_INVALID)

    def test_manifest_and_report_schemas_are_draft_2020_12_and_extensible(self) -> None:
        for path in (MANIFEST_SCHEMA_PATH, REPORT_SCHEMA_PATH):
            with self.subTest(path=path):
                schema = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"])
                self.assertEqual("object", schema["type"])
                self.assertIs(schema["additionalProperties"], True)
                self.assertGreater(len(schema["required"]), 0)
        report_schema = json.loads(REPORT_SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual("1.0.0", report_schema["properties"]["schema_version"]["const"])
        self.assertEqual(["success", "failure", "incomplete"], report_schema["properties"]["overall_status"]["enum"])


if __name__ == "__main__":
    unittest.main()
