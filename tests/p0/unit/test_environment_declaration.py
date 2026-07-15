from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPOSITORY_ROOT / "p0_baseline" / "manifest.json"
FIXTURE_ROOT = REPOSITORY_ROOT / "tests" / "p0" / "fixtures" / "environments"
EXPECTED_ENVIRONMENT_ID = "darwin-arm64-cpython-3.12"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _matches_declaration(environment: dict[str, object], constraint: dict[str, str]) -> bool:
    """Test-only matcher; production environment support belongs to Preflight."""
    declared_version = constraint["runtime_version"]
    version_prefix = declared_version.removesuffix(".x")
    runtime_version = str(environment["runtime_version"])
    return (
        environment["os"] == constraint["os"]
        and environment["architecture"] == constraint["architecture"]
        and environment["runtime_name"] == constraint["runtime_name"]
        and runtime_version.split(".")[:2] == version_prefix.split(".")
    )


class EnvironmentDeclarationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = _read_json(MANIFEST_PATH)
        self.constraint = self.manifest["supported_environments"][0]

    def test_manifest_skeleton_declares_the_single_supported_environment(self) -> None:
        self.assertEqual(
            self.manifest["supported_environment_id"], EXPECTED_ENVIRONMENT_ID
        )
        # ADR-P0-003 requires independent clean-checkout validation before adding entries.
        self.assertEqual(len(self.manifest["supported_environments"]), 1)
        self.assertEqual(
            self.constraint,
            {
                "environment_id": EXPECTED_ENVIRONMENT_ID,
                "os": "Darwin",
                "architecture": "arm64",
                "runtime_name": "CPython",
                "runtime_version": "3.12.x",
            },
        )

    def test_manifest_skeleton_preserves_known_baseline_manifest_fields(self) -> None:
        self.assertEqual(self.manifest["manifest_id"], "localpilot.p0-baseline")
        self.assertIn("schema_version", self.manifest)
        self.assertIn("required_assets", self.manifest)
        self.assertIn("checks", self.manifest)
        self.assertIn("evidence_schema_version", self.manifest)

        # Task 2.3 owns the complete asset/check declarations and Schema validation.
        self.assertEqual(self.manifest["required_assets"], [])
        self.assertEqual(self.manifest["checks"], [])

    def test_supported_fixture_has_deterministic_true_expectation(self) -> None:
        fixture = _read_json(FIXTURE_ROOT / "supported.json")

        self.assertIs(fixture["expected_supported"], True)
        self.assertEqual(
            _matches_declaration(fixture, self.constraint),
            fixture["expected_supported"],
        )

    def test_other_os_architecture_and_python_minor_are_unsupported(self) -> None:
        fixtures = _read_json(FIXTURE_ROOT / "unsupported.json")

        self.assertEqual(len(fixtures), 3)
        for fixture in fixtures:
            with self.subTest(fixture=fixture):
                self.assertIs(fixture["expected_supported"], False)
                self.assertEqual(
                    _matches_declaration(fixture, self.constraint),
                    fixture["expected_supported"],
                )


if __name__ == "__main__":
    unittest.main()
