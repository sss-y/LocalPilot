from __future__ import annotations

import importlib.abc
import os
from pathlib import Path
import runpy
import subprocess
import sys
import unittest
from unittest import mock

from p0_baseline.cli import build_parser


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PYTHON = Path(sys.executable).resolve()


class _RejectProductImports(importlib.abc.MetaPathFinder):
    """Fail if the help path reaches product or personal configuration code."""

    FORBIDDEN_ROOTS = {"agent", "config", "core", "runagent"}

    def find_spec(self, fullname: str, path=None, target=None):  # noqa: ANN001
        if fullname.partition(".")[0] in self.FORBIDDEN_ROOTS:
            raise AssertionError(f"help imported forbidden module: {fullname}")
        return None


class CliEntrypointTests(unittest.TestCase):
    def test_parser_reserves_format_and_output_boundaries(self) -> None:
        arguments = build_parser().parse_args(
            ["--format", "json", "--output", "temp/p0-baseline/report.json"]
        )

        self.assertEqual(arguments.format, "json")
        self.assertEqual(arguments.output, "temp/p0-baseline/report.json")

    def test_help_from_repository_root_returns_zero(self) -> None:
        completed = subprocess.run(
            [str(PYTHON), "-m", "p0_baseline", "--help"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--format {human,json}", completed.stdout)
        self.assertIn("--output", completed.stdout)

    def test_help_from_non_root_with_explicit_pythonpath_returns_zero(self) -> None:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(REPOSITORY_ROOT)
        completed = subprocess.run(
            [str(PYTHON), "-m", "p0_baseline", "--help"],
            cwd=Path("/tmp"),
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("usage:", completed.stdout)

    def test_help_does_not_import_product_or_personal_configuration(self) -> None:
        finder = _RejectProductImports()
        with (
            mock.patch.object(sys, "argv", ["p0_baseline", "--help"]),
            mock.patch.object(sys, "meta_path", [finder, *sys.meta_path]),
            self.assertRaises(SystemExit) as exit_context,
        ):
            runpy.run_module("p0_baseline", run_name="__main__")

        self.assertEqual(exit_context.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
