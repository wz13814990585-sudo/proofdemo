"""Bounded repair proposal validation and explicit target-only application."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from proofdemo.application.artifacts import (
    ArtifactDeclaration,
    ArtifactKind,
    ArtifactManifest,
    ArtifactWriter,
)
from proofdemo.application.change_detection import ChangeStatus, UIChangeReport
from proofdemo.domain.demo_spec import (
    ClickAction,
    DemoSpec,
    ElementVisibleAssertion,
    FillAction,
    Scene,
    TextContainsAssertion,
)
from proofdemo.domain.recipe import DemoRecipe
from proofdemo.domain.repair import (
    RepairFindingContext,
    RepairRequest,
    SceneRepairProposal,
)
from proofdemo.ports.repair import RepairPort


@dataclass(frozen=True)
class RepairProposalResult:
    proposal: SceneRepairProposal
    provider: str
    model: str


class InvalidRepairProposal(ValueError):
    """A repair candidate exceeds the diagnosed target-only boundary."""


class RepairArtifactError(RuntimeError):
    """Repair inputs or outputs fail artifact integrity requirements."""


class RepairService:
    APPROVED_PATH = "repair_proposal.json"

    @staticmethod
    def load_change_report(
        recipe: DemoRecipe,
        artifact_dir: Path,
    ) -> UIChangeReport:
        root = artifact_dir.resolve()
        manifest_path = (root / "artifact_manifest.json").resolve()
        if not manifest_path.is_file():
            raise RepairArtifactError("change artifact manifest is missing")
        try:
            manifest = ArtifactManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as error:
            raise RepairArtifactError("change artifact manifest is invalid") from error
        integrity_errors = ArtifactWriter.verify(root, manifest)
        if integrity_errors:
            raise RepairArtifactError(f"change artifact integrity failed: {integrity_errors[0]}")
        record = next(
            (
                item
                for item in manifest.artifacts
                if item.kind is ArtifactKind.UI_CHANGE_REPORT
                and item.path == "ui_change_report.json"
            ),
            None,
        )
        if record is None:
            raise RepairArtifactError("integrity manifest has no UI change report")
        report_path = (root / record.path).resolve()
        if not report_path.is_relative_to(root):
            raise RepairArtifactError("UI change report path escaped artifact directory")
        try:
            report = UIChangeReport.model_validate_json(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise RepairArtifactError("UI change report is invalid") from error
        if (
            report.recipe_id != str(recipe.id)
            or report.spec_id != recipe.spec.id
            or report.status is not ChangeStatus.CHANGED
        ):
            raise RepairArtifactError("UI change report does not diagnose this recipe")
        return report

    def propose(
        self,
        planner: RepairPort,
        recipe: DemoRecipe,
        change_report: UIChangeReport,
        scene_id: str,
        *,
        user_hint: str | None = None,
    ) -> RepairProposalResult:
        scene = next((item for item in recipe.spec.scenes if item.id == scene_id), None)
        if scene is None:
            raise InvalidRepairProposal(f"Scene {scene_id} is absent from the recipe")
        findings = tuple(
            finding for finding in change_report.findings if finding.scene_id == scene_id
        )
        if not findings:
            raise InvalidRepairProposal(f"Scene {scene_id} has no diagnosed changes")
        request = RepairRequest(
            recipe_id=recipe.id,
            spec_sha256=recipe.spec_sha256,
            scene=scene,
            findings=tuple(
                RepairFindingContext(
                    category=finding.category.value,
                    action_id=finding.action_id,
                    assertion_id=finding.assertion_id,
                    description=finding.description,
                )
                for finding in findings
            ),
            user_hint=user_hint,
        )
        candidate = planner.propose(request)
        self.validate(recipe, change_report, candidate.proposal)
        return RepairProposalResult(
            proposal=candidate.proposal,
            provider=candidate.provider,
            model=candidate.model,
        )

    @staticmethod
    def validate(
        recipe: DemoRecipe,
        change_report: UIChangeReport,
        proposal: SceneRepairProposal,
    ) -> Scene:
        if (
            str(proposal.source_recipe_id) != str(recipe.id)
            or proposal.source_spec_sha256 != recipe.spec_sha256
        ):
            raise InvalidRepairProposal("repair proposal source does not match the recipe")
        scene = next(
            (item for item in recipe.spec.scenes if item.id == proposal.scene_id),
            None,
        )
        if scene is None:
            raise InvalidRepairProposal("repair proposal references an unknown Scene")
        findings = tuple(
            item for item in change_report.findings if item.scene_id == proposal.scene_id
        )
        if not findings:
            raise InvalidRepairProposal("repair Scene has no diagnosed changes")
        actual_categories = {item.category.value for item in findings}
        if not set(proposal.diagnostic_categories).issubset(actual_categories):
            raise InvalidRepairProposal(
                "repair cites diagnostic categories not present in evidence"
            )
        diagnosed = {
            ("action", item.action_id)
            if item.action_id is not None
            else ("assertion", item.assertion_id)
            for item in findings
        }
        seen: set[tuple[str, str]] = set()
        actions = {action.id: action for action in scene.actions}
        assertions = {assertion.id: assertion for assertion in scene.assertions}
        for replacement in proposal.replacements:
            key = (replacement.entity, replacement.entity_id)
            if key in seen:
                raise InvalidRepairProposal("repair contains a duplicate target replacement")
            seen.add(key)
            if key not in diagnosed:
                raise InvalidRepairProposal("repair targets an entity without a diagnosed change")
            if replacement.entity == "action":
                action = actions.get(replacement.entity_id)
                if not isinstance(action, ClickAction | FillAction):
                    raise InvalidRepairProposal("only click/fill action targets can be repaired")
                if replacement.target == action.target:
                    raise InvalidRepairProposal("repair action target is unchanged")
            else:
                assertion = assertions.get(replacement.entity_id)
                if not isinstance(assertion, ElementVisibleAssertion | TextContainsAssertion):
                    raise InvalidRepairProposal(
                        "only element/text assertion targets can be repaired"
                    )
                if replacement.target == assertion.target:
                    raise InvalidRepairProposal("repair assertion target is unchanged")
        return scene

    def apply(
        self,
        recipe: DemoRecipe,
        change_report: UIChangeReport,
        proposal: SceneRepairProposal,
    ) -> DemoSpec:
        original_scene = self.validate(recipe, change_report, proposal)
        replacements = {
            (item.entity, item.entity_id): item.target for item in proposal.replacements
        }
        actions = tuple(
            action.model_copy(update={"target": replacements[("action", action.id)]})
            if ("action", action.id) in replacements
            else action
            for action in original_scene.actions
        )
        assertions = tuple(
            assertion.model_copy(update={"target": replacements[("assertion", assertion.id)]})
            if ("assertion", assertion.id) in replacements
            else assertion
            for assertion in original_scene.assertions
        )
        repaired_scene = original_scene.model_copy(
            update={"actions": actions, "assertions": assertions}
        )
        scenes = tuple(
            repaired_scene if scene.id == proposal.scene_id else scene
            for scene in recipe.spec.scenes
        )
        return DemoSpec.model_validate(
            recipe.spec.model_copy(update={"scenes": scenes}).model_dump(mode="json")
        )

    @staticmethod
    def write_candidate(proposal: SceneRepairProposal, output: Path) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        RepairService._atomic_text(output, proposal.model_dump_json(indent=2) + "\n")

    @staticmethod
    def write_approved(
        proposal: SceneRepairProposal,
        artifact_dir: Path,
    ) -> ArtifactDeclaration:
        path = (artifact_dir.resolve() / RepairService.APPROVED_PATH).resolve()
        if not path.is_relative_to(artifact_dir.resolve()):
            raise RepairArtifactError("repair proposal path escaped artifact directory")
        RepairService._atomic_text(path, proposal.model_dump_json(indent=2) + "\n")
        return ArtifactDeclaration(
            path=RepairService.APPROVED_PATH,
            kind=ArtifactKind.REPAIR_PROPOSAL,
            scene_id=proposal.scene_id,
        )

    @staticmethod
    def _atomic_text(path: Path, content: str) -> None:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)
