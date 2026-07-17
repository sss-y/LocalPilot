"""Controlled Python worker subprocess boundary for P0 checks."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Mapping

from .check_worker import WorkerRequest, WorkerResult
from .preflight import sanitized_worker_env


_MAX_RESULT_BYTES = 1_000_000


class SafeSubprocessError(RuntimeError):
    """A controlled worker process could not be executed safely."""

    def __init__(self, reason: str = "P0_WORKER_PROCESS_ERROR") -> None:
        self.reason = reason
        super().__init__(reason)


class UnsupportedExecutableError(SafeSubprocessError):
    """The requested executable is not the current Python interpreter."""

    def __init__(self) -> None:
        super().__init__("P0_UNSUPPORTED_EXECUTABLE")


def _directory(path: Path, name: str) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or path.is_symlink():
        raise SafeSubprocessError(f"P0_INVALID_{name.upper()}")
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        raise SafeSubprocessError(f"P0_INVALID_{name.upper()}") from None
    if not resolved.is_dir():
        raise SafeSubprocessError(f"P0_INVALID_{name.upper()}")
    return resolved


def _current_executable(requested: str | os.PathLike[str] | None) -> str:
    candidate = sys.executable if requested is None else os.fspath(requested)
    if type(candidate) is not str or not candidate:
        raise UnsupportedExecutableError()
    try:
        current = Path(sys.executable).resolve(strict=True)
        resolved = Path(candidate).resolve(strict=True)
    except OSError:
        raise UnsupportedExecutableError() from None
    if resolved != current or not current.is_file():
        raise UnsupportedExecutableError()
    return sys.executable


def _worker_environment(
    environment: Mapping[str, str],
    *,
    allow_loopback: bool,
) -> dict[str, str]:
    if not isinstance(environment, Mapping):
        raise SafeSubprocessError("P0_UNSANITIZED_WORKER_ENV")
    copied = dict(environment)
    if copied != sanitized_worker_env(copied):
        raise SafeSubprocessError("P0_UNSANITIZED_WORKER_ENV")
    copied["P0_OFFLINE_ALLOW_LOOPBACK"] = "1" if allow_loopback else "0"
    copied["P0_OFFLINE_SOURCE"] = "check-worker"
    return copied


def run_worker(
    request: WorkerRequest,
    *,
    repository_root: Path,
    run_directory: Path,
    sanitized_environment: Mapping[str, str],
    allow_loopback: bool = False,
    executable: str | os.PathLike[str] | None = None,
    timeout_seconds: float = 30.0,
) -> WorkerResult:
    """Run one fixed Check Worker invocation and return its structured result."""

    if not isinstance(request, WorkerRequest):
        raise TypeError("request must be a WorkerRequest")
    if type(allow_loopback) is not bool:
        raise TypeError("allow_loopback must be a boolean")
    if type(timeout_seconds) not in {int, float} or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    python = _current_executable(executable)
    repository = _directory(repository_root, "repository_root")
    runtime = _directory(run_directory, "run_directory")
    environment = _worker_environment(
        sanitized_environment,
        allow_loopback=allow_loopback,
    )

    try:
        with TemporaryDirectory(prefix="check-worker-", dir=runtime) as directory:
            boundary = Path(directory).resolve(strict=True)
            boundary.relative_to(runtime)
            request_path = boundary / "request.json"
            result_path = boundary / "result.json"
            with request_path.open("x", encoding="utf-8") as stream:
                stream.write(request.to_json())
            command = [
                python,
                "-m",
                "p0_baseline.check_worker",
                "--request",
                str(request_path),
                "--result",
                str(result_path),
            ]
            completed = subprocess.run(
                command,
                cwd=repository,
                env=environment,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
                shell=False,
            )
            if completed.returncode != 0:
                raise SafeSubprocessError("P0_WORKER_EXIT_NONZERO")
            if result_path.is_symlink() or not result_path.is_file():
                raise SafeSubprocessError("P0_WORKER_RESULT_MISSING")
            if result_path.resolve(strict=True).parent != boundary:
                raise SafeSubprocessError("P0_WORKER_RESULT_INVALID")
            if result_path.stat().st_size > _MAX_RESULT_BYTES:
                raise SafeSubprocessError("P0_WORKER_RESULT_INVALID")
            try:
                return WorkerResult.from_json(result_path.read_bytes())
            except (OSError, ValueError, TypeError):
                raise SafeSubprocessError("P0_WORKER_RESULT_INVALID") from None
    except subprocess.TimeoutExpired:
        raise SafeSubprocessError("P0_WORKER_TIMEOUT") from None
    except SafeSubprocessError:
        raise
    except (subprocess.SubprocessError, OSError, ValueError, TypeError):
        raise SafeSubprocessError() from None
