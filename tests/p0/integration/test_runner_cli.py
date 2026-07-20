from __future__ import annotations

from dataclasses import replace
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from p0_baseline.adapters import InternalAdapter, UnittestAdapter
from p0_baseline.cli import main
from p0_baseline.manifest import ManifestIntegrity, load_manifest
from p0_baseline.models import (
    BaselineStatus,
    CheckStatus,
    EnvironmentSnapshot,
    NetworkMode,
    WorkingTreeState,
)
from p0_baseline.offline import NetworkPolicyViolation
from p0_baseline.registry import AdapterRegistry
from p0_baseline.runner import run


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPOSITORY_ROOT / "p0_baseline" / "manifest.json"
REVISION = "a" * 40


def clean_environment() -> EnvironmentSnapshot:
    return EnvironmentSnapshot(
        revision=REVISION,
        repository_root="<repository-root>",
        working_tree_state=WorkingTreeState.CLEAN,
        runtime_name="CPython",
        runtime_version="3.12.13",
        os="Darwin",
        architecture="arm64",
        dependency_fingerprint="sha256:dependencies",
        code_origins={"core": "core/__init__.py"},
        network_mode=NetworkMode.OFFLINE,
        personal_credentials_loaded=False,
        supported=True,
    )


class RunnerIntegrationTests(unittest.TestCase):
    def test_required_internal_check_runs_under_parent_offline_guard_and_succeeds(self) -> None:
        source = load_manifest(MANIFEST_PATH)
        descriptor = replace(
            next(check for check in source.checks if check.adapter == "internal"),
            check_id="runtime.parent-guard",
            title="Parent guard",
            requirement_ids=("3.1",),
        )
        manifest = replace(source, checks=(descriptor,))

        def guarded_check(context, target):
            self.assertTrue(getattr(socket.getaddrinfo, "__p0_offline_guard__", False))
            with self.assertRaises(NetworkPolicyViolation):
                socket.getaddrinfo("provider.example", 443)
            return UnittestAdapter.result_for_status(target, CheckStatus.PASSED)
        registry = AdapterRegistry(
            unittest=UnittestAdapter(),
            internal=InternalAdapter({descriptor.check_id: guarded_check}),
        )
        integrity = ManifestIntegrity((), (), "sha256:manifest")

        with (
            patch("p0_baseline.runner.load_manifest", return_value=manifest),
            patch("p0_baseline.runner.validate_manifest_integrity", return_value=integrity),
            patch("p0_baseline.runner.inspect_preflight", return_value=clean_environment()),
        ):
            report = run(REPOSITORY_ROOT, MANIFEST_PATH, registry=registry)

        self.assertIs(report.overall_status, BaselineStatus.SUCCESS)
        self.assertEqual(0, report.exit_code)
        self.assertEqual((descriptor.check_id,), tuple(item.check_id for item in report.checks))
        self.assertFalse(getattr(socket.getaddrinfo, "__p0_offline_guard__", False))


class CliIntegrationTests(unittest.TestCase):
    def test_json_stdout_is_one_report_object_and_returns_report_exit_code(self) -> None:
        source = load_manifest(MANIFEST_PATH)
        descriptor = replace(
            next(check for check in source.checks if check.adapter == "internal"),
            check_id="runtime.cli",
            title="Runtime CLI",
            requirement_ids=("1.3",),
        )
        manifest = replace(source, checks=(descriptor,))
        registry = AdapterRegistry(
            unittest=UnittestAdapter(),
            internal=InternalAdapter(
                {
                    descriptor.check_id: lambda context, target: (
                        UnittestAdapter.result_for_status(target, CheckStatus.PASSED)
                    )
                }
            ),
        )
        with (
            patch("p0_baseline.runner.load_manifest", return_value=manifest),
            patch(
                "p0_baseline.runner.validate_manifest_integrity",
                return_value=ManifestIntegrity((), (), "sha256:manifest"),
            ),
            patch("p0_baseline.runner.inspect_preflight", return_value=clean_environment()),
        ):
            report = run(REPOSITORY_ROOT, MANIFEST_PATH, registry=registry)

        stdout = StringIO()
        with patch("p0_baseline.cli.run", return_value=report), redirect_stdout(stdout):
            exit_code = main(["--format", "json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual("success", payload["overall_status"])
        self.assertEqual(0, exit_code)
        self.assertEqual(1, len(stdout.getvalue().splitlines()))

    def test_human_output_ends_with_uppercase_status(self) -> None:
        report = self._successful_report()
        stdout = StringIO()

        with patch("p0_baseline.cli.run", return_value=report), redirect_stdout(stdout):
            exit_code = main([])

        self.assertEqual(0, exit_code)
        self.assertEqual("SUCCESS", stdout.getvalue().splitlines()[-1])

    def test_output_write_failure_returns_incomplete_without_exposing_path(self) -> None:
        report = self._successful_report()
        stdout = StringIO()

        with (
            patch("p0_baseline.cli.run", return_value=report),
            patch("p0_baseline.cli.Path.write_text", side_effect=OSError),
            redirect_stdout(stdout),
        ):
            exit_code = main(
                ["--format", "json", "--output", "/private/example/secret/report.json"]
            )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(2, exit_code)
        self.assertEqual("incomplete", payload["overall_status"])
        self.assertEqual("P0_EVIDENCE_INCOMPLETE", payload["run_diagnostics"][0]["code"])
        self.assertNotIn("/private/example", stdout.getvalue())

    def test_output_file_contains_the_same_json_object_as_stdout(self) -> None:
        report = self._successful_report()
        stdout = StringIO()

        with TemporaryDirectory() as directory:
            output = Path(directory) / "nested" / "report.json"
            with patch("p0_baseline.cli.run", return_value=report), redirect_stdout(stdout):
                exit_code = main(["--format", "json", "--output", str(output)])

            self.assertEqual(0, exit_code)
            self.assertEqual(
                json.loads(stdout.getvalue()),
                json.loads(output.read_text(encoding="utf-8")),
            )

    def test_output_write_failure_does_not_override_existing_failure(self) -> None:
        report = self._successful_report(CheckStatus.FAILED)
        stdout = StringIO()

        with (
            patch("p0_baseline.cli.run", return_value=report),
            patch("p0_baseline.cli.Path.write_text", side_effect=OSError),
            redirect_stdout(stdout),
        ):
            exit_code = main(["--format", "json", "--output", "report.json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(1, exit_code)
        self.assertEqual("failure", payload["overall_status"])
        self.assertEqual("P0_EVIDENCE_INCOMPLETE", payload["run_diagnostics"][0]["code"])

    def _successful_report(self, status: CheckStatus = CheckStatus.PASSED):
        source = load_manifest(MANIFEST_PATH)
        descriptor = replace(
            next(check for check in source.checks if check.adapter == "internal"),
            check_id="runtime.cli-fixture",
            title="Runtime CLI fixture",
            requirement_ids=("1.3",),
        )
        manifest = replace(source, checks=(descriptor,))
        registry = AdapterRegistry(
            unittest=UnittestAdapter(),
            internal=InternalAdapter(
                {
                    descriptor.check_id: lambda context, target: (
                        UnittestAdapter.result_for_status(target, status)
                    )
                }
            ),
        )
        with (
            patch("p0_baseline.runner.load_manifest", return_value=manifest),
            patch(
                "p0_baseline.runner.validate_manifest_integrity",
                return_value=ManifestIntegrity((), (), "sha256:manifest"),
            ),
            patch("p0_baseline.runner.inspect_preflight", return_value=clean_environment()),
        ):
            return run(REPOSITORY_ROOT, MANIFEST_PATH, registry=registry)

    def test_required_failure_and_dirty_gate_map_to_failure_and_incomplete(self) -> None:
        source = load_manifest(MANIFEST_PATH)
        descriptor = replace(
            next(check for check in source.checks if check.adapter == "internal"),
            check_id="runtime.status",
            title="Runtime status",
            requirement_ids=("4.2",),
        )
        manifest = replace(source, checks=(descriptor,))
        integrity = ManifestIntegrity((), (), "sha256:manifest")

        for status, environment, expected, exit_code in (
            (CheckStatus.FAILED, clean_environment(), BaselineStatus.FAILURE, 1),
            (
                CheckStatus.PASSED,
                replace(
                    clean_environment(),
                    working_tree_state=WorkingTreeState.DIRTY,
                ),
                BaselineStatus.INCOMPLETE,
                2,
            ),
        ):
            with self.subTest(status=status, expected=expected):
                registry = AdapterRegistry(
                    unittest=UnittestAdapter(),
                    internal=InternalAdapter(
                        {
                            descriptor.check_id: lambda context, target, value=status: (
                                UnittestAdapter.result_for_status(target, value)
                            )
                        }
                    ),
                )
                with (
                    patch("p0_baseline.runner.load_manifest", return_value=manifest),
                    patch(
                        "p0_baseline.runner.validate_manifest_integrity",
                        return_value=integrity,
                    ),
                    patch(
                        "p0_baseline.runner.inspect_preflight",
                        return_value=environment,
                    ),
                ):
                    report = run(REPOSITORY_ROOT, MANIFEST_PATH, registry=registry)

                self.assertIs(report.overall_status, expected)
                self.assertEqual(exit_code, report.exit_code)

    def test_interrupt_leaves_not_run_result_and_restores_parent_guard(self) -> None:
        source = load_manifest(MANIFEST_PATH)
        descriptor = replace(
            next(check for check in source.checks if check.adapter == "internal"),
            check_id="runtime.interrupt",
            title="Runtime interrupt",
            requirement_ids=("4.4",),
        )
        manifest = replace(source, checks=(descriptor,))

        def interrupt(context, target):
            raise KeyboardInterrupt

        registry = AdapterRegistry(
            unittest=UnittestAdapter(),
            internal=InternalAdapter({descriptor.check_id: interrupt}),
        )
        with (
            patch("p0_baseline.runner.load_manifest", return_value=manifest),
            patch(
                "p0_baseline.runner.validate_manifest_integrity",
                return_value=ManifestIntegrity((), (), "sha256:manifest"),
            ),
            patch("p0_baseline.runner.inspect_preflight", return_value=clean_environment()),
        ):
            report = run(REPOSITORY_ROOT, MANIFEST_PATH, registry=registry)

        self.assertIs(report.overall_status, BaselineStatus.INCOMPLETE)
        self.assertIs(report.checks[0].status, CheckStatus.NOT_RUN)
        self.assertFalse(getattr(socket.getaddrinfo, "__p0_offline_guard__", False))


if __name__ == "__main__":
    unittest.main()
