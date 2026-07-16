"""Closed adapter registry for P0 check descriptors."""

from __future__ import annotations

from dataclasses import dataclass

from .adapters import Adapter, InternalAdapter, UnittestAdapter
from .errors import ErrorCode
from .models import Diagnostic


class AdapterLookupError(LookupError):
    code = ErrorCode.MANIFEST_INVALID

    def __init__(self, adapter: str) -> None:
        self.adapter = adapter
        super().__init__("P0 adapter is not registered.")

    def to_diagnostic(self) -> Diagnostic:
        return Diagnostic(
            code=self.code,
            message="Required check adapter is not registered.",
            failure_type="adapter",
            target="adapter-registry",
            recoverable=False,
        )


@dataclass(frozen=True)
class AdapterRegistry:
    unittest: UnittestAdapter
    internal: InternalAdapter

    def __post_init__(self) -> None:
        if not isinstance(self.unittest, UnittestAdapter):
            raise TypeError("unittest adapter is invalid")
        if not isinstance(self.internal, InternalAdapter):
            raise TypeError("internal adapter is invalid")

    def resolve(self, name: str) -> Adapter:
        if name == "unittest":
            return self.unittest
        if name == "internal":
            return self.internal
        raise AdapterLookupError(name)
