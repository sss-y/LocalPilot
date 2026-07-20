from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import replace
import json
from pathlib import Path

from .errors import ErrorCode
from .manifest import validate_json_schema
from .models import BaselineReport, BaselineStatus, Diagnostic
from .redaction import redact
from .runner import run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m p0_baseline",
        description="Run the LocalPilot P0 verifiable engineering baseline.",
    )
    parser.add_argument("--format", choices=("human", "json"), default="human")
    parser.add_argument("--output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    root = Path.cwd().resolve(strict=True)
    report = run(root, root / "p0_baseline" / "manifest.json")
    output_path = Path(arguments.output) if arguments.output else None
    if output_path is not None:
        try:
            payload = _safe_payload(report)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(_json(payload) + "\n", encoding="utf-8")
        except (OSError, TypeError, ValueError):
            report = _with_output_failure(report)

    payload = _safe_payload(report)
    if arguments.format == "json":
        print(_json(payload))
    else:
        _print_human(payload)
    return report.exit_code


def _safe_payload(report: BaselineReport) -> object:
    source = report.to_dict()
    validate_json_schema(
        source,
        Path(__file__).with_name("schemas") / "report.schema.json",
    )
    return redact(source).value


def _json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _with_output_failure(report: BaselineReport) -> BaselineReport:
    diagnostic = Diagnostic(
        code=ErrorCode.EVIDENCE_INCOMPLETE,
        message="Requested P0 JSON output could not be written safely.",
        failure_type="output",
        target="output",
        recoverable=False,
    )
    status = (
        BaselineStatus.FAILURE
        if report.overall_status is BaselineStatus.FAILURE
        else BaselineStatus.INCOMPLETE
    )
    return replace(
        report,
        overall_status=status,
        exit_code=1 if status is BaselineStatus.FAILURE else 2,
        acceptance_eligible=False,
        run_diagnostics=report.run_diagnostics + (diagnostic,),
    )


def _print_human(payload: object) -> None:
    if not isinstance(payload, dict):
        raise ValueError("redacted report payload must be an object")
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        raise ValueError("redacted report summary must be an object")
    print(f"status: {payload['overall_status']}")
    print(f"exit_code: {payload['exit_code']}")
    print(
        "checks: "
        f"passed={summary['passed']} failed={summary['failed']} "
        f"error={summary['error']} incomplete="
        f"{summary['skipped'] + summary['not_run'] + summary['interrupted']}"
    )
    print(str(payload["overall_status"]).upper())
