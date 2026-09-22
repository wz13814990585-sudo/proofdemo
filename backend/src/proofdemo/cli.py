"""Command-line interface for deterministic ProofDemo workflows."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from proofdemo.adapters.playwright_browser import PlaywrightBrowser
from proofdemo.application.artifacts import ArtifactWriteError, ArtifactWriter
from proofdemo.application.execution import ExecutionService
from proofdemo.domain.demo_run import DemoRunStatus
from proofdemo.domain.demo_spec import DemoSpec

EXIT_EXECUTED = 0
EXIT_FAILED = 1
EXIT_BLOCKED = 2
EXIT_INVALID_INPUT = 64


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="proofdemo")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="execute a validated DemoSpec")
    run.add_argument("spec", type=Path, help="path to a DemoSpec JSON file")
    run.add_argument("--artifacts", required=True, type=Path, help="artifact output directory")
    return parser


def _load_spec(path: Path) -> DemoSpec:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return DemoSpec.model_validate(raw)


def run(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command != "run":
        return EXIT_INVALID_INPUT

    try:
        spec = _load_spec(args.spec)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        print(f"Invalid DemoSpec: {error}", file=sys.stderr)
        return EXIT_INVALID_INPUT

    try:
        args.artifacts.mkdir(parents=True, exist_ok=True)
        bundle = ExecutionService(PlaywrightBrowser()).execute_bundle(spec, args.artifacts)
        ArtifactWriter().persist(bundle, args.artifacts)
        report = bundle.report
        report_path = args.artifacts / "execution_report.json"
    except (ArtifactWriteError, OSError) as error:
        print(f"Could not write artifacts: {error}", file=sys.stderr)
        return EXIT_BLOCKED

    print(f"{report.run.status}: {report_path}")
    if report.run.status in {DemoRunStatus.EXECUTED, DemoRunStatus.PASSED}:
        return EXIT_EXECUTED
    if report.run.status is DemoRunStatus.FAILED:
        return EXIT_FAILED
    return EXIT_BLOCKED


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
