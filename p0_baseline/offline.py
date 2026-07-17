"""Offline network guard for the P0 verification parent process."""

from __future__ import annotations

import ipaddress
import re
import socket
import threading
from urllib.parse import urlsplit

from p0_baseline.errors import ErrorCode
from p0_baseline.models import Diagnostic


_SAFE_HOST = re.compile(r"(?:[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?)\Z", re.ASCII)
_SAFE_SOURCE = re.compile(r"[a-z0-9](?:[a-z0-9_.-]{0,126}[a-z0-9])?\Z", re.ASCII)
_OPERATIONS = frozenset(
    {"getaddrinfo", "create_connection", "connect", "connect_ex", "sendto"}
)
_PATCH_LOCK = threading.RLock()
_GUARD_STACK: list[OfflineGuard] = []


def _host_from_address(address: object) -> object:
    if isinstance(address, tuple):
        return address[0] if address else None
    return address


def _host_text(address: object) -> str | None:
    host = _host_from_address(address)
    if isinstance(host, bytes):
        try:
            return host.decode("ascii")
        except UnicodeDecodeError:
            return None
    return host if isinstance(host, str) else None


def _is_loopback_literal(address: object) -> bool:
    text = _host_text(address)
    if text is None:
        return False
    if "%" in text:
        return False
    if text.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        return False


def _safe_target_summary(address: object) -> str:
    text = _host_text(address)
    if text is None:
        return "<opaque-host>"
    candidate = text
    if "://" in candidate:
        try:
            candidate = urlsplit(candidate).hostname or ""
        except ValueError:
            candidate = ""
    candidate = candidate.casefold()
    try:
        return ipaddress.ip_address(candidate).compressed
    except ValueError:
        if _SAFE_HOST.fullmatch(candidate):
            return candidate
    return "<opaque-host>"


def _safe_source(source: str) -> str:
    if not isinstance(source, str):
        return "unknown-source"
    normalized = source.casefold()
    return normalized if _SAFE_SOURCE.fullmatch(normalized) else "unknown-source"


class NetworkPolicyViolation(OSError):
    """Stable, evidence-safe representation of a blocked network attempt."""

    code = ErrorCode.NETWORK_POLICY_VIOLATION

    def __init__(self, operation: str, source: str, address: object) -> None:
        self.operation = operation if operation in _OPERATIONS else "unknown-operation"
        self.source = _safe_source(source)
        self.target_summary = _safe_target_summary(address)
        super().__init__(self.code.value)

    def to_diagnostic(self) -> Diagnostic:
        return Diagnostic(
            code=self.code,
            message="offline network policy blocked an attempted connection",
            failure_type="network_policy",
            target=self.target_summary,
            recoverable=False,
            details={"operation": self.operation, "source": self.source},
        )


class OfflineGuardOwnershipError(RuntimeError):
    """The process-wide socket patch is no longer owned by this guard."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class OfflineGuard:
    """Install and reliably restore process-wide Python socket entry points."""

    def __init__(self, *, allow_loopback: bool = False, source: str = "parent") -> None:
        if type(allow_loopback) is not bool:
            raise TypeError("allow_loopback must be a boolean")
        self.allow_loopback = allow_loopback
        self.source = _safe_source(source)
        self._installed = False
        self._originals: tuple[object, ...] | None = None
        self._wrappers: tuple[object, ...] | None = None

    def _check(self, operation: str, address: object) -> None:
        if self.allow_loopback and _is_loopback_literal(address):
            return
        raise NetworkPolicyViolation(
            operation=operation,
            source=self.source,
            address=address,
        )

    def install(self) -> OfflineGuard:
        """Install this guard and return it for explicit lifecycle management."""

        with _PATCH_LOCK:
            if self._installed:
                raise RuntimeError("offline guard instance is already installed")
            originals = (
                socket.getaddrinfo,
                socket.create_connection,
                socket.socket.connect,
                socket.socket.connect_ex,
                socket.socket.sendto,
            )

            def guarded_getaddrinfo(host: object, *args: object, **kwargs: object):
                self._check("getaddrinfo", host)
                return originals[0](host, *args, **kwargs)

            def guarded_create_connection(address: object, *args: object, **kwargs: object):
                self._check("create_connection", address)
                return originals[1](address, *args, **kwargs)

            def guarded_connect(sock: socket.socket, address: object):
                self._check("connect", address)
                return originals[2](sock, address)

            def guarded_connect_ex(sock: socket.socket, address: object):
                self._check("connect_ex", address)
                return originals[3](sock, address)

            def guarded_sendto(sock: socket.socket, data: object, *args: object):
                if not args:
                    raise TypeError("sendto requires a destination address")
                address = args[-1]
                self._check("sendto", address)
                return originals[4](sock, data, *args)

            wrappers = (
                guarded_getaddrinfo,
                guarded_create_connection,
                guarded_connect,
                guarded_connect_ex,
                guarded_sendto,
            )
            self._originals = originals
            self._wrappers = wrappers
            (
                socket.getaddrinfo,
                socket.create_connection,
                socket.socket.connect,
                socket.socket.connect_ex,
                socket.socket.sendto,
            ) = wrappers
            _GUARD_STACK.append(self)
            self._installed = True
            return self

    def restore(self) -> None:
        """Restore exactly the socket functions captured by :meth:`install`."""

        with _PATCH_LOCK:
            if not self._installed:
                return None
            if not _GUARD_STACK or _GUARD_STACK[-1] is not self:
                raise OfflineGuardOwnershipError("P0_OFFLINE_GUARD_NOT_TOP")
            assert self._originals is not None
            assert self._wrappers is not None
            current = (
                socket.getaddrinfo,
                socket.create_connection,
                socket.socket.connect,
                socket.socket.connect_ex,
                socket.socket.sendto,
            )
            if any(actual is not expected for actual, expected in zip(current, self._wrappers)):
                raise OfflineGuardOwnershipError("P0_OFFLINE_GUARD_PATCH_OWNERSHIP_LOST")
            (
                socket.getaddrinfo,
                socket.create_connection,
                socket.socket.connect,
                socket.socket.connect_ex,
                socket.socket.sendto,
            ) = self._originals
            _GUARD_STACK.pop()
            self._installed = False
            self._originals = None
            self._wrappers = None
            return None

    def __enter__(self) -> OfflineGuard:
        return self.install()

    def __exit__(self, *exc_info: object) -> None:
        self.restore()
        return None


def offline_guard(*, allow_loopback: bool = False, source: str = "parent") -> OfflineGuard:
    return OfflineGuard(allow_loopback=allow_loopback, source=source)
