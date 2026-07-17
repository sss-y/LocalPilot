from __future__ import annotations

from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from p0_baseline.errors import FAILURE_ERROR_CODES, ErrorCode
from p0_baseline.manifest import load_manifest
from p0_baseline.models import WorkingTreeState
from p0_baseline.preflight import (
    PreflightError,
    RuntimeProbe,
    inspect_preflight,
    sanitized_worker_env,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = load_manifest(REPOSITORY_ROOT / "p0_baseline" / "manifest.json")
SUPPORTED = RuntimeProbe("CPython", "3.12.13", "Darwin", "arm64")
CORE_TARGETS = ("core", "core.client", "config.paths", "tools.base")
LOCKED_VERSIONS = {
    "certifi": "2026.6.17",
    "charset-normalizer": "3.4.9",
    "idna": "3.18",
    "requests": "2.34.2",
    "urllib3": "2.7.0",
}
HASH_A = "a" * 64
HASH_B = "b" * 64


class PreflightTests(unittest.TestCase):
    def _git(self, root: Path, *args: str) -> str:
        completed = subprocess.run(
            ["git", "-c", "user.name=P0 Tests", "-c", "user.email=p0@example.invalid", *args],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        )
        return completed.stdout.strip()

    def _repository(self, root: Path) -> None:
        self._git(root, "init", "-q")
        files = {
            "core/__init__.py": "raise RuntimeError('must not import core')\n",
            "core/client.py": "VALUE = 1\n",
            "config/paths.py": "VALUE = 1\n",
            "tools/__init__.py": "raise RuntimeError('must not import tools')\n",
            "tools/base.py": "VALUE = 1\n",
            ".gitignore": "ignored-runtime.txt\n",
            "requirements-p0.lock": (
                REPOSITORY_ROOT / "requirements-p0.lock"
            ).read_text(encoding="utf-8"),
        }
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        self._git(root, "add", ".")
        self._git(root, "commit", "-q", "-m", "fixture")

    def _inspect(self, root: Path, **changes: object):
        versions = dict(LOCKED_VERSIONS)
        versions.update(changes.pop("versions", {}))
        with mock.patch(
            "p0_baseline.preflight.metadata.version",
            side_effect=lambda name: versions[name],
        ):
            return inspect_preflight(
                MANIFEST,
                root,
                runtime_probe=changes.pop("runtime_probe", SUPPORTED),
                module_names=changes.pop("module_names", CORE_TARGETS),
                **changes,
            )

    def test_clean_repository_snapshot_uses_full_revision_and_relative_code_origins(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._repository(root)

            snapshot = self._inspect(root)

            self.assertRegex(snapshot.revision, r"^[0-9a-f]{40}$")
            self.assertEqual("<repository-root>", snapshot.repository_root)
            self.assertIs(snapshot.working_tree_state, WorkingTreeState.CLEAN)
            self.assertEqual(
                {
                    "config.paths": "config/paths.py",
                    "core": "core/__init__.py",
                    "core.client": "core/client.py",
                    "tools.base": "tools/base.py",
                },
                dict(snapshot.code_origins),
            )
            self.assertTrue(snapshot.supported)
            self.assertFalse(snapshot.personal_credentials_loaded)
            self.assertEqual((), snapshot.violations)

    def test_dirty_tree_is_recorded_but_ignored_runtime_files_do_not_make_it_dirty(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._repository(root)
            (root / "ignored-runtime.txt").write_text("runtime", encoding="utf-8")
            clean = self._inspect(root)
            self.assertIs(clean.working_tree_state, WorkingTreeState.CLEAN)

            (root / "core" / "client.py").write_text("VALUE = 2\n", encoding="utf-8")
            dirty = self._inspect(root)
            self.assertIs(dirty.working_tree_state, WorkingTreeState.DIRTY)
            self.assertTrue(dirty.supported)

    def test_unsupported_runtime_is_a_stable_environment_violation(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._repository(root)

            snapshot = self._inspect(
                root,
                runtime_probe=RuntimeProbe("CPython", "3.11.9", "Linux", "x86_64"),
            )

            self.assertFalse(snapshot.supported)
            self.assertEqual(ErrorCode.ENV_UNSUPPORTED, snapshot.violations[0].code)
            self.assertNotIn(str(root), snapshot.to_dict().__repr__())

    def test_code_origin_symlink_outside_checkout_is_rejected_without_importing_modules(self) -> None:
        with TemporaryDirectory() as directory, TemporaryDirectory() as adjacent:
            root = Path(directory)
            self._repository(root)
            outside = Path(adjacent) / "client.py"
            outside.write_text("VALUE = 'adjacent'\n", encoding="utf-8")
            (root / "core" / "client.py").unlink()
            (root / "core" / "client.py").symlink_to(outside)

            snapshot = self._inspect(root)

            self.assertTrue(snapshot.supported)
            self.assertIn(ErrorCode.CODE_ORIGIN_MISMATCH, tuple(item.code for item in snapshot.violations))
            self.assertNotIn("adjacent", snapshot.to_dict().__repr__())

            (root / "rogue.py").write_text("VALUE = 'untracked'\n", encoding="utf-8")
            untracked = self._inspect(root, module_names=("rogue",))
            self.assertEqual(ErrorCode.CODE_ORIGIN_MISMATCH, untracked.violations[0].code)
            self.assertEqual({}, dict(untracked.code_origins))

    def test_non_repository_is_a_stable_preflight_error(self) -> None:
        with TemporaryDirectory() as directory:
            with self.assertRaises(PreflightError) as caught:
                inspect_preflight(MANIFEST, Path(directory), runtime_probe=SUPPORTED)
            self.assertEqual(ErrorCode.CHECK_ERROR, caught.exception.code)

    def test_dependency_drift_is_reported_without_accepting_a_caller_fingerprint(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._repository(root)

            snapshot = self._inspect(root, versions={"requests": "0.0.0"})

            self.assertNotEqual(MANIFEST.dependency_fingerprint, snapshot.dependency_fingerprint)
            self.assertTrue(snapshot.supported)
            self.assertEqual(
                [ErrorCode.DEPENDENCY_UNDECLARED],
                [item.code for item in snapshot.violations],
            )
            self.assertIn(snapshot.violations[0].code, FAILURE_ERROR_CODES)
            self.assertEqual("requirements-p0.lock", snapshot.violations[0].target)

    def test_dependency_lock_parser_rejects_ambiguous_or_unhashed_declarations(self) -> None:
        invalid_locks = {
            "non_normalized_name": (
                f"Bad_Name==1.0 \\\n    --hash=sha256:{HASH_A}\n"
            ),
            "imprecise_version": (
                f"requests==2.* \\\n    --hash=sha256:{HASH_A}\n"
            ),
            "environment_marker": (
                f"requests==2.34.2;python_version>='3.12' \\\n    --hash=sha256:{HASH_A}\n"
            ),
            "direct_url": "requests @ https://example.invalid/archive.whl\n",
            "duplicate_pin": (
                f"requests==2.34.2 \\\n    --hash=sha256:{HASH_A}\n"
                f"requests==2.34.2 \\\n    --hash=sha256:{HASH_B}\n"
            ),
            "missing_hash": "requests==2.34.2 \\\n",
            "dangling_hash_continuation": (
                f"requests==2.34.2 \\\n    --hash=sha256:{HASH_A} \\\n"
            ),
            "hash_before_pin": (
                f"    --hash=sha256:{HASH_A}\n"
                f"requests==2.34.2 \\\n    --hash=sha256:{HASH_B}\n"
            ),
            "hash_after_terminated_hash": (
                f"requests==2.34.2 \\\n    --hash=sha256:{HASH_A}\n"
                f"    --hash=sha256:{HASH_B}\n"
            ),
            "duplicate_hash": (
                f"requests==2.34.2 \\\n    --hash=sha256:{HASH_A} \\\n"
                f"    --hash=sha256:{HASH_A}\n"
            ),
        }

        for label, lock_content in invalid_locks.items():
            with self.subTest(label=label), TemporaryDirectory() as directory:
                root = Path(directory)
                self._repository(root)
                (root / "requirements-p0.lock").write_text(lock_content, encoding="utf-8")

                snapshot = self._inspect(root)

                self.assertEqual(
                    [ErrorCode.DEPENDENCY_UNDECLARED],
                    [item.code for item in snapshot.violations],
                )
                self.assertIn(snapshot.violations[0].code, FAILURE_ERROR_CODES)

    def test_worker_environment_removes_credentials_proxies_and_telemetry_without_leaking_values(self) -> None:
        secret = "p0-super-secret-value"
        blocked_names = {
            "OPENAI_API_KEY",
            "CUSTOM_SESSION_COOKIE",
            "HTTP_PROXY",
            "https_proxy",
            "OTEL_EXPORTER_OTLP_HEADERS",
            "LANGCHAIN_TRACING_V2",
            "AWS_PROFILE",
            "CUSTOM_PROVIDER_BASE_URL",
            "CUSTOM_PROVIDER_REGION",
            "USER",
            "LC_OPENAI_API_KEY",
            "LC_SESSION_COOKIE",
            "LC_CUSTOM_PROVIDER_BASE_URL",
        }

        class SecretUnreadableEnvironment(dict[str, str]):
            def __getitem__(self, name: str) -> str:
                if name in blocked_names:
                    raise AssertionError(f"secret value was read: {name}")
                return super().__getitem__(name)

        source = SecretUnreadableEnvironment({
            "PATH": "/usr/bin",
            "LC_ALL": "C",
            "LC_CTYPE": "UTF-8",
            "TMPDIR": "/tmp/p0-worker",
            "PYTHONHASHSEED": "0",
            "OPENAI_API_KEY": secret,
            "CUSTOM_SESSION_COOKIE": secret,
            "HTTP_PROXY": f"https://user:{secret}@proxy.invalid",
            "https_proxy": f"https://{secret}@proxy.invalid",
            "OTEL_EXPORTER_OTLP_HEADERS": f"authorization={secret}",
            "LANGCHAIN_TRACING_V2": "true",
            "AWS_PROFILE": secret,
            "CUSTOM_PROVIDER_BASE_URL": f"https://{secret}.invalid",
            "CUSTOM_PROVIDER_REGION": "private-region",
            "USER": "personal-user",
            "LC_OPENAI_API_KEY": secret,
            "LC_SESSION_COOKIE": secret,
            "LC_CUSTOM_PROVIDER_BASE_URL": f"https://{secret}.invalid",
        })

        sanitized = sanitized_worker_env(source)

        self.assertEqual(
            {
                "PATH": "/usr/bin",
                "LC_ALL": "C",
                "LC_CTYPE": "UTF-8",
                "TMPDIR": "/tmp/p0-worker",
                "PYTHONHASHSEED": "0",
            },
            sanitized,
        )
        self.assertNotIn(secret, repr(sanitized))


if __name__ == "__main__":
    unittest.main()
