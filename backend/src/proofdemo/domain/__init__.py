"""Stable domain contracts for ProofDemo."""

from proofdemo.domain.demo_run import (
    DemoRun,
    DemoRunStatus,
    InvalidRunTransition,
    create_demo_run,
    transition_demo_run,
)
from proofdemo.domain.demo_spec import DemoSpec

__all__ = [
    "DemoRun",
    "DemoRunStatus",
    "DemoSpec",
    "InvalidRunTransition",
    "create_demo_run",
    "transition_demo_run",
]
