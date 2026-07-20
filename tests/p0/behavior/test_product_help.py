from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import os
from pathlib import Path
import runpy
import sys
import unittest
from unittest.mock import patch

from p0_baseline.offline import offline_guard
from p0_baseline.preflight import sanitized_worker_env


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class ProductHelpSmokeTests(unittest.TestCase):
    def test_help_is_offline_credential_free_and_restores_process_state(self) -> None:
        original_environment = dict(os.environ)
        original_argv = sys.argv
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        stdout = StringIO()
        stderr = StringIO()

        with (
            patch.dict(os.environ, sanitized_worker_env(os.environ), clear=True),
            patch.object(sys, "argv", ["runagent.py", "--help"]),
            patch(
                "core.config.reload_mykeys",
                side_effect=AssertionError("help must not load credentials"),
            ),
            offline_guard(source="product-help-smoke"),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
            self.assertRaises(SystemExit) as caught,
        ):
            runpy.run_path(str(REPOSITORY_ROOT / "runagent.py"), run_name="__main__")

        self.assertEqual(0, caught.exception.code)
        self.assertTrue(stdout.getvalue().strip())
        self.assertEqual(original_environment, dict(os.environ))
        self.assertIs(original_argv, sys.argv)
        self.assertIs(original_stdout, sys.stdout)
        self.assertIs(original_stderr, sys.stderr)


if __name__ == "__main__":
    unittest.main()
