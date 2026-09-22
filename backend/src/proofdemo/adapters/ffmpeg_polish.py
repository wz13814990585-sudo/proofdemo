"""Offline Chromium overlay assets and shell-free FFmpeg presentation rendering."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from proofdemo.adapters.ffmpeg_render import FFmpegRenderAdapter
from proofdemo.application.execution import safe_artifact_path
from proofdemo.domain.video_polish import FocusCue, VideoPolishPlan
from proofdemo.ports.render import MediaInfo
from proofdemo.ports.video_polish import PolishRenderError, PolishUnavailableError
from proofdemo.security import sanitize_diagnostic_text

_OVERLAY_HTML = """<!doctype html><html><head><style>
  * { box-sizing: border-box; }
  html, body { margin: 0; background: transparent; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Noto Sans CJK SC',
    'Segoe UI', sans-serif; color: #f7fbea; }
  #caption { width: 790px; height: 150px; display: flex; flex-direction: column;
    justify-content: center; padding: 20px 28px 20px 34px; border: 1px solid #7f9b6b;
    border-left: 7px solid #b4ff53; border-radius: 18px;
    background: rgba(13, 22, 15, .92); box-shadow: 0 15px 40px rgba(0,0,0,.3); }
  #scene-number { color: #b4ff53; font-size: 17px; letter-spacing: .14em;
    font-weight: 800; }
  #scene-title { display: -webkit-box; margin-top: 8px; font-size: 35px;
    line-height: 1.13; font-weight: 750; overflow-wrap: anywhere;
    -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; }
  #verified { width: 390px; min-height: 103px; padding: 21px 25px;
    border: 1px solid #b4ff53; border-radius: 17px;
    background: rgba(13, 27, 17, .94); box-shadow: 0 15px 40px rgba(0,0,0,.32); }
  #verified strong { display: block; color: #c9ff8d; font-size: 25px; }
  #verified span { display: block; margin-top: 4px; color: #d9e7ca; font-size: 17px; }
  .cursor { width: 126px; height: 48px; display: flex; align-items: center; gap: 9px;
    padding: 5px 13px 5px 7px; border-radius: 24px; background: rgba(16, 24, 16, .94);
    border: 1px solid #c8ff84; box-shadow: 0 7px 22px rgba(0,0,0,.35);
    color: #eaffce; font-size: 16px; font-weight: 800; letter-spacing: .07em; }
  .cursor i { display: block; width: 25px; height: 25px; border-radius: 50%;
    background: #b4ff53; border: 3px solid white; box-shadow: 0 0 0 3px #334b2a; }
</style></head><body>
  <div id="caption"><span id="scene-number"></span><strong id="scene-title"></strong></div>
  <div id="verified"><strong>✓ VERIFIED</strong><span id="assertion-count"></span></div>
  <div id="cursor-click" class="cursor"><i></i>CLICK</div>
  <div id="cursor-fill" class="cursor"><i></i>TYPE</div>
</body></html>"""


class FFmpegVideoPolisher:
    """Render fixed assets without a text filter, then composite via FFmpeg."""

    def __init__(
        self,
        *,
        ffmpeg_path: str | None = None,
        ffprobe_path: str | None = None,
        timeout_seconds: int = 600,
    ) -> None:
        self._ffmpeg = ffmpeg_path or shutil.which("ffmpeg")
        self._media = FFmpegRenderAdapter(ffprobe_path=ffprobe_path)
        self._timeout_seconds = timeout_seconds

    def probe(self, path: Path) -> MediaInfo:
        return self._media.probe(path)

    def render(
        self,
        source: Path,
        output: Path,
        plan: VideoPolishPlan,
        artifact_dir: Path,
    ) -> tuple[str, ...]:
        if self._ffmpeg is None:
            raise PolishUnavailableError("FFmpeg is unavailable for video polish")
        assets = self._render_assets(plan, artifact_dir)
        command = [
            self._ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
        ]
        for relative_path in assets:
            path = safe_artifact_path(artifact_dir, relative_path)
            command.extend(["-loop", "1", "-framerate", "30", "-i", str(path)])
        command.extend(
            [
                "-filter_complex",
                self.build_filter(plan, assets),
                "-map",
                "[polished]",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-threads",
                "1",
                "-map_metadata",
                "-1",
                "-fflags",
                "+bitexact",
                "-flags:v",
                "+bitexact",
                "-movflags",
                "+faststart",
                "-frames:v",
                str(round(plan.output_duration_ms * plan.output_fps / 1000)),
                str(output),
            ]
        )
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            )
        except FileNotFoundError as error:
            raise PolishUnavailableError("FFmpeg is unavailable for video polish") from error
        except subprocess.TimeoutExpired as error:
            raise PolishRenderError("FFmpeg polish timed out") from error
        if completed.returncode != 0:
            detail = sanitize_diagnostic_text(completed.stderr.strip(), max_length=1000)
            raise PolishRenderError(f"FFmpeg polish failed: {detail or 'unknown error'}")
        return assets

    @staticmethod
    def _render_assets(plan: VideoPolishPlan, artifact_dir: Path) -> tuple[str, ...]:
        paths = [
            *(f"polish/caption-{index + 1:02d}.png" for index in range(len(plan.scenes))),
            *(f"polish/verified-{index + 1:02d}.png" for index in range(len(plan.scenes))),
        ]
        kinds = {cue.kind for cue in plan.focus_cues}
        if "click" in kinds:
            paths.append("polish/cursor-click.png")
        if "fill" in kinds:
            paths.append("polish/cursor-fill.png")
        for relative_path in paths:
            safe_artifact_path(artifact_dir, relative_path).parent.mkdir(
                parents=True, exist_ok=True
            )
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    context = browser.new_context(
                        viewport={"width": 1920, "height": 1080},
                        service_workers="block",
                        device_scale_factor=1,
                    )
                    context.route("**/*", lambda route: route.abort())
                    page = context.new_page()
                    page.set_content(_OVERLAY_HTML)
                    for index, scene in enumerate(plan.scenes):
                        page.locator("#scene-number").evaluate(
                            "(node, value) => node.textContent = value",
                            f"SCENE {index + 1:02d}",
                        )
                        page.locator("#scene-title").evaluate(
                            "(node, value) => node.textContent = value", scene.title
                        )
                        page.locator("#caption").screenshot(
                            path=str(safe_artifact_path(artifact_dir, paths[index])),
                            omit_background=True,
                        )
                        page.locator("#assertion-count").evaluate(
                            "(node, value) => node.textContent = value",
                            f"{scene.passed_assertions} assertion(s) passed",
                        )
                        page.locator("#verified").screenshot(
                            path=str(
                                safe_artifact_path(artifact_dir, paths[len(plan.scenes) + index])
                            ),
                            omit_background=True,
                        )
                    for kind in ("click", "fill"):
                        if kind in kinds:
                            page.locator(f"#cursor-{kind}").screenshot(
                                path=str(
                                    safe_artifact_path(artifact_dir, f"polish/cursor-{kind}.png")
                                ),
                                omit_background=True,
                            )
                finally:
                    browser.close()
        except PlaywrightError as error:
            raise PolishUnavailableError("Chromium could not render text overlays") from error
        return tuple(paths)

    @staticmethod
    def build_filter(plan: VideoPolishPlan, assets: tuple[str, ...]) -> str:
        """Build a numeric-only filtergraph; no page or model text enters FFmpeg syntax."""
        parts: list[str] = []
        for index, scene in enumerate(plan.scenes):
            parts.append(
                f"[0:v]trim=start={scene.source_start_ms / 1000:.3f}:"
                f"end={scene.source_end_ms / 1000:.3f},setpts=PTS-STARTPTS,"
                f"tpad=stop_mode=clone:stop_duration={scene.hold_ms / 1000:.3f}[seg{index}]"
            )
        joined = "".join(f"[seg{index}]" for index in range(len(plan.scenes)))
        parts.append(
            f"{joined}concat=n={len(plan.scenes)}:v=1:a=0,fps=30,"
            "scale=1920:1080:force_original_aspect_ratio=decrease:flags=lanczos,"
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x0b1020[base]"
        )
        current = "base"
        if plan.focus_cues:
            zoom = "1"
            pan_x = "0"
            pan_y = "0"
            for cue in reversed(plan.focus_cues):
                start_frame = round(cue.zoom_start_ms * 30 / 1000)
                end_frame = round(cue.zoom_end_ms * 30 / 1000)
                if end_frame <= start_frame:
                    continue
                active = f"between(on,{start_frame},{end_frame})"
                pulse = f"1+0.18*sin(PI*(on-{start_frame})/{end_frame - start_frame})"
                zoom = f"if({active},{pulse},{zoom})"
                x = f"max(0,min(iw-iw/zoom,iw*{cue.x:.6f}-iw/(2*zoom)))"
                y = f"max(0,min(ih-ih/zoom,ih*{cue.y:.6f}-ih/(2*zoom)))"
                pan_x = f"if({active},{x},{pan_x})"
                pan_y = f"if({active},{y},{pan_y})"
            parts.append(
                f"[{current}]zoompan=z='{zoom}':x='{pan_x}':y='{pan_y}':"
                "d=1:s=1920x1080:fps=30[zoomed]"
            )
            current = "zoomed"
        for index, scene in enumerate(plan.scenes):
            start = scene.display_start_ms / 1000
            end = scene.display_end_ms / 1000
            caption_input = index + 1
            label = f"caption{index}"
            parts.append(
                f"[{caption_input}:v]format=rgba,"
                f"fade=t=in:st={start:.3f}:d=0.180:alpha=1,"
                f"fade=t=out:st={max(start, end - 0.180):.3f}:d=0.180:alpha=1[{label}]"
            )
            next_label = f"over{index}"
            parts.append(
                f"[{current}][{label}]overlay=x=65:y=870:"
                f"enable='between(t,{start:.3f},{end:.3f})':shortest=1[{next_label}]"
            )
            current = next_label
        for index, scene in enumerate(plan.scenes):
            start = (scene.display_end_ms - scene.hold_ms) / 1000
            end = scene.display_end_ms / 1000
            verify_input = len(plan.scenes) + index + 1
            label = f"verify{index}"
            parts.append(
                f"[{verify_input}:v]format=rgba,"
                f"fade=t=in:st={start:.3f}:d=0.180:alpha=1,"
                f"fade=t=out:st={max(start, end - 0.180):.3f}:d=0.180:alpha=1[{label}]"
            )
            next_label = f"badge{index}"
            parts.append(
                f"[{current}][{label}]overlay=x=1460:y=85:"
                f"enable='between(t,{start:.3f},{end:.3f})':shortest=1[{next_label}]"
            )
            current = next_label
        for kind in ("click", "fill"):
            path = f"polish/cursor-{kind}.png"
            if path not in assets:
                continue
            input_index = assets.index(path) + 1
            cues = [cue for cue in plan.focus_cues if cue.kind == kind]
            x, y, enabled = FFmpegVideoPolisher._cursor_expressions(cues)
            next_label = f"cursor{kind}"
            parts.append(
                f"[{current}][{input_index}:v]overlay=x='{x}':y='{y}':"
                f"enable='{enabled}':eval=frame:shortest=1[{next_label}]"
            )
            current = next_label
        for index, scene in enumerate(plan.scenes[:-1]):
            boundary = scene.display_end_ms / 1000
            next_label = f"transition{index}"
            parts.append(
                f"[{current}]fade=t=out:st={boundary - 0.080:.3f}:d=0.080,"
                f"fade=t=in:st={boundary:.3f}:d=0.080[{next_label}]"
            )
            current = next_label
        parts.append(f"[{current}]format=yuv420p[polished]")
        return ";".join(parts)

    @staticmethod
    def _cursor_expressions(cues: list[FocusCue]) -> tuple[str, str, str]:
        x_expression, y_expression = "0", "0"
        windows: list[str] = []
        for cue in reversed(cues):
            start = cue.cursor_start_ms / 1000
            action = cue.action_ms / 1000
            end = cue.zoom_start_ms / 1000
            windows.append(f"between(t,{start:.3f},{end:.3f})")
            if action - start < 0.001:
                ease = "1"
            else:
                fraction = f"max(0,min(1,(t-{start:.3f})/{action - start:.3f}))"
                ease = f"({fraction})*({fraction})*(3-2*({fraction}))"
            x = f"max(0,min(1794,1920*({cue.from_x:.6f}+({cue.x - cue.from_x:.6f})*({ease}))-18))"
            y = f"max(0,min(1032,1080*({cue.from_y:.6f}+({cue.y - cue.from_y:.6f})*({ease}))-24))"
            active = f"between(t,{start:.3f},{end:.3f})"
            x_expression = f"if({active},{x},{x_expression})"
            y_expression = f"if({active},{y},{y_expression})"
        return x_expression, y_expression, "+".join(windows) or "0"
