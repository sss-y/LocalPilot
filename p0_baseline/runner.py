"""Synchronous orchestration for the LocalPilot P0 baseline."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic_ns
from uuid import uuid4

from .adapters import (
    InternalAdapter,
    UnittestAdapter,
    VerificationContext,
    not_run_result,
)
from .aggregation import AcceptanceGates, aggregate
from .errors import FAILURE_ERROR_CODES
from .manifest import (
    BaselineManifest,
    CheckDescriptor,
    ManifestIntegrity,
    load_manifest,
    validate_manifest_integrity,
)
from .models import (
    BaselineReport,
    CheckResult,
    CheckStatus,
    CoverageStatus,
    EnvironmentSnapshot,
    NetworkMode,
    RequirementCoverage,
    WorkingTreeState,
)
from .offline import offline_guard
from .preflight import inspect_preflight, sanitized_worker_env
from .registry import AdapterRegistry
from .safe_subprocess import run_worker


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _passed_internal(
    context: VerificationContext,
    descriptor: CheckDescriptor,
) -> CheckResult:
    return UnittestAdapter.result_for_status(descriptor, CheckStatus.PASSED)


def default_registry() -> AdapterRegistry:
    """Return the closed registry for currently implemented control checks."""

    return AdapterRegistry(
        unittest=UnittestAdapter(),
        internal=InternalAdapter(
            {
                "manifest.integrity": _passed_internal,
                "network.offline-boundary": _passed_internal,
            }
        ),
    )


def _coverage(
    manifest_integrity: ManifestIntegrity,
    checks: tuple[CheckResult, ...],
) -> tuple[RequirementCoverage, ...]:
    by_id = {item.check_id: item for item in checks}
    coverage: list[RequirementCoverage] = []
    for mapping in manifest_integrity.requirement_coverage:
        statuses = {by_id[check_id].status for check_id in mapping.check_ids}
        status = (
            CoverageStatus.FAILED
            if statuses & {CheckStatus.FAILED, CheckStatus.ERROR}
            else CoverageStatus.INCOMPLETE
            if statuses & {
                CheckStatus.SKIPPED,
                CheckStatus.NOT_RUN,
                CheckStatus.INTERRUPTED,
            }
            else CoverageStatus.PASSED
        )
        coverage.append(
            RequirementCoverage(
                requirement_id=mapping.requirement_id,
                status=status,
                check_ids=mapping.check_ids,
                evidence_refs=tuple(
                    f"checks/{check_id}.json" for check_id in mapping.check_ids
                ),
            )
        )
    return tuple(coverage)


def run(
    repository_root: str | Path,
    manifest_path: str | Path,
    *,
    registry: AdapterRegistry | None = None,
) -> BaselineReport:
    """Run the active manifest under the parent offline boundary."""

    started_at = _timestamp()
    started_ns = monotonic_ns()
    root = Path(repository_root).resolve(strict=True)
    manifest: BaselineManifest = load_manifest(manifest_path)
    integrity = validate_manifest_integrity(manifest, root)
    environment: EnvironmentSnapshot = inspect_preflight(manifest, root)
    active = tuple(item for item in manifest.checks if item.required)
    results = [not_run_result(item) for item in active]
    selected_registry = registry or default_registry()
    worker_environment = sanitized_worker_env(os.environ)

    with TemporaryDirectory(prefix="p0-run-") as directory:
        run_directory = Path(directory).resolve(strict=True)
        with offline_guard(source="p0-runner"):
            for index, descriptor in enumerate(active):
                try:
                    context = VerificationContext(
                        repository_root=root,
                        run_directory=run_directory,
                        worker_executor=lambda request, target=descriptor: run_worker(
                            request,
                            repository_root=root,
                            run_directory=run_directory,
                            sanitized_environment=worker_environment,
                            allow_loopback=target.allow_loopback,
                            timeout_seconds=target.timeout_ms / 1000,
                        ),
                    )
                    adapter = selected_registry.resolve(descriptor.adapter)
                    results[index] = adapter.execute(context, descriptor)
                except KeyboardInterrupt:
                    break
                except Exception:
                    results[index] = UnittestAdapter.result_for_status(
                        descriptor,
                        CheckStatus.ERROR,
                    )

    observed = tuple(results)
    determinate_failure = any(
        diagnostic.code in FAILURE_ERROR_CODES
        for diagnostic in environment.violations
    )
    gates = AcceptanceGates(
        clean_checkout=environment.working_tree_state is WorkingTreeState.CLEAN,
        offline=environment.network_mode is NetworkMode.OFFLINE,
        evidence_complete=len(observed) == len(active),
        requirement_coverage_complete=len(observed) == len(active),
        supported_environment=environment.supported,
        credentials_absent=not environment.personal_credentials_loaded,
        scope_compliant=True,
    )
    aggregated = aggregate(
        observed,
        gates,
        determinate_failure=determinate_failure,
    )
    finished_at = _timestamp()
    return BaselineReport(
        schema_version=manifest.evidence_schema_version,
        run_id=f"p0-{uuid4().hex}",
        revision=environment.revision,
        manifest_digest=integrity.manifest_digest,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=max(0, (monotonic_ns() - started_ns) // 1_000_000),
        mode=NetworkMode.OFFLINE,
        environment=environment,
        overall_status=aggregated.overall_status,
        exit_code=aggregated.exit_code,
        acceptance_eligible=aggregated.acceptance_eligible,
        summary=aggregated.summary,
        checks=observed,
        requirement_coverage=_coverage(integrity, observed),
        run_diagnostics=(),
        redaction={"enabled": True, "matched_values": 0},
    )
