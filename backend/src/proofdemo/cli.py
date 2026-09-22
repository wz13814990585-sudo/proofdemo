"""Command-line interface for deterministic ProofDemo workflows."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from tempfile import NamedTemporaryFile

from pydantic import ValidationError

from proofdemo.adapters.ffmpeg_audio import FFmpegAudioMixAdapter
from proofdemo.adapters.ffmpeg_render import FFmpegRenderAdapter
from proofdemo.adapters.openai_planner import OpenAIPlanner
from proofdemo.adapters.openai_speech import OpenAISpeechAdapter
from proofdemo.adapters.playwright_browser import PlaywrightBrowser
from proofdemo.application.artifacts import ArtifactWriteError, ArtifactWriter
from proofdemo.application.execution import ExecutionService
from proofdemo.application.narration import NarrationRefusedError, NarrationService
from proofdemo.application.planning import InvalidPlannerCandidate, PlanningService
from proofdemo.application.rendering import CompositionRefusedError, CompositionService
from proofdemo.config import Settings
from proofdemo.domain.demo_run import DemoRunStatus
from proofdemo.domain.demo_spec import DemoSpec
from proofdemo.domain.planning import DemoIntent
from proofdemo.ports.audio import AudioMixError, AudioUnavailableError
from proofdemo.ports.planner import PlannerResponseError, PlannerUnavailableError
from proofdemo.ports.render import RenderFailedError, RenderUnavailableError
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
    plan = commands.add_parser("plan", help="create a reviewable DemoSpec candidate")
    plan.add_argument("source_url", help="same-origin application URL")
    plan.add_argument("--goal", required=True, help="natural-language demo goal")
    plan.add_argument("--output", required=True, type=Path, help="candidate JSON path")
    plan.add_argument("--audience")
    plan.add_argument("--language", default="en")
    plan.add_argument("--duration", type=int, dest="approximate_duration_seconds")
    plan.add_argument("--model", help="explicit OpenAI model; overrides environment")
    return parser


def _load_spec(path: Path) -> DemoSpec:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return DemoSpec.model_validate(raw)


def _run_spec(args: argparse.Namespace) -> int:
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
        spec = _load_spec(args.spec)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        print(f"Invalid DemoSpec: {error}", file=sys.stderr)
        return EXIT_INVALID_INPUT

    try:
        args.artifacts.mkdir(parents=True, exist_ok=True)
        bundle = ExecutionService(PlaywrightBrowser()).execute_bundle(spec, args.artifacts)
        writer = ArtifactWriter()
        manifest = writer.persist(bundle, args.artifacts)
        report = bundle.report
        if report.run.status is DemoRunStatus.PASSED:
            composition = CompositionService(FFmpegRenderAdapter()).compose(
                bundle,
                manifest,
                args.artifacts,
            )
            manifest = writer.persist(
                bundle,
                args.artifacts,
                extra_artifacts=composition.declarations,
            )
            if args.narrate:
                narration = NarrationService(
                    OpenAISpeechAdapter(tts_model or "", tts_voice or ""),
                    FFmpegAudioMixAdapter(),
                ).narrate(bundle, manifest, composition.timeline, args.artifacts)
                writer.persist(
                    bundle,
                    args.artifacts,
                    extra_artifacts=composition.declarations + narration.declarations,
                )
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

    print(f"{report.run.status}: {report_path}")
    if report.run.status in {DemoRunStatus.EXECUTED, DemoRunStatus.PASSED}:
        return EXIT_EXECUTED
    if report.run.status is DemoRunStatus.FAILED:
        return EXIT_FAILED
    return EXIT_BLOCKED


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

    model = args.model or Settings.from_env().openai_model
    if not model:
        print(
            "Planner blocked: set --model or PROOFDEMO_OPENAI_MODEL",
            file=sys.stderr,
        )
        return EXIT_BLOCKED
    try:
        result = PlanningService(OpenAIPlanner(model)).plan(intent)
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
    return EXIT_INVALID_INPUT


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
