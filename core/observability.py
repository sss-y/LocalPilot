"""Structured JSONL event logging for LocalPilot.

The event log is for troubleshooting control flow, not for storing full prompt,
file, or tool payload content. Keep event extras compact and metadata-oriented.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import os
import sys
import traceback as traceback_module
import uuid
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Iterator
from urllib.parse import urlparse

from config.paths import TEMP_DIR


LOG_DIR = TEMP_DIR / "logs"
_RUN_CONTEXT: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "localpilot_run_context",
    default={},
)

_LEVELS = {"debug": 10, "info": 20, "warning": 30, "error": 40}
_DEFAULT_MAX_STR = 500
_SENSITIVE_KEYS = ("api", "apikey", "authorization", "cookie", "key", "password", "secret", "token")


def _current_level() -> int:
    raw = os.environ.get("LOCALPILOT_LOG_LEVEL", "info").strip().lower()
    return _LEVELS.get(raw, _LEVELS["info"])


def _should_log(level: str) -> bool:
    return _LEVELS.get(level, _LEVELS["info"]) >= _current_level()


def _jsonl_path() -> Path:
    return LOG_DIR / f"agent-{datetime.now():%Y-%m-%d}.jsonl"


def _redact_key(key: str) -> bool:
    k = key.lower()
    return any(part in k for part in _SENSITIVE_KEYS)


def _safe_text(value: str, max_len: int = _DEFAULT_MAX_STR) -> str:
    value = value.replace("\r", "\\r").replace("\n", "\\n")
    if len(value) <= max_len:
        return value
    return f"{value[:max_len]}...[truncated {len(value) - max_len} chars]"


def summarize(value: Any, max_len: int = _DEFAULT_MAX_STR) -> Any:
    """Return a compact, JSON-serializable, redacted summary."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _safe_text(value, max_len=max_len)
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        result = [summarize(item, max_len=max_len) for item in items[:20]]
        if len(items) > 20:
            result.append(f"...[{len(items) - 20} more items]")
        return result
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for idx, (key, item) in enumerate(value.items()):
            if idx >= 40:
                result["..."] = f"{len(value) - 40} more keys"
                break
            key_text = str(key)
            result[key_text] = "[REDACTED]" if _redact_key(key_text) else summarize(item, max_len=max_len)
        return result
    return _safe_text(repr(value), max_len=max_len)


def content_summary(value: Any, max_len: int = 200) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = repr(value)
    return _safe_text(value.strip(), max_len=max_len)


def current_run_id() -> str | None:
    return _RUN_CONTEXT.get({}).get("run_id")


def new_run_context(entrypoint: str, **extra: Any) -> contextvars.Token[dict[str, Any]]:
    context = {
        "run_id": uuid.uuid4().hex[:12],
        "entrypoint": entrypoint,
        **{key: summarize(value) for key, value in extra.items() if value is not None},
    }
    return _RUN_CONTEXT.set(context)


def reset_run_context(token: contextvars.Token[dict[str, Any]]) -> None:
    _RUN_CONTEXT.reset(token)


def _stderr_line(record: dict[str, Any]) -> str:
    msg = record.get("message") or record.get("event", "")
    return f"[{record.get('level')}] {record.get('event')} run_id={record.get('run_id')} {msg}\n"


def log_event(event: str, level: str = "info", message: str | None = None, **extra: Any) -> None:
    """Append one compact structured event. Logging failures never affect runtime."""
    level = level.lower()
    if not _should_log(level):
        return
    context = _RUN_CONTEXT.get({})
    record = {
        "ts": datetime.now().isoformat(timespec="milliseconds"),
        "level": level,
        "event": event,
        "run_id": context.get("run_id"),
        "entrypoint": context.get("entrypoint"),
        "pid": os.getpid(),
    }
    for key, value in context.items():
        if key not in record:
            record[key] = value
    if message:
        record["message"] = content_summary(message, max_len=500)
    for key, value in extra.items():
        if value is not None:
            record[key] = summarize(value, max_len=20000 if key == "traceback" else _DEFAULT_MAX_STR)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(_jsonl_path(), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        if os.environ.get("LOCALPILOT_LOG_STDERR") == "1":
            sys.stderr.write(_stderr_line(record))
    except Exception:
        pass


def log_exception(
    event: str,
    exc: BaseException,
    level: str = "error",
    recoverable: bool = False,
    user_visible_msg: str | None = None,
    **extra: Any,
) -> None:
    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
        raise exc
    log_event(
        event,
        level=level,
        exc_type=type(exc).__name__,
        exc_msg=str(exc),
        traceback="".join(traceback_module.format_exception(type(exc), exc, exc.__traceback__)),
        recoverable=recoverable,
        user_visible_msg=user_visible_msg,
        **extra,
    )


@contextlib.contextmanager
def timed_event(event: str, level: str = "info", **extra: Any) -> Iterator[None]:
    start = perf_counter()
    log_event(f"{event}_start", level=level, **extra)
    try:
        yield
    except Exception as exc:
        log_exception(f"{event}_exception", exc, recoverable=False, **extra)
        raise
    finally:
        log_event(f"{event}_end", level=level, duration_ms=round((perf_counter() - start) * 1000, 2), **extra)


def url_host(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parsed = urlparse(url)
        return parsed.netloc or parsed.path.split("/")[0]
    except Exception:
        return None
