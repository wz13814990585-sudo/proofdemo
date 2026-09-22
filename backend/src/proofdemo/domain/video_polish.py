"""Versioned, evidence-linked instructions for the presentation-only video layer."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PolishScene(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scene_id: str
    title: str = Field(min_length=1, max_length=200)
    source_start_ms: int = Field(ge=0)
    source_end_ms: int = Field(gt=0)
    display_start_ms: int = Field(ge=0)
    display_end_ms: int = Field(gt=0)
    hold_ms: Literal[800] = 800
    passed_assertions: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_range(self) -> PolishScene:
        if self.source_end_ms <= self.source_start_ms:
            raise ValueError("polish source scene end must follow start")
        if self.display_end_ms - self.display_start_ms != (
            self.source_end_ms - self.source_start_ms + self.hold_ms
        ):
            raise ValueError("polish display scene must include its verified hold")
        return self


class FocusCue(BaseModel):
    """A real action's viewport point and bounded visual-animation window."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scene_id: str
    action_id: str
    kind: Literal["click", "fill"]
    from_x: float = Field(ge=0, le=1, allow_inf_nan=False)
    from_y: float = Field(ge=0, le=1, allow_inf_nan=False)
    x: float = Field(ge=0, le=1, allow_inf_nan=False)
    y: float = Field(ge=0, le=1, allow_inf_nan=False)
    cursor_start_ms: int = Field(ge=0)
    source_action_ms: int = Field(ge=0)
    action_ms: int = Field(ge=0)
    zoom_start_ms: int = Field(ge=0)
    zoom_end_ms: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_windows(self) -> FocusCue:
        if not (self.cursor_start_ms <= self.action_ms <= self.zoom_start_ms < self.zoom_end_ms):
            raise ValueError("focus cue windows must be ordered")
        return self


class VideoPolishPlan(BaseModel):
    """Source hashes and edit decisions, never a new verification result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    source_video_path: Literal["demo.mp4"] = "demo.mp4"
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    timeline_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_duration_ms: int = Field(gt=0)
    output_duration_ms: int = Field(gt=0)
    output_width: Literal[1920] = 1920
    output_height: Literal[1080] = 1080
    output_fps: Literal[30] = 30
    transition_ms: Literal[160] = 160
    scenes: tuple[PolishScene, ...] = Field(min_length=1, max_length=12)
    focus_cues: tuple[FocusCue, ...] = Field(max_length=24)
    warnings: tuple[str, ...] = Field(max_length=20)

    @model_validator(mode="after")
    def validate_coverage(self) -> VideoPolishPlan:
        if (
            self.scenes[0].source_start_ms != 0
            or self.scenes[0].display_start_ms != 0
            or self.scenes[-1].source_end_ms != self.source_duration_ms
            or self.scenes[-1].display_end_ms != self.output_duration_ms
        ):
            raise ValueError("polish scenes must cover complete source and output videos")
        for left, right in zip(self.scenes, self.scenes[1:], strict=False):
            if (
                left.source_end_ms != right.source_start_ms
                or left.display_end_ms != right.display_start_ms
            ):
                raise ValueError("polish scenes must be contiguous")
        ranges = {scene.scene_id: scene for scene in self.scenes}
        for cue in self.focus_cues:
            scene = ranges.get(cue.scene_id)
            if scene is None or not (
                scene.source_start_ms <= cue.source_action_ms <= scene.source_end_ms
                and scene.display_start_ms <= cue.cursor_start_ms
                and cue.zoom_end_ms <= scene.display_end_ms
            ):
                raise ValueError("focus cue must stay inside its verified scene")
        return self


class CaptionCue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scene_id: str
    kind: Literal["scene_title", "verified_result"]
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_window(self) -> CaptionCue:
        if self.end_ms <= self.start_ms:
            raise ValueError("caption end must follow start")
        return self


class CaptionTrack(BaseModel):
    """Readable text/timing source for the baked-in overlays."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    cues: tuple[CaptionCue, ...] = Field(min_length=2, max_length=24)
