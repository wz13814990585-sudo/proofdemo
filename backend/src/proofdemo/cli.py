"""Command-line interface for deterministic ProofDemo workflows."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from tempfile import NamedTemporaryFile

from pydantic import ValidationError

from proofdemo.adapters.deepseek import DeepSeekPlanner
from proofdemo.adapters.ffmpeg_audio import FFmpegAudioMixAdapter
from proofdemo.adapters.ffmpeg_partial import FFmpegPartialRenderAdapter
from proofdemo.adapters.ffmpeg_render import FFmpegRenderAdapter
from proofdemo.adapters.openai_planner import OpenAIPlanner
from proofdemo.adapters.openai_repair import OpenAIRepairAdapter
from proofdemo.adapters.openai_speech import OpenAISpeechAdapter
from proofdemo.adapters.playwright_browser import PlaywrightBrowser
from proofdemo.application.artifacts import ArtifactDeclaration, ArtifactWriteError, ArtifactWriter
from proofdemo.application.change_detection import (
    BaselineInvalidError,
    BaselineMissingError,
    ChangeDetectionContext,
    ChangeDetectionError,
    ChangeDetectionService,
)
from proofdemo.application.execution import ExecutionService
from proofdemo.application.narration import NarrationRefusedError, NarrationService
from proofdemo.application.partial_rendering import (
    PartialRenderRefusedError,
    PartialRenderService,
    RepairExecutionContext,
)
from proofdemo.application.planning import InvalidPlannerCandidate, PlanningService
from proofdemo.application.recipes import (
    CompatibilityStatus,
    RecipeRefusedError,
    RecipeService,
)
from proofdemo.application.rendering import CompositionRefusedError, CompositionService
from proofdemo.application.repair import (
    InvalidRepairProposal,
    RepairArtifactError,
    RepairService,
)
from proofdemo.application.safety import SafetyDecision, SafetyService
from proofdemo.config import Settings
from proofdemo.domain.demo_run import DemoRunStatus
from proofdemo.domain.demo_spec import DemoSpec
from proofdemo.domain.planning import DemoIntent
from proofdemo.domain.recipe import DemoRecipe
from proofdemo.domain.repair import SceneRepairProposal
from proofdemo.evaluation.benchmark import BenchmarkService, BenchmarkStatus
from proofdemo.ports.audio import AudioMixError, AudioUnavailableError
from proofdemo.ports.planner import PlannerResponseError, PlannerUnavailableError
from proofdemo.ports.render import RenderFailedError, RenderUnavailableError
from proofdemo.ports.repair import RepairResponseError, RepairUnavailableError
from proofdemo.ports.speech import SpeechSynthesisError, SpeechUnavailableError

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
    run.add_argument("--narrate", action="store_true", help="add evidence-grounded AI speech")
    run.add_argument("--tts-model", help="explicit OpenAI speech model; overrides environment")
    run.add_argument("--voice", help="explicit OpenAI speech voice; overrides environment")
    run.add_argument(
        "--allow-risky-actions",
        action="store_true",
        help="fresh approval for named destructive/financial/account actions",
    )
    replay = commands.add_parser("replay", help="compatibility-check and replay a DemoRecipe")
    replay.add_argument("recipe", type=Path, help="path to demo_recipe.json")
    replay.add_argument("--artifacts", required=True, type=Path, help="new artifact directory")
    replay.add_argument("--narrate", action="store_true", help="add evidence-grounded AI speech")
    replay.add_argument("--tts-model", help="explicit OpenAI speech model; overrides environment")
    replay.add_argument("--voice", help="explicit OpenAI speech voice; overrides environment")
    replay.add_argument("--allow-risky-actions", action="store_true")
    replay.add_argument(
        "--baseline-artifacts",
        type=Path,
        help="source artifact directory; defaults to the recipe directory",
    )
    plan = commands.add_parser("plan", help="create a reviewable DemoSpec candidate")
    plan.add_argument("source_url", help="same-origin application URL")
    plan.add_argument("--goal", required=True, help="natural-language demo goal")
    plan.add_argument("--output", required=True, type=Path, help="candidate JSON path")
    plan.add_argument("--audience")
    plan.add_argument("--language", default="en")
    plan.add_argument("--duration", type=int, dest="approximate_duration_seconds")
    plan.add_argument("--model", help="explicit OpenAI model; overrides environment")
    propose_repair = commands.add_parser(
        "propose-repair",
        help="create a review-required target repair candidate",
    )
    propose_repair.add_argument("recipe", type=Path)
    propose_repair.add_argument("--change-artifacts", required=True, type=Path)
    propose_repair.add_argument("--scene", required=True)
    propose_repair.add_argument("--output", required=True, type=Path)
    propose_repair.add_argument("--model", help="explicit OpenAI model; overrides environment")
    propose_repair.add_argument("--hint", help="reviewer locator guidance")
    apply_repair = commands.add_parser(
        "apply-repair",
        help="explicitly approve, verify, and partially render one repair",
    )
    apply_repair.add_argument("recipe", type=Path)
    apply_repair.add_argument("proposal", type=Path)
    apply_repair.add_argument("--change-artifacts", required=True, type=Path)
    apply_repair.add_argument("--baseline-artifacts", required=True, type=Path)
    apply_repair.add_argument("--artifacts", required=True, type=Path)
    apply_repair.add_argument("--allow-risky-actions", action="store_true")
    apply_repair.set_defaults(narrate=False, tts_model=None, voice=None)
    benchmark = commands.add_parser("benchmark", help="run offline V1 release benchmarks")
    benchmark.add_argument("--output", required=True, type=Path)
    return parser


def _load_spec(path: Path) -> DemoSpec:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return DemoSpec.model_validate(raw)


def _execute_spec(
    spec: DemoSpec,
    args: argparse.Namespace,
    *,
    base_artifacts: tuple[ArtifactDeclaration, ...] = (),
    change_context: ChangeDetectionContext | None = None,
    repair_context: RepairExecutionContext | None = None,
) -> int:
    if not args.narrate and (args.tts_model or args.voice):
        print("Invalid narration options: --tts-model/--voice require --narrate", file=sys.stderr)
        return EXIT_INVALID_INPUT
    settings = Settings.from_env()
    tts_model = args.tts_model or settings.openai_tts_model
    tts_voice = args.voice or settings.openai_tts_voice
    if args.narrate and (not tts_model or not tts_voice):
        print(
            "Narration blocked: set an explicit TTS model and voice",
            file=sys.stderr,
        )
        return EXIT_BLOCKED

    try:
        assessment = SafetyService.assess(
            spec,
            approval_acknowledged=args.allow_risky_actions,
        )
        safety_declaration = SafetyService.write(assessment, args.artifacts)
    except (OSError, ValueError) as error:
        print(f"Could not write safety assessment: {error}", file=sys.stderr)
        return EXIT_BLOCKED
    if assessment.decision is not SafetyDecision.ALLOWED:
        print(
            f"Safety {assessment.decision}: {args.artifacts / SafetyService.REPORT_PATH}",
            file=sys.stderr,
        )
        return EXIT_BLOCKED

    try:
        args.artifacts.mkdir(parents=True, exist_ok=True)
        bundle = ExecutionService(PlaywrightBrowser()).execute_bundle(spec, args.artifacts)
        writer = ArtifactWriter()
        declarations = [*base_artifacts, safety_declaration]
        if change_context is not None:
            change_report = ChangeDetectionService.compare(change_context, bundle.report)
            declarations.append(ChangeDetectionService.write(change_report, args.artifacts))
        manifest = writer.persist(
            bundle,
            args.artifacts,
            extra_artifacts=declarations,
        )
        report = bundle.report
        if report.run.status is DemoRunStatus.PASSED:
            composition = CompositionService(FFmpegRenderAdapter()).compose(
                bundle,
                manifest,
                args.artifacts,
            )
            declarations.extend(composition.declarations)
            manifest = writer.persist(
                bundle,
                args.artifacts,
                extra_artifacts=declarations,
            )
            if repair_context is not None:
                partial = PartialRenderService(FFmpegPartialRenderAdapter()).compose(
                    repair_context,
                    spec,
                    bundle,
                    manifest,
                    composition.timeline,
                    args.artifacts,
                )
                declarations.extend(partial.declarations)
                manifest = writer.persist(
                    bundle,
                    args.artifacts,
                    extra_artifacts=declarations,
                )
            if args.narrate:
                narration = NarrationService(
                    OpenAISpeechAdapter(tts_model or "", tts_voice or ""),
                    FFmpegAudioMixAdapter(),
                ).narrate(bundle, manifest, composition.timeline, args.artifacts)
                declarations.extend(narration.declarations)
                manifest = writer.persist(
                    bundle,
                    args.artifacts,
                    extra_artifacts=declarations,
                )
            recipe = RecipeService().create(spec, bundle, manifest, args.artifacts)
            declarations.append(recipe.declaration)
            writer.persist(bundle, args.artifacts, extra_artifacts=declarations)
        report_path = args.artifacts / "execution_report.json"
    except (ArtifactWriteError, OSError) as error:
        print(f"Could not write artifacts: {error}", file=sys.stderr)
        return EXIT_BLOCKED
    except RenderUnavailableError as error:
        print(f"Render blocked: {error}", file=sys.stderr)
        return EXIT_BLOCKED
    except (CompositionRefusedError, RenderFailedError) as error:
        print(f"Render failed: {error}", file=sys.stderr)
        return EXIT_BLOCKED
    except (SpeechUnavailableError, AudioUnavailableError) as error:
        print(f"Narration blocked: {error}", file=sys.stderr)
        return EXIT_BLOCKED
    except (SpeechSynthesisError, AudioMixError, NarrationRefusedError) as error:
        print(f"Narration failed: {error}", file=sys.stderr)
        return EXIT_BLOCKED
    except RecipeRefusedError as error:
        print(f"Recipe failed: {error}", file=sys.stderr)
        return EXIT_BLOCKED
    except PartialRenderRefusedError as error:
        print(f"Partial render failed: {error}", file=sys.stderr)
        return EXIT_BLOCKED
    except ChangeDetectionError as error:
        print(f"Change detection failed: {error}", file=sys.stderr)
        return EXIT_BLOCKED

    print(f"{report.run.status}: {report_path}")
    if report.run.status in {DemoRunStatus.EXECUTED, DemoRunStatus.PASSED}:
        return EXIT_EXECUTED
    if report.run.status is DemoRunStatus.FAILED:
        return EXIT_FAILED
    return EXIT_BLOCKED


def _run_spec(args: argparse.Namespace) -> int:
    try:
        spec = _load_spec(args.spec)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        print(f"Invalid DemoSpec: {error}", file=sys.stderr)
        return EXIT_INVALID_INPUT
    return _execute_spec(spec, args)


def _replay_recipe(args: argparse.Namespace) -> int:
    try:
        if (args.artifacts.resolve() / RecipeService.RECIPE_PATH) == args.recipe.resolve():
            print("Replay output must not overwrite its source recipe", file=sys.stderr)
            return EXIT_INVALID_INPUT
        recipe = DemoRecipe.model_validate_json(args.recipe.read_text(encoding="utf-8"))
        service = RecipeService()
        preflight = service.compatibility(recipe)
        args.artifacts.mkdir(parents=True, exist_ok=True)
        declaration = service.write_preflight(preflight, args.artifacts)
    except (OSError, ValidationError) as error:
        print(f"Invalid DemoRecipe: {error}", file=sys.stderr)
        return EXIT_INVALID_INPUT
    if preflight.status is CompatibilityStatus.INCOMPATIBLE:
        print(
            f"INCOMPATIBLE: {args.artifacts / RecipeService.PREFLIGHT_PATH}",
            file=sys.stderr,
        )
        return EXIT_INVALID_INPUT
    baseline_dir = args.baseline_artifacts or args.recipe.parent
    try:
        baseline = ChangeDetectionService.load_baseline(recipe, baseline_dir)
        change_context = ChangeDetectionService.context(recipe, baseline)
    except BaselineMissingError as error:
        if args.baseline_artifacts is not None:
            print(f"Invalid replay baseline: {error}", file=sys.stderr)
            return EXIT_INVALID_INPUT
        change_context = ChangeDetectionService.context(
            recipe,
            None,
            unavailable_reason="source execution report is not available beside the recipe",
        )
    except BaselineInvalidError as error:
        print(f"Invalid replay baseline: {error}", file=sys.stderr)
        return EXIT_INVALID_INPUT
    return _execute_spec(
        recipe.spec,
        args,
        base_artifacts=(declaration,),
        change_context=change_context,
    )


def _write_candidate(spec: DemoSpec, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=output.parent,
        prefix=f".{output.name}.",
        delete=False,
    ) as temporary:
        temporary.write(spec.model_dump_json(indent=2) + "\n")
        temporary.flush()
        temporary_path = Path(temporary.name)
    temporary_path.replace(output)


def _load_recipe(path: Path) -> DemoRecipe:
    return DemoRecipe.model_validate_json(path.read_text(encoding="utf-8"))


def _propose_repair(args: argparse.Namespace) -> int:
    try:
        recipe = _load_recipe(args.recipe)
        preflight = RecipeService.compatibility(recipe)
        if preflight.status is CompatibilityStatus.INCOMPATIBLE:
            print("Repair blocked: DemoRecipe is incompatible", file=sys.stderr)
            return EXIT_INVALID_INPUT
        change_report = RepairService.load_change_report(recipe, args.change_artifacts)
    except (OSError, ValidationError, RepairArtifactError) as error:
        print(f"Invalid repair input: {error}", file=sys.stderr)
        return EXIT_INVALID_INPUT
    model = args.model or Settings.from_env().openai_model
    if not model:
        print("Repair blocked: set --model or PROOFDEMO_OPENAI_MODEL", file=sys.stderr)
        return EXIT_BLOCKED
    try:
        result = RepairService().propose(
            OpenAIRepairAdapter(model),
            recipe,
            change_report,
            args.scene,
            user_hint=args.hint,
        )
        RepairService.write_candidate(result.proposal, args.output)
    except RepairUnavailableError as error:
        print(f"Repair blocked: {error}", file=sys.stderr)
        return EXIT_BLOCKED
    except (RepairResponseError, InvalidRepairProposal) as error:
        print(f"Repair failed: {error}", file=sys.stderr)
        return EXIT_FAILED
    except OSError as error:
        print(f"Could not write repair candidate: {error}", file=sys.stderr)
        return EXIT_BLOCKED
    print(f"REPAIR PROPOSED (review required): {args.output} [{result.provider}/{result.model}]")
    return EXIT_EXECUTED


def _apply_repair(args: argparse.Namespace) -> int:
    try:
        if args.artifacts.resolve() == args.baseline_artifacts.resolve():
            print("Repair output must differ from baseline artifacts", file=sys.stderr)
            return EXIT_INVALID_INPUT
        recipe = _load_recipe(args.recipe)
        preflight = RecipeService.compatibility(recipe)
        if preflight.status is CompatibilityStatus.INCOMPATIBLE:
            print("Repair blocked: DemoRecipe is incompatible", file=sys.stderr)
            return EXIT_INVALID_INPUT
        ChangeDetectionService.load_baseline(recipe, args.baseline_artifacts)
        change_report = RepairService.load_change_report(recipe, args.change_artifacts)
        proposal = SceneRepairProposal.model_validate_json(
            args.proposal.read_text(encoding="utf-8")
        )
        repaired_spec = RepairService().apply(recipe, change_report, proposal)
        args.artifacts.mkdir(parents=True, exist_ok=True)
        declaration = RepairService.write_approved(proposal, args.artifacts)
    except (
        OSError,
        ValidationError,
        BaselineMissingError,
        BaselineInvalidError,
        RepairArtifactError,
        InvalidRepairProposal,
    ) as error:
        print(f"Invalid repair input: {error}", file=sys.stderr)
        return EXIT_INVALID_INPUT
    context = RepairExecutionContext(
        baseline_dir=args.baseline_artifacts,
        baseline_spec=recipe.spec,
        proposal=proposal,
    )
    return _execute_spec(
        repaired_spec,
        args,
        base_artifacts=(declaration,),
        repair_context=context,
    )


def _run_benchmark(args: argparse.Namespace) -> int:
    report = BenchmarkService().run()
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=args.output.parent,
            prefix=f".{args.output.name}.",
            delete=False,
        ) as temporary:
            temporary.write(report.model_dump_json(indent=2) + "\n")
            temporary.flush()
            temporary_path = Path(temporary.name)
        temporary_path.replace(args.output)
    except OSError as error:
        print(f"Could not write benchmark report: {error}", file=sys.stderr)
        return EXIT_BLOCKED
    print(f"BENCHMARK {report.status}: {args.output}")
    return EXIT_EXECUTED if report.status is BenchmarkStatus.PASSED else EXIT_FAILED


def _plan_spec(args: argparse.Namespace) -> int:
    try:
        intent = DemoIntent(
            source_url=args.source_url,
            goal=args.goal,
            audience=args.audience,
            language=args.language,
            approximate_duration_seconds=args.approximate_duration_seconds,
        )
    except ValidationError as error:
        print(f"Invalid demo intent: {error}", file=sys.stderr)
        return EXIT_INVALID_INPUT

    settings = Settings.from_env()
    model = args.model or (
        settings.deepseek_model
        if settings.planner_provider == "deepseek"
        else settings.openai_model
    )
    if not model:
        print(
            "Planner blocked: set --model or "
            + (
                "PROOFDEMO_DEEPSEEK_MODEL"
                if settings.planner_provider == "deepseek"
                else "PROOFDEMO_OPENAI_MODEL"
            ),
            file=sys.stderr,
        )
        return EXIT_BLOCKED
    try:
        planner = (
            DeepSeekPlanner(model)
            if settings.planner_provider == "deepseek"
            else OpenAIPlanner(model)
        )
        result = PlanningService(planner).plan(intent)
        _write_candidate(result.spec, args.output)
    except PlannerUnavailableError as error:
        print(f"Planner blocked: {error}", file=sys.stderr)
        return EXIT_BLOCKED
    except (PlannerResponseError, InvalidPlannerCandidate) as error:
        print(f"Planner failed: {error}", file=sys.stderr)
        return EXIT_FAILED
    except OSError as error:
        print(f"Could not write candidate: {error}", file=sys.stderr)
        return EXIT_BLOCKED

    print(f"PLANNED (review required): {args.output} [{result.provider}/{result.model}]")
    return EXIT_EXECUTED


def run(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "run":
        return _run_spec(args)
    if args.command == "plan":
        return _plan_spec(args)
    if args.command == "replay":
        return _replay_recipe(args)
    if args.command == "propose-repair":
        return _propose_repair(args)
    if args.command == "apply-repair":
        return _apply_repair(args)
    if args.command == "benchmark":
        return _run_benchmark(args)
    return EXIT_INVALID_INPUT


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
