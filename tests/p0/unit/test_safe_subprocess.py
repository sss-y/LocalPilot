from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from p0_baseline.check_worker import WorkerRequest, WorkerResult
from p0_baseline.preflight import sanitized_worker_env
from p0_baseline.safe_subprocess import (
    SafeSubprocessError,
    UnsupportedExecutableError,
    run_worker,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
NETWORK_TEST_IDS = (
    "tests.p0.fixtures.worker_cases.OfflineNetworkFixture.test_external_dns_is_blocked",
    "tests.p0.fixtures.worker_cases.OfflineNetworkFixture.test_external_tcp_is_blocked",
    "tests.p0.fixtures.worker_cases.OfflineNetworkFixture.test_external_udp_is_blocked",
)


class SafeSubprocessTests(unittest.TestCase):
    def _run_directory(self) -> Path:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name)

    def _environment(self) -> dict[str, str]:
        return sanitized_worker_env(
            {
                "PATH": os.environ.get("PATH", ""),
                "PYTHONUTF8": "1",
                "API_KEY": "worker-api-secret",
                "HTTPS_PROXY": "https://proxy-user:proxy-secret@example.invalid",
                "PYTHONPATH": "/unapproved/import/path",
            }
        )

    def test_real_worker_blocks_external_dns_tcp_and_udp_without_leaking_target_secrets(self) -> None:
        result = run_worker(
            WorkerRequest("1.0.0", NETWORK_TEST_IDS),
            repository_root=REPOSITORY_ROOT,
            run_directory=self._run_directory(),
            sanitized_environment=self._environment(),
        )

        self.assertEqual(3, result.tests_run)
        self.assertEqual(
            ("network_policy", "network_policy", "network_policy"),
            tuple(outcome.failure_type for outcome in result.outcomes),
        )
        self.assertEqual(
            ("getaddrinfo", "connect", "sendto"),
            tuple(outcome.operation for outcome in result.outcomes),
        )
        self.assertEqual(
            ("check-worker", "check-worker", "check-worker"),
            tuple(outcome.source for outcome in result.outcomes),
        )
        self.assertEqual(
            ("example.invalid", "203.0.113.17", "203.0.113.17"),
            tuple(outcome.target_summary for outcome in result.outcomes),
        )
        rendered = result.to_json()
        self.assertEqual(result, WorkerResult.from_json(rendered))
        self.assertIn("203.0.113.17", rendered)
        for secret in (
            "worker-api-secret",
            "proxy-user",
            "proxy-secret",
            "token=",
            "password",
            "/private/path",
        ):
            self.assertNotIn(secret, rendered)

    def test_unknown_executable_is_rejected_before_subprocess_is_called(self) -> None:
        with mock.patch("p0_baseline.safe_subprocess.subprocess.run") as process:
            with self.assertRaises(UnsupportedExecutableError):
                run_worker(
                    WorkerRequest(
                        "1.0.0",
                        ("tests.p0.fixtures.worker_cases.PassingFixture.test_passes",),
                    ),
                    repository_root=REPOSITORY_ROOT,
                    run_directory=self._run_directory(),
                    sanitized_environment=self._environment(),
                    executable="/bin/sh",
                )
        process.assert_not_called()

    def test_invocation_and_environment_are_fixed_and_sanitized(self) -> None:
        completed = subprocess.CompletedProcess([], 0, stdout="ignored-secret", stderr="ignored-secret")

        def fake_run(command, **options):
            self.assertEqual(sys.executable, command[0])
            self.assertEqual(("-m", "p0_baseline.check_worker", "--request"), tuple(command[1:4]))
            self.assertEqual("--result", command[5])
            self.assertEqual(REPOSITORY_ROOT, options["cwd"])
            self.assertTrue(options["capture_output"])
            self.assertFalse(options["shell"])
            self.assertEqual(
                {
                    "PATH": os.environ.get("PATH", ""),
                    "PYTHONUTF8": "1",
                    "P0_OFFLINE_ALLOW_LOOPBACK": "1",
                    "P0_OFFLINE_SOURCE": "check-worker",
                },
                options["env"],
            )
            request_path = Path(command[4])
            result_path = Path(command[6])
            self.assertEqual(request_path.parent, result_path.parent)
            self.assertFalse(result_path.exists())
            result_path.write_text(
                '{"outcomes":[],"schema_version":"1.0.0","tests_run":0}',
                encoding="utf-8",
            )
            return completed

        with mock.patch("p0_baseline.safe_subprocess.subprocess.run", side_effect=fake_run) as process:
            result = run_worker(
                WorkerRequest("1.0.0", ("tests.p0.fixtures.worker_cases.PassingFixture.test_passes",)),
                repository_root=REPOSITORY_ROOT,
                run_directory=self._run_directory(),
                sanitized_environment=self._environment(),
                allow_loopback=True,
            )

        self.assertEqual(0, result.tests_run)
        process.assert_called_once()

    def test_unsanitized_environment_and_invalid_loopback_value_fail_closed(self) -> None:
        common = {
            "repository_root": REPOSITORY_ROOT,
            "run_directory": self._run_directory(),
        }
        request = WorkerRequest(
            "1.0.0", ("tests.p0.fixtures.worker_cases.PassingFixture.test_passes",)
        )
        with mock.patch("p0_baseline.safe_subprocess.subprocess.run") as process:
            with self.assertRaises(SafeSubprocessError):
                run_worker(request, sanitized_environment={"API_KEY": "secret"}, **common)
            with self.assertRaises(TypeError):
                run_worker(
                    request,
                    sanitized_environment=self._environment(),
                    allow_loopback="true",
                    **common,
                )
        process.assert_not_called()

    def test_timeout_has_a_stable_internal_reason_without_waiting(self) -> None:
        with mock.patch(
            "p0_baseline.safe_subprocess.subprocess.run",
            side_effect=subprocess.TimeoutExpired([sys.executable], 1),
        ):
            with self.assertRaises(SafeSubprocessError) as caught:
                run_worker(
                    WorkerRequest(
                        "1.0.0",
                        ("tests.p0.fixtures.worker_cases.PassingFixture.test_passes",),
                    ),
                    repository_root=REPOSITORY_ROOT,
                    run_directory=self._run_directory(),
                    sanitized_environment=self._environment(),
                )
        self.assertEqual("P0_WORKER_TIMEOUT", caught.exception.reason)

    def test_nonzero_missing_and_invalid_results_have_stable_internal_reasons(self) -> None:
        request = WorkerRequest(
            "1.0.0", ("tests.p0.fixtures.worker_cases.PassingFixture.test_passes",)
        )

        def missing(command, **options):
            return subprocess.CompletedProcess(command, 0, stdout="secret", stderr="secret")

        def invalid(command, **options):
            Path(command[6]).write_text("not-json secret", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="secret", stderr="secret")

        cases = (
            (lambda command, **options: subprocess.CompletedProcess(command, 7, stdout="secret", stderr="secret"), "P0_WORKER_EXIT_NONZERO"),
            (missing, "P0_WORKER_RESULT_MISSING"),
            (invalid, "P0_WORKER_RESULT_INVALID"),
        )
        for fake_run, reason in cases:
            with self.subTest(reason=reason), mock.patch(
                "p0_baseline.safe_subprocess.subprocess.run", side_effect=fake_run
            ):
                with self.assertRaises(SafeSubprocessError) as caught:
                    run_worker(
                        request,
                        repository_root=REPOSITORY_ROOT,
                        run_directory=self._run_directory(),
                        sanitized_environment=self._environment(),
                    )
                self.assertEqual(reason, caught.exception.reason)
                self.assertNotIn("secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
