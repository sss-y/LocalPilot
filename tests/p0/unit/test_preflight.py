from __future__ import annotations

from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from p0_baseline.errors import ErrorCode
from p0_baseline.manifest import load_manifest
from p0_baseline.models import WorkingTreeState
from p0_baseline.preflight import PreflightError, RuntimeProbe, inspect_preflight


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = load_manifest(REPOSITORY_ROOT / "p0_baseline" / "manifest.json")
SUPPORTED = RuntimeProbe("CPython", "3.12.13", "Darwin", "arm64")
CORE_TARGETS = ("core", "core.client", "config.paths", "tools.base")


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
        }
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        self._git(root, "add", ".")
        self._git(root, "commit", "-q", "-m", "fixture")

    def test_clean_repository_snapshot_uses_full_revision_and_relative_code_origins(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._repository(root)

            snapshot = inspect_preflight(
                MANIFEST,
                root,
                MANIFEST.dependency_fingerprint,
                runtime_probe=SUPPORTED,
                module_names=CORE_TARGETS,
            )

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
            clean = inspect_preflight(MANIFEST, root, "sha256:test", runtime_probe=SUPPORTED, module_names=CORE_TARGETS)
            self.assertIs(clean.working_tree_state, WorkingTreeState.CLEAN)

            (root / "core" / "client.py").write_text("VALUE = 2\n", encoding="utf-8")
            dirty = inspect_preflight(MANIFEST, root, "sha256:test", runtime_probe=SUPPORTED, module_names=CORE_TARGETS)
            self.assertIs(dirty.working_tree_state, WorkingTreeState.DIRTY)
            self.assertTrue(dirty.supported)

    def test_unsupported_runtime_is_a_stable_environment_violation(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._repository(root)

            snapshot = inspect_preflight(
                MANIFEST,
                root,
                "sha256:test",
                runtime_probe=RuntimeProbe("CPython", "3.11.9", "Linux", "x86_64"),
                module_names=CORE_TARGETS,
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

            snapshot = inspect_preflight(MANIFEST, root, "sha256:test", runtime_probe=SUPPORTED, module_names=CORE_TARGETS)

            self.assertTrue(snapshot.supported)
            self.assertIn(ErrorCode.CODE_ORIGIN_MISMATCH, tuple(item.code for item in snapshot.violations))
            self.assertNotIn("adjacent", snapshot.to_dict().__repr__())

            (root / "rogue.py").write_text("VALUE = 'untracked'\n", encoding="utf-8")
            untracked = inspect_preflight(
                MANIFEST,
                root,
                "sha256:test",
                runtime_probe=SUPPORTED,
                module_names=("rogue",),
            )
            self.assertEqual(ErrorCode.CODE_ORIGIN_MISMATCH, untracked.violations[0].code)
            self.assertEqual({}, dict(untracked.code_origins))

    def test_non_repository_is_a_stable_preflight_error(self) -> None:
        with TemporaryDirectory() as directory:
            with self.assertRaises(PreflightError) as caught:
                inspect_preflight(MANIFEST, Path(directory), "sha256:test", runtime_probe=SUPPORTED)
            self.assertEqual(ErrorCode.CHECK_ERROR, caught.exception.code)


if __name__ == "__main__":
    unittest.main()
