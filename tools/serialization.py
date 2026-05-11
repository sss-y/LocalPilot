"""Lightweight serialization helpers shared across tool modules."""

from __future__ import annotations


def json_default(obj):
    return list(obj) if isinstance(obj, set) else str(obj)
