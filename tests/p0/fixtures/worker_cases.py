from __future__ import annotations

import unittest


class PassingFixture(unittest.TestCase):
    def test_passes(self) -> None:
        self.assertEqual(2, 1 + 1)


class FailingFixture(unittest.TestCase):
    def test_fails(self) -> None:
        self.fail("controlled failure")


class ErrorFixture(unittest.TestCase):
    def test_errors(self) -> None:
        raise RuntimeError("controlled error")
