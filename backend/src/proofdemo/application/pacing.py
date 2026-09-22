"""Deterministic, bounded viewing pauses for local product demos."""

from __future__ import annotations

from proofdemo.domain.demo_spec import (
    ClickAction,
    DemoSpec,
    FillAction,
    GotoAction,
    PauseAction,
)

WATCH_BUDGET_MS = 9_000
MAX_WATCH_POINTS = 4
MIN_REQUESTED_SECONDS = 15


def pace_studio_spec(spec: DemoSpec, requested_seconds: int | None) -> DemoSpec:
    """Make a short verified workflow watchable without padding its final frame."""
    if requested_seconds is None or requested_seconds < MIN_REQUESTED_SECONDS:
        return spec
    existing_pause_ms = sum(
        action.duration_ms
        for scene in spec.scenes
        for action in scene.actions
        if isinstance(action, PauseAction)
    )
    budget_ms = max(0, WATCH_BUDGET_MS - existing_pause_ms)
    if budget_ms == 0:
        return spec

    total_actions = sum(len(scene.actions) for scene in spec.scenes)
    free_slots = min(500 - total_actions, MAX_WATCH_POINTS)
    if free_slots <= 0:
        return spec
    eligible: list[tuple[int, int]] = []
    for scene_index, scene in enumerate(spec.scenes):
        if len(scene.actions) >= 100:
            continue
        for action_index, action in enumerate(scene.actions):
            if not isinstance(action, (GotoAction, FillAction, ClickAction)):
                continue
            following = scene.actions[action_index + 1 : action_index + 2]
            if following and isinstance(following[0], PauseAction):
                continue
            eligible.append((scene_index, action_index))
    if not eligible:
        return spec

    # Spread the available moments over the workflow, including its last action.
    point_count = min(len(eligible), free_slots)
    if point_count == 1:
        chosen = [eligible[-1]]
    else:
        chosen = [
            eligible[round(index * (len(eligible) - 1) / (point_count - 1))]
            for index in range(point_count)
        ]
    selected: list[tuple[int, int]] = []
    scene_counts: dict[int, int] = {}
    for scene_index, action_index in chosen:
        count = scene_counts.get(scene_index, 0)
        if len(spec.scenes[scene_index].actions) + count >= 100:
            continue
        selected.append((scene_index, action_index))
        scene_counts[scene_index] = count + 1
    if not selected:
        return spec

    per_point, remainder = divmod(budget_ms, len(selected))
    pauses = {point: per_point + (index < remainder) for index, point in enumerate(selected)}
    rebuilt = spec.model_dump(mode="json")
    for scene_index, scene in enumerate(spec.scenes):
        taken = {action.id for action in scene.actions}
        next_id = 1
        actions: list[dict[str, object]] = []
        for action_index, action in enumerate(scene.actions):
            actions.append(action.model_dump(mode="json"))
            duration_ms = pauses.get((scene_index, action_index))
            if duration_ms is None:
                continue
            while f"watch-{next_id:02d}" in taken:
                next_id += 1
            pause_id = f"watch-{next_id:02d}"
            taken.add(pause_id)
            next_id += 1
            actions.append(
                PauseAction(id=pause_id, type="pause", duration_ms=duration_ms).model_dump()
            )
        rebuilt["scenes"][scene_index]["actions"] = actions
    return DemoSpec.model_validate(rebuilt)
