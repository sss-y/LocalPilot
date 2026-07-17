from __future__ import annotations

import socket
import threading
import unittest
from unittest import mock

from p0_baseline.errors import ErrorCode
from p0_baseline.offline import (
    NetworkPolicyViolation,
    OfflineGuardOwnershipError,
    offline_guard,
)


EXTERNAL_HOST = "https://user:password@example.invalid/path?token=secret"


class OfflineGuardTests(unittest.TestCase):
    def assert_violation(
        self,
        operation: str,
        call,
        *,
        source: str = "check.behavior",
    ) -> NetworkPolicyViolation:
        with self.assertRaises(NetworkPolicyViolation) as caught:
            call()
        violation = caught.exception
        self.assertEqual(ErrorCode.NETWORK_POLICY_VIOLATION, violation.code)
        self.assertEqual(operation, violation.operation)
        self.assertEqual(source, violation.source)
        self.assertEqual("example.invalid", violation.target_summary)
        rendered = repr(violation.to_diagnostic())
        for secret in ("user", "password", "token", "secret", "/path", "Cookie", "body"):
            self.assertNotIn(secret, rendered)
        return violation

    def test_external_dns_is_rejected_before_original_resolution(self) -> None:
        original = mock.Mock(name="getaddrinfo")
        with mock.patch.object(socket, "getaddrinfo", original):
            with offline_guard(source="check.behavior"):
                self.assert_violation(
                    "getaddrinfo",
                    lambda: socket.getaddrinfo(EXTERNAL_HOST, 443),
                )
        original.assert_not_called()

    def test_external_tcp_entry_points_are_rejected_before_original_calls(self) -> None:
        create_connection = mock.Mock(name="create_connection")
        connect = mock.Mock(name="connect")
        connect_ex = mock.Mock(name="connect_ex")
        with (
            mock.patch.object(socket, "create_connection", create_connection),
            mock.patch.object(socket.socket, "connect", connect),
            mock.patch.object(socket.socket, "connect_ex", connect_ex),
        ):
            with offline_guard(source="check.behavior"):
                self.assert_violation(
                    "create_connection",
                    lambda: socket.create_connection((EXTERNAL_HOST, 443)),
                )
                sock = mock.sentinel.socket
                self.assert_violation(
                    "connect", lambda: socket.socket.connect(sock, (EXTERNAL_HOST, 443))
                )
                self.assert_violation(
                    "connect_ex", lambda: socket.socket.connect_ex(sock, (EXTERNAL_HOST, 443))
                )
        create_connection.assert_not_called()
        connect.assert_not_called()
        connect_ex.assert_not_called()

    def test_external_udp_forms_are_rejected_before_original_sendto(self) -> None:
        sendto = mock.Mock(name="sendto")
        with mock.patch.object(socket.socket, "sendto", sendto):
            with offline_guard(source="check.behavior"):
                sock = mock.sentinel.socket
                self.assert_violation(
                    "sendto",
                    lambda: socket.socket.sendto(sock, b"body-secret", (EXTERNAL_HOST, 53)),
                )
                self.assert_violation(
                    "sendto",
                    lambda: socket.socket.sendto(
                        sock, b"body-secret", 0, (EXTERNAL_HOST, 53)
                    ),
                )
        sendto.assert_not_called()

    def test_default_policy_rejects_localhost_and_ip_loopback_literals(self) -> None:
        for host in ("localhost", "127.0.0.1", "::1", b"127.0.0.1"):
            with self.subTest(host=host), mock.patch.object(
                socket, "getaddrinfo", mock.Mock()
            ) as original:
                with offline_guard(source="check.loopback"):
                    with self.assertRaises(NetworkPolicyViolation):
                        socket.getaddrinfo(host, 80)
                original.assert_not_called()

    def test_explicit_loopback_policy_only_delegates_loopback_literals(self) -> None:
        accepted = ("localhost", "LOCALHOST", "127.0.0.1", "::1", b"::1")
        for host in accepted:
            with self.subTest(host=host), mock.patch.object(
                socket, "getaddrinfo", mock.Mock(return_value=[("stub",)])
            ) as original:
                with offline_guard(allow_loopback=True, source="check.fixture"):
                    self.assertEqual([("stub",)], socket.getaddrinfo(host, 80))
                original.assert_called_once_with(host, 80)

        for host in ("example.invalid", "0.0.0.0", "::", b"example.invalid"):
            with self.subTest(host=host), mock.patch.object(
                socket, "getaddrinfo", mock.Mock()
            ) as original:
                with offline_guard(allow_loopback=True, source="check.fixture"):
                    with self.assertRaises(NetworkPolicyViolation):
                        socket.getaddrinfo(host, 80)
                original.assert_not_called()

    def test_scoped_ipv6_loopback_is_rejected_before_dns_or_socket_calls(self) -> None:
        for host in ("::1%lo0", b"::1%lo0"):
            with self.subTest(host=host):
                getaddrinfo = mock.Mock(name="getaddrinfo")
                create_connection = mock.Mock(name="create_connection")
                with (
                    mock.patch.object(socket, "getaddrinfo", getaddrinfo),
                    mock.patch.object(socket, "create_connection", create_connection),
                ):
                    with offline_guard(allow_loopback=True, source="check.fixture"):
                        with self.assertRaises(NetworkPolicyViolation):
                            socket.getaddrinfo(host, 80)
                        with self.assertRaises(NetworkPolicyViolation):
                            socket.create_connection((host, 80))
                getaddrinfo.assert_not_called()
                create_connection.assert_not_called()

    def test_address_shapes_are_checked_without_dns(self) -> None:
        targets = (
            "203.0.113.1",
            b"2001:db8::1",
            ("203.0.113.2", 443),
            (b"2001:db8::2", 443, 0, 0),
        )
        for target in targets:
            with self.subTest(target=target), mock.patch.object(
                socket, "create_connection", mock.Mock()
            ) as original:
                with offline_guard():
                    with self.assertRaises(NetworkPolicyViolation):
                        socket.create_connection(target)
                original.assert_not_called()

    def test_nested_guards_and_exception_paths_restore_every_original(self) -> None:
        originals = (
            socket.getaddrinfo,
            socket.create_connection,
            socket.socket.connect,
            socket.socket.connect_ex,
            socket.socket.sendto,
        )
        with self.assertRaisesRegex(RuntimeError, "controlled"):
            with offline_guard(source="outer"):
                outer = socket.getaddrinfo
                with offline_guard(source="inner"):
                    self.assertIsNot(outer, socket.getaddrinfo)
                self.assertIs(outer, socket.getaddrinfo)
                raise RuntimeError("controlled")
        self.assertEqual(
            originals,
            (
                socket.getaddrinfo,
                socket.create_connection,
                socket.socket.connect,
                socket.socket.connect_ex,
                socket.socket.sendto,
            ),
        )

    def test_guard_instance_can_be_reused_after_restoration(self) -> None:
        original = mock.Mock(name="getaddrinfo")
        guard = offline_guard(source="check.reused")
        with mock.patch.object(socket, "getaddrinfo", original):
            for _ in range(2):
                with guard:
                    with self.assertRaises(NetworkPolicyViolation):
                        socket.getaddrinfo("example.invalid", 443)
                self.assertIs(original, socket.getaddrinfo)
        original.assert_not_called()

    def test_explicit_install_restore_and_unsafe_source_are_fail_closed(self) -> None:
        original = mock.Mock(name="getaddrinfo")
        with mock.patch.object(socket, "getaddrinfo", original):
            guard = offline_guard(source="Authorization Bearer source-secret")
            guard.install()
            try:
                with self.assertRaises(NetworkPolicyViolation) as caught:
                    socket.getaddrinfo(EXTERNAL_HOST, 443)
                self.assertEqual("unknown-source", caught.exception.source)
                self.assertNotIn("source-secret", repr(caught.exception.to_diagnostic()))
            finally:
                guard.restore()
            self.assertIs(original, socket.getaddrinfo)
        original.assert_not_called()

    def test_non_lifo_restore_fails_without_changing_guard_ownership(self) -> None:
        originals = (
            socket.getaddrinfo,
            socket.create_connection,
            socket.socket.connect,
            socket.socket.connect_ex,
            socket.socket.sendto,
        )
        outer = offline_guard(source="outer")
        inner = offline_guard(source="inner")
        outer.install()
        inner.install()
        inner_functions = (
            socket.getaddrinfo,
            socket.create_connection,
            socket.socket.connect,
            socket.socket.connect_ex,
            socket.socket.sendto,
        )
        try:
            with self.assertRaisesRegex(
                OfflineGuardOwnershipError, "P0_OFFLINE_GUARD_NOT_TOP"
            ):
                outer.restore()
            self.assertTrue(outer._installed)
            self.assertTrue(inner._installed)
            self.assertEqual(inner_functions, (
                socket.getaddrinfo,
                socket.create_connection,
                socket.socket.connect,
                socket.socket.connect_ex,
                socket.socket.sendto,
            ))
            with self.assertRaises(NetworkPolicyViolation):
                socket.getaddrinfo("example.invalid", 443)
        finally:
            inner.restore()
            outer.restore()
        self.assertEqual(originals, (
            socket.getaddrinfo,
            socket.create_connection,
            socket.socket.connect,
            socket.socket.connect_ex,
            socket.socket.sendto,
        ))

    def test_concurrent_interleaving_enforces_lifo_and_restores_initial_state(self) -> None:
        original = socket.getaddrinfo
        outer = offline_guard(source="thread.outer")
        inner = offline_guard(source="thread.inner")
        outer_ready = threading.Event()
        inner_ready = threading.Event()
        outer_rejected = threading.Event()
        inner_restored = threading.Event()
        errors: list[BaseException] = []

        def outer_thread() -> None:
            try:
                outer.install()
                outer_ready.set()
                if not inner_ready.wait(2):
                    raise AssertionError("inner guard did not install")
                with self.assertRaisesRegex(
                    OfflineGuardOwnershipError, "P0_OFFLINE_GUARD_NOT_TOP"
                ):
                    outer.restore()
                outer_rejected.set()
                if not inner_restored.wait(2):
                    raise AssertionError("inner guard did not restore")
                outer.restore()
            except BaseException as error:
                errors.append(error)

        def inner_thread() -> None:
            try:
                if not outer_ready.wait(2):
                    raise AssertionError("outer guard did not install")
                inner.install()
                inner_ready.set()
                if not outer_rejected.wait(2):
                    raise AssertionError("outer restore was not rejected")
                inner.restore()
                inner_restored.set()
            except BaseException as error:
                errors.append(error)

        threads = (threading.Thread(target=outer_thread), threading.Thread(target=inner_thread))
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(3)
        try:
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual([], errors)
            self.assertIs(original, socket.getaddrinfo)
        finally:
            if inner._installed:
                inner.restore()
            if outer._installed:
                outer.restore()

    def test_restore_detects_third_party_patch_without_overwriting_it(self) -> None:
        original = socket.getaddrinfo
        guard = offline_guard(source="check.ownership").install()
        guard_wrapper = socket.getaddrinfo
        third_party = mock.Mock(name="third_party_getaddrinfo")
        socket.getaddrinfo = third_party
        try:
            with self.assertRaisesRegex(
                OfflineGuardOwnershipError,
                "P0_OFFLINE_GUARD_PATCH_OWNERSHIP_LOST",
            ):
                guard.restore()
            self.assertIs(third_party, socket.getaddrinfo)
            self.assertTrue(guard._installed)
            socket.getaddrinfo = guard_wrapper
            guard.restore()
            self.assertIs(original, socket.getaddrinfo)
        finally:
            if guard._installed:
                socket.getaddrinfo = guard_wrapper
                guard.restore()


if __name__ == "__main__":
    unittest.main()
