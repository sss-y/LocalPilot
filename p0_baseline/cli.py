from __future__ import annotations

import argparse
from collections.abc import Sequence


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
    parser.parse_args(argv)
    parser.error("P0 baseline execution is not available yet")
