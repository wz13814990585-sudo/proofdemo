"""Deterministic provenance gate between page observations and proposed actions."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from proofdemo.domain.demo_spec import (
    ClickAction,
    DemoSpec,
    FillAction,
    GotoAction,
)
from proofdemo.domain.exploration import ExplorationReport, PageObservation


class GroundingCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scene_id: str
    action_id: str
    status: Literal["GROUNDED", "UNSUPPORTED", "BLOCKED"]
    page_index: int | None = None
    control_id: str | None = None
    reason: str | None = None


class GroundingReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    status: Literal["GROUNDED", "BLOCKED"]
    checks: tuple[GroundingCheck, ...] = Field(max_length=500)


class GroundingService:
    """Require observed visited pages and exact observed interactive targets."""

    @staticmethod
    def assess(spec: DemoSpec, exploration: ExplorationReport) -> GroundingReport:
        pages = {str(page.url): (index + 1, page) for index, page in enumerate(exploration.pages)}
        current: tuple[int, PageObservation] | None = None
        checks: list[GroundingCheck] = []
        for scene in spec.scenes:
            for action in scene.actions:
                status: Literal["GROUNDED", "UNSUPPORTED", "BLOCKED"] = "UNSUPPORTED"
                reason: str | None = None
                control_id: str | None = None
                if isinstance(action, GotoAction):
                    current = pages.get(str(action.url))
                    if current is None:
                        status, reason = "BLOCKED", "navigation page was not visited"
                    else:
                        status = "GROUNDED"
                elif isinstance(action, (ClickAction, FillAction)):
                    if current is None:
                        status, reason = "BLOCKED", "current page was not observed"
                    else:
                        _, page = current
                        matched = next(
                            (
                                control
                                for control in page.controls
                                if control.target == action.target
                                and (
                                    control.kind == "input"
                                    if isinstance(action, FillAction)
                                    else control.kind in {"link", "button", "element"}
                                )
                            ),
                            None,
                        )
                        if matched is None:
                            status, reason = "BLOCKED", "action target was not observed"
                        else:
                            status, control_id = "GROUNDED", matched.id
                            if isinstance(action, ClickAction) and matched.href is not None:
                                current = pages.get(str(matched.href))
                                if current is None:
                                    status, reason = (
                                        "BLOCKED",
                                        "clicked link destination was not visited",
                                    )
                checks.append(
                    GroundingCheck(
                        scene_id=scene.id,
                        action_id=action.id,
                        status=status,
                        page_index=current[0] if current is not None else None,
                        control_id=control_id,
                        reason=reason,
                    )
                )
        return GroundingReport(
            status="BLOCKED" if any(item.status == "BLOCKED" for item in checks) else "GROUNDED",
            checks=tuple(checks),
        )
