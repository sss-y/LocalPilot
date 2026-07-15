from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CLASSIFICATION_PATH = REPOSITORY_ROOT / "plan" / "p0-test-asset-classification.md"


class AssetGovernanceTests(unittest.TestCase):
    def assert_git_ignored(self, relative_path: str) -> None:
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", "--no-index", "--", relative_path],
            cwd=REPOSITORY_ROOT,
            check=False,
        )
        self.assertEqual(0, result.returncode, f"expected Git to ignore {relative_path}")

    def assert_git_trackable(self, relative_path: str) -> None:
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", "--no-index", "--", relative_path],
            cwd=REPOSITORY_ROOT,
            check=False,
        )
        self.assertEqual(1, result.returncode, f"expected Git to track {relative_path}")

    def test_only_p0_tests_are_released_from_tests_ignore_rule(self) -> None:
        self.assert_git_trackable("tests/p0/unit/test_cli_entrypoint.py")
        self.assert_git_trackable("tests/p0/unit/test_asset_governance.py")
        self.assert_git_ignored("tests/test_session.py")

    def test_runtime_and_credentials_remain_ignored(self) -> None:
        for relative_path in (
            "temp/",
            "mykey.py",
            "core/mykey.json",
            ".env",
            "tests/p0/unit/__pycache__/",
            "tests/p0/unit/example.pyc",
        ):
            with self.subTest(relative_path=relative_path):
                self.assert_git_ignored(relative_path)

    def test_every_discovered_historical_test_has_an_explicit_decision(self) -> None:
        classification = CLASSIFICATION_PATH.read_text(encoding="utf-8")
        expected = {
            "tests/test_agent_paths.py": (
                "重写并迁移",
                "`tests/p0/behavior/test_cli_module_paths.py`",
            ),
            "tests/test_session.py": (
                "选择性重写",
                "`tests/p0/behavior/test_model_responses.py` 与 "
                "`tests/p0/behavior/test_transport_errors.py`",
            ),
            "tests/test_llm_client.py": (
                "选择性重写",
                "`tests/p0/behavior/test_model_responses.py`",
            ),
            "tests/test_repo_handler_tools.py": (
                "选择性迁移",
                "`tests/p0/behavior/test_tool_dispatch.py`",
            ),
            "tests/test_repo_tools.py": ("P0 排除", "无"),
            "tests/test_evals.py": ("P0 排除", "无"),
            "test_client.py": ("P0 排除", "无"),
        }
        for relative_path, (decision, target) in expected.items():
            with self.subTest(relative_path=relative_path):
                self.assertTrue((REPOSITORY_ROOT / relative_path).is_file())
                row_pattern = (
                    rf"^\| `{re.escape(relative_path)}` \| {re.escape(decision)} \| "
                    rf"{re.escape(target)} \|"
                )
                self.assertRegex(classification, re.compile(row_pattern, re.MULTILINE))


if __name__ == "__main__":
    unittest.main()
