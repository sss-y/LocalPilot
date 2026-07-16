"""Read-only repository, runtime, and code-origin preflight inspection."""

from __future__ import annotations

import importlib.machinery
import platform
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .errors import ErrorCode
from .manifest import BaselineManifest
from .models import (
    Diagnostic,
    EnvironmentSnapshot,
    NetworkMode,
    WorkingTreeState,
)


_REVISION = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
DEFAULT_MODULE_NAMES = (
    "config.paths",
    "core",
    "core.client",
    "core.context",
    "core.session",
    "tools.base",
)


class PreflightError(RuntimeError):
    code = ErrorCode.CHECK_ERROR

    def __init__(self, target: str = "repository") -> None:
        self.target = target
        super().__init__("P0 preflight inspection failed.")

    def to_diagnostic(self) -> Diagnostic:
        return Diagnostic(
            code=self.code,
            message="Repository preflight inspection could not be completed.",
            failure_type="preflight",
            target=self.target,
            recoverable=False,
        )


@dataclass(frozen=True)
class RuntimeProbe:
    runtime_name: str
    runtime_version: str
    os: str
    architecture: str

    def __post_init__(self) -> None:
        if any(type(value) is not str or not value.strip() for value in (
            self.runtime_name, self.runtime_version, self.os, self.architecture,
        )):
            raise ValueError("runtime probe values must be nonempty text")

    @classmethod
    def current(cls) -> RuntimeProbe:
        return cls(
            platform.python_implementation(),
            platform.python_version(),
            platform.system(),
            platform.machine(),
        )


def _git_result(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise PreflightError() from None


def _git(root: Path, *args: str) -> str:
    completed = _git_result(root, *args)
    if completed.returncode != 0:
        raise PreflightError()
    return completed.stdout


def _repository_root(repository_root: str | Path) -> Path:
    try:
        root = Path(repository_root).resolve(strict=True)
    except OSError:
        raise PreflightError() from None
    if not root.is_dir():
        raise PreflightError()
    discovered = _git(root, "rev-parse", "--show-toplevel").strip()
    try:
        if Path(discovered).resolve(strict=True) != root:
            raise PreflightError()
    except OSError:
        raise PreflightError() from None
    return root


def _runtime_supported(manifest: BaselineManifest, probe: RuntimeProbe) -> bool:
    expected = manifest.supported_environments[0]
    version = probe.runtime_version.split(".")
    expected_version = expected.runtime_version.removesuffix(".x").split(".")
    return (
        probe.runtime_name == expected.runtime_name
        and probe.os == expected.os
        and probe.architecture == expected.architecture
        and version[:2] == expected_version
    )


def _find_spec_without_import(module_name: str, root: Path):
    parts = module_name.split(".")
    search_path: list[str] = [str(root)]
    spec = None
    for index in range(len(parts)):
        qualified = ".".join(parts[: index + 1])
        spec = importlib.machinery.PathFinder.find_spec(qualified, search_path)
        if spec is None:
            return None
        if index < len(parts) - 1:
            locations = spec.submodule_search_locations
            if locations is None:
                return None
            search_path = list(locations)
    return spec


def _code_origins(
    root: Path,
    module_names: Iterable[str],
) -> tuple[dict[str, str], tuple[Diagnostic, ...]]:
    names = tuple(module_names)
    if not names or len(set(names)) != len(names) or any(
        type(name) is not str or not name.strip() for name in names
    ):
        raise PreflightError("code-origins")
    origins: dict[str, str] = {}
    violations: list[Diagnostic] = []
    for name in sorted(names):
        spec = _find_spec_without_import(name, root)
        try:
            if spec is None or spec.origin in {None, "built-in", "frozen"}:
                raise ValueError
            origin = Path(spec.origin).resolve(strict=True)
            relative = origin.relative_to(root)
            if not origin.is_file():
                raise ValueError
            tracked = _git_result(root, "cat-file", "-t", f"HEAD:{relative.as_posix()}")
            if tracked.returncode != 0 or tracked.stdout.strip() != "blob":
                raise ValueError
            origins[name] = relative.as_posix()
        except (OSError, ValueError):
            violations.append(Diagnostic(
                code=ErrorCode.CODE_ORIGIN_MISMATCH,
                message="Core module source is not contained in the current checkout.",
                failure_type="code_origin",
                target=name,
                recoverable=False,
            ))
    return origins, tuple(violations)


def inspect_preflight(
    manifest: BaselineManifest,
    repository_root: str | Path,
    dependency_fingerprint: str,
    *,
    runtime_probe: RuntimeProbe | None = None,
    module_names: Iterable[str] = DEFAULT_MODULE_NAMES,
) -> EnvironmentSnapshot:
    root = _repository_root(repository_root)
    revision = _git(root, "rev-parse", "--verify", "HEAD^{commit}").strip()
    if _REVISION.fullmatch(revision) is None:
        raise PreflightError("revision")
    dirty = bool(_git(root, "status", "--porcelain=v1", "--untracked-files=all"))
    probe = runtime_probe or RuntimeProbe.current()
    supported = _runtime_supported(manifest, probe)
    origins, origin_violations = _code_origins(root, module_names)
    violations = list(origin_violations)
    if not supported:
        violations.insert(0, Diagnostic(
            code=ErrorCode.ENV_UNSUPPORTED,
            message="Runtime does not match the approved P0 environment.",
            failure_type="environment",
            target=manifest.supported_environment_id,
            recoverable=False,
        ))
    return EnvironmentSnapshot(
        revision=revision,
        repository_root="<repository-root>",
        working_tree_state=WorkingTreeState.DIRTY if dirty else WorkingTreeState.CLEAN,
        runtime_name=probe.runtime_name,
        runtime_version=probe.runtime_version,
        os=probe.os,
        architecture=probe.architecture,
        dependency_fingerprint=dependency_fingerprint,
        code_origins=origins,
        network_mode=NetworkMode.OFFLINE,
        personal_credentials_loaded=False,
        supported=supported,
        violations=tuple(violations),
    )
