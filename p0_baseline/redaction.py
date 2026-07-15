"""Fail-closed redaction for values crossing the P0 evidence boundary.

The module only accepts JSON containers and safe scalar values.  It never
coerces unknown objects, exceptions, or failed inputs to text because doing so
could execute user code or disclose their contents.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


REDACTED_PLACEHOLDER = "<redacted>"
TRUNCATED_PLACEHOLDER = "<truncated>"
DROPPED_PLACEHOLDER = "<dropped>"

DEFAULT_MAX_DEPTH = 8
DEFAULT_MAX_ITEMS = 64
DEFAULT_MAX_STRING_LENGTH = 512
DEFAULT_MAX_NODES = 4096
DEFAULT_MAX_OUTPUT_CHARS = 65536
MIN_MAX_OUTPUT_CHARS = len(json.dumps(TRUNCATED_PLACEHOLDER))

_SENSITIVE_KEY_PARTS = (
    "api",
    "apikey",
    "authorization",
    "cookie",
    "key",
    "password",
    "secret",
    "token",
)
_FORBIDDEN_RAW_KEY_PARTS = (
    "traceback",
    "exception",
    "exceptiondetail",
    "prompt",
    "modelraw",
    "rawmodel",
    "rawresponse",
    "toolfullresult",
    "fulltoolresult",
)
_SAFE_COUNT_METADATA_KEYS = frozenset(
    {
        ("request", "count"),
        ("result", "count"),
    }
)
_MAX_SAFE_COUNT = (1 << 63) - 1


class _FrozenDict(dict[str, Any]):
    """A JSON-serializable dictionary that cannot be modified after creation."""

    def _immutable(self, *args: object, **kwargs: object) -> None:
        raise TypeError("redacted values are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable

    def __ior__(self, other: object) -> _FrozenDict:
        self._immutable(other)
        return self


class _FrozenList(list[Any]):
    """A JSON-serializable list that cannot be modified after creation."""

    def _immutable(self, *args: object, **kwargs: object) -> None:
        raise TypeError("redacted values are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable


@dataclass(frozen=True)
class RedactionResult:
    """Immutable result and auditable replacement counters."""

    value: Any
    matched_values: int
    truncated: int
    dropped: int


@dataclass
class _Counters:
    matched_values: int = 0
    truncated: int = 0
    dropped: int = 0
    nodes: int = 0


def _is_sensitive_key(key: str) -> bool:
    lowered = key.casefold()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def _key_tokens(key: str) -> tuple[str, ...]:
    separated = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", key)
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", separated)
    return tuple(part.casefold() for part in re.findall(r"[A-Za-z0-9]+", separated))


def _is_forbidden_raw_value(key: str, value: object) -> bool:
    tokens = _key_tokens(key)
    token_set = frozenset(tokens)
    if tokens in _SAFE_COUNT_METADATA_KEYS:
        return not (
            type(value) is int and 0 <= value <= _MAX_SAFE_COUNT
        )

    normalized = "".join(character for character in key.casefold() if character.isalnum())
    return (
        tokens == ("body",)
        or "request" in token_set
        or "tool" in token_set
        or any(part in normalized for part in _FORBIDDEN_RAW_KEY_PARTS)
    )


def _safe_url(value: str, counters: _Counters, *, max_items: int) -> str | None:
    """Return a URL with credentials and every query value removed."""
    try:
        parts = urlsplit(value)
        if parts.scheme.casefold() not in {"http", "https"} or not parts.netloc:
            return None
        hostname = parts.hostname
        if not hostname:
            return DROPPED_PLACEHOLDER

        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        port = parts.port
        netloc = hostname if port is None else f"{hostname}:{port}"

        if parts.username is not None or parts.password is not None:
            counters.matched_values += 1

        query_items = parse_qsl(parts.query, keep_blank_values=True)
        safe_query: list[tuple[str, str]] = []
        for key, _original_value in query_items[:max_items]:
            safe_key = REDACTED_PLACEHOLDER if _is_sensitive_key(key) else key
            safe_query.append((safe_key, REDACTED_PLACEHOLDER))
            counters.matched_values += 1
        if len(query_items) > max_items:
            safe_query.append((TRUNCATED_PLACEHOLDER, TRUNCATED_PLACEHOLDER))
            counters.truncated += 1

        if parts.fragment:
            counters.matched_values += 1

        return urlunsplit(
            (parts.scheme.casefold(), netloc, parts.path, urlencode(safe_query), "")
        )
    except BaseException:
        counters.dropped += 1
        return DROPPED_PLACEHOLDER


def _freeze_dict(value: dict[str, Any]) -> _FrozenDict:
    result = _FrozenDict()
    dict.update(result, value)
    return result


def _freeze_list(value: list[Any]) -> _FrozenList:
    result = _FrozenList()
    list.extend(result, value)
    return result


def _sanitize(
    value: object,
    counters: _Counters,
    active_containers: set[int],
    *,
    depth: int,
    max_depth: int,
    max_items: int,
    max_string_length: int,
    max_nodes: int,
) -> object:
    counters.nodes += 1
    if counters.nodes > max_nodes:
        counters.truncated += 1
        return TRUNCATED_PLACEHOLDER

    if depth >= max_depth and type(value) in {dict, list}:
        counters.truncated += 1
        return TRUNCATED_PLACEHOLDER

    if value is None or type(value) in {bool, int}:
        return value
    if type(value) is float:
        if math.isfinite(value):
            return value
        counters.dropped += 1
        return DROPPED_PLACEHOLDER
    if type(value) is str:
        safe_url = _safe_url(value, counters, max_items=max_items)
        safe_value = value if safe_url is None else safe_url
        if len(safe_value) > max_string_length:
            counters.truncated += 1
            return safe_value[:max_string_length] + TRUNCATED_PLACEHOLDER
        return safe_value

    if type(value) not in {dict, list}:
        counters.dropped += 1
        return DROPPED_PLACEHOLDER

    identity = id(value)
    if identity in active_containers:
        counters.dropped += 1
        return DROPPED_PLACEHOLDER
    active_containers.add(identity)
    try:
        if type(value) is dict:
            safe_items: dict[str, object] = {}
            items = list(dict.items(value))
            for key, item in items[:max_items]:
                if type(key) is not str:
                    counters.dropped += 1
                    continue
                if _is_sensitive_key(key) or _is_forbidden_raw_value(key, item):
                    safe_items[key] = REDACTED_PLACEHOLDER
                    counters.matched_values += 1
                    continue
                safe_items[key] = _sanitize(
                    item,
                    counters,
                    active_containers,
                    depth=depth + 1,
                    max_depth=max_depth,
                    max_items=max_items,
                    max_string_length=max_string_length,
                    max_nodes=max_nodes,
                )
            if len(items) > max_items:
                safe_items[TRUNCATED_PLACEHOLDER] = TRUNCATED_PLACEHOLDER
                counters.truncated += 1
            return _freeze_dict(safe_items)

        safe_values = [
            _sanitize(
                item,
                counters,
                active_containers,
                depth=depth + 1,
                max_depth=max_depth,
                max_items=max_items,
                max_string_length=max_string_length,
                max_nodes=max_nodes,
            )
            for item in list.__getitem__(value, slice(0, max_items))
        ]
        if len(value) > max_items:
            safe_values.append(TRUNCATED_PLACEHOLDER)
            counters.truncated += 1
        return _freeze_list(safe_values)
    except BaseException:
        counters.dropped += 1
        return DROPPED_PLACEHOLDER
    finally:
        active_containers.discard(identity)


def _positive_limit(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _output_limit(value: object) -> int:
    result = _positive_limit(value, "max_output_chars")
    if result < MIN_MAX_OUTPUT_CHARS:
        raise ValueError(
            f"max_output_chars must be at least {MIN_MAX_OUTPUT_CHARS} characters"
        )
    return result


def redact(
    value: object,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_items: int = DEFAULT_MAX_ITEMS,
    max_string_length: int = DEFAULT_MAX_STRING_LENGTH,
    max_nodes: int = DEFAULT_MAX_NODES,
    max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
) -> RedactionResult:
    """Return an immutable, bounded, JSON-serializable safe representation.

    Unsupported inputs and sanitizer failures are replaced without invoking
    their ``str``/``repr`` methods or retaining exception tracebacks.
    """
    validated_depth = _positive_limit(max_depth, "max_depth")
    validated_items = _positive_limit(max_items, "max_items")
    validated_string = _positive_limit(max_string_length, "max_string_length")
    validated_nodes = _positive_limit(max_nodes, "max_nodes")
    validated_output = _output_limit(max_output_chars)
    counters = _Counters()
    try:
        safe_value = _sanitize(
            value,
            counters,
            set(),
            depth=0,
            max_depth=validated_depth,
            max_items=validated_items,
            max_string_length=validated_string,
            max_nodes=validated_nodes,
        )
        encoded = json.dumps(safe_value, sort_keys=True, separators=(",", ":"))
        if len(encoded) > validated_output:
            counters.truncated += 1
            safe_value = TRUNCATED_PLACEHOLDER
        return RedactionResult(
            value=safe_value,
            matched_values=counters.matched_values,
            truncated=counters.truncated,
            dropped=counters.dropped,
        )
    except BaseException:
        return RedactionResult(
            value=DROPPED_PLACEHOLDER,
            matched_values=counters.matched_values,
            truncated=counters.truncated,
            dropped=counters.dropped + 1,
        )
