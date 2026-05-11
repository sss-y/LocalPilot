"""Formatting helpers for tool modules."""

from __future__ import annotations

import os
import sys
import traceback
from typing import Any


def format_error(exc: BaseException) -> str:
    """Return a compact error string with the last traceback frame when available."""
    exc_type, _, exc_traceback = sys.exc_info()
    if exc_traceback:
        frames = traceback.extract_tb(exc_traceback)
        if frames:
            frame = frames[-1]
            return (
                f"{(exc_type or type(exc)).__name__}: {exc} @ "
                f"{os.path.basename(frame.filename)}:{frame.lineno}, "
                f"{frame.name} -> `{frame.line}`"
            )
    return f"{type(exc).__name__}: {exc}"


def smart_format(data: Any, max_str_len: int = 100, omit_str: str = " ... ") -> str:
    """Truncate long values by keeping the head and tail."""
    text = data if isinstance(data, str) else str(data)
    if len(text) < max_str_len + len(omit_str) * 2:
        return text
    half = max_str_len // 2
    return f"{text[:half]}{omit_str}{text[-half:]}"
