"""Run the deterministic release benchmark from a source checkout."""

from __future__ import annotations

import argparse
from pathlib import Path

from proofdemo.cli import run


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/benchmark_report.json"))
    args = parser.parse_args()
    raise SystemExit(run(["benchmark", "--output", str(args.output)]))


if __name__ == "__main__":
    main()
