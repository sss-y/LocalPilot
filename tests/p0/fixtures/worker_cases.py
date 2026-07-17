from __future__ import annotations

import socket
import unittest


GUARD_INSTALLED_AT_IMPORT = all(
    getattr(operation, "__p0_offline_guard__", False)
    for operation in (socket.getaddrinfo, socket.socket.connect, socket.socket.sendto)
)


class PassingFixture(unittest.TestCase):
    def test_passes(self) -> None:
        self.assertEqual(2, 1 + 1)


class FailingFixture(unittest.TestCase):
    def test_fails(self) -> None:
        self.fail("controlled failure")


class ErrorFixture(unittest.TestCase):
    def test_errors(self) -> None:
        raise RuntimeError("controlled error")


class SkippedFixture(unittest.TestCase):
    @unittest.skip("controlled skip")
    def test_is_skipped(self) -> None:
        self.fail("decorated skip must not execute")


class ExpectedFailureFixture(unittest.TestCase):
    @unittest.expectedFailure
    def test_is_expected_failure(self) -> None:
        self.fail("controlled expected failure")


class UnexpectedSuccessFixture(unittest.TestCase):
    @unittest.expectedFailure
    def test_is_unexpected_success(self) -> None:
        self.assertTrue(True)


class OfflineNetworkFixture(unittest.TestCase):
    """Exercise the real installed guard without allowing an unguarded OS call."""

    def _assert_guarded(self, operation) -> None:
        self.assertTrue(GUARD_INSTALLED_AT_IMPORT)
        self.assertTrue(getattr(operation, "__p0_offline_guard__", False))

    def test_external_dns_is_blocked(self) -> None:
        self._assert_guarded(socket.getaddrinfo)
        socket.getaddrinfo(
            "https://user:password@example.invalid/private/path?token=secret",
            443,
        )

    def test_external_tcp_is_blocked(self) -> None:
        self._assert_guarded(socket.socket.connect)
        sock = socket.socket()
        try:
            sock.connect(("203.0.113.17", 443))
        finally:
            sock.close()

    def test_external_udp_is_blocked(self) -> None:
        self._assert_guarded(socket.socket.sendto)
        sock = socket.socket(type=socket.SOCK_DGRAM)
        try:
            sock.sendto(b"body-secret", ("203.0.113.17", 53))
        finally:
            sock.close()
