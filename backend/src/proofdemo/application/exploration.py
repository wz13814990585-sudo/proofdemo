"""Bounded same-origin reconnaissance and deterministic link admission."""

from __future__ import annotations

import re
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import monotonic
from urllib.parse import parse_qsl, urldefrag, urlsplit

from pydantic import HttpUrl

from proofdemo.application.execution import safe_artifact_path
from proofdemo.domain.exploration import (
    ExplorationReport,
    ExplorationStatus,
    ObservedControl,
    PageObservation,
)
from proofdemo.domain.planning import DemoIntent
from proofdemo.ports.explorer import (
    ExplorationUnavailableError,
    ExplorerPort,
    InvalidLinkChoice,
    LinkAdvisorPort,
)

_RISKY_PATH = re.compile(
    r"(?i)(?:^|[/_-])(logout|signout|delete|remove|purchase|checkout|pay|transfer|"
    r"unsubscribe|cancel-account|close-account)(?:$|[/_.-])"
)
_SECRET_QUERY_KEY = re.compile(
    r"(?i)(password|passcode|token|secret|api.?key|access.?key|authorization|auth.?code|session)"
)
_DOWNLOAD_PATH = re.compile(r"(?i)\.(?:zip|exe|dmg|pdf|csv|xlsx|mp4|webm)$")


def _origin(url: str) -> tuple[str, str, int] | None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    return parsed.scheme, parsed.hostname.lower(), port or (443 if parsed.scheme == "https" else 80)


def safe_exploration_url(source_url: str, candidate: str) -> str | None:
    """Admit only plausible read-only links on the declared origin."""
    parsed = urlsplit(candidate)
    source_origin = _origin(source_url)
    if (
        source_origin is None
        or _origin(candidate) != source_origin
        or parsed.username is not None
        or parsed.password is not None
        or _RISKY_PATH.search(parsed.path)
        or _DOWNLOAD_PATH.search(parsed.path)
        or any(_SECRET_QUERY_KEY.search(key) for key, _ in parse_qsl(parsed.query))
    ):
        return None
    normalized, _fragment = urldefrag(candidate)
    return normalized


class ExplorationService:
    """Select observed links under policy; model suggestions never become authority."""

    REPORT_PATH = "exploration_report.json"
    MAX_PAGES = 5
    MAX_CONTROLS_PER_PAGE = 120
    MAX_FRONTIER = 50
    MAX_SECONDS = 45.0

    def __init__(
        self,
        browser: ExplorerPort,
        advisor: LinkAdvisorPort,
        *,
        observation_observer: Callable[[int, PageObservation], None] | None = None,
    ) -> None:
        self._browser = browser
        self._advisor = advisor
        self._observation_observer = observation_observer

    def explore(self, intent: DemoIntent, artifact_dir: Path) -> ExplorationReport:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        source = str(intent.source_url)
        if safe_exploration_url(source, source) is None:
            return ExplorationReport(
                source_url=intent.source_url,
                status=ExplorationStatus.BLOCKED,
                pages=(),
                warnings=("Source URL is not safe for read-only exploration",),
                unvisited_link_count=0,
            )
        frontier: dict[str, str | None] = {source: None}
        visited: set[str] = set()
        pages: list[PageObservation] = []
        warnings: list[str] = []
        blocked = False
        deadline = monotonic() + self.MAX_SECONDS
        try:
            self._browser.open(source)
            while frontier and len(pages) < self.MAX_PAGES:
                if monotonic() >= deadline:
                    warnings.append("Exploration time budget was exhausted")
                    break
                if not pages:
                    next_url = source
                else:
                    suggested = self._advisor.choose(intent, tuple(pages), tuple(sorted(frontier)))
                    if suggested is None:
                        break
                    if suggested not in frontier:
                        raise InvalidLinkChoice("advisor selected an unobserved or unsafe link")
                    next_url = suggested
                remaining_ms = int((deadline - monotonic()) * 1_000)
                if remaining_ms <= 0:
                    warnings.append("Exploration time budget was exhausted")
                    break
                discovered_from = frontier.pop(next_url)
                visited.add(next_url)
                screenshot_name = f"exploration/page-{len(pages) + 1}.png"
                screenshot_path = safe_artifact_path(artifact_dir, screenshot_name)
                screenshot_path.parent.mkdir(parents=True, exist_ok=True)
                snapshot = self._browser.visit(
                    next_url,
                    screenshot_path=screenshot_path,
                    timeout_ms=min(15_000, remaining_ms),
                )
                if not screenshot_path.is_file():
                    raise ExplorationUnavailableError(
                        "browser did not capture an exploration screenshot"
                    )
                actual_url = safe_exploration_url(source, snapshot.url)
                if actual_url is None:
                    raise ExplorationUnavailableError(
                        "page redirected outside the safe source origin"
                    )
                visited.add(actual_url)
                observed_controls: list[ObservedControl] = []
                for control in snapshot.controls[: self.MAX_CONTROLS_PER_PAGE]:
                    name = control.name.strip()[:200]
                    if not name or control.kind not in {"link", "button", "input", "element"}:
                        continue
                    href = (
                        safe_exploration_url(source, control.href)
                        if control.kind == "link" and control.href
                        else None
                    )
                    if control.kind == "link" and href is None:
                        continue
                    observed_controls.append(
                        ObservedControl(
                            id=f"page-{len(pages) + 1}-control-{len(observed_controls) + 1}",
                            kind=control.kind,
                            name=name,
                            target=control.target,
                            href=HttpUrl(href) if href else None,
                        )
                    )
                    if href and href not in visited and len(frontier) < self.MAX_FRONTIER:
                        frontier.setdefault(href, actual_url)
                pages.append(
                    PageObservation(
                        url=HttpUrl(actual_url),
                        title=snapshot.title.strip()[:200],
                        headings=tuple(item.strip()[:200] for item in snapshot.headings[:30]),
                        controls=tuple(observed_controls),
                        discovered_from=HttpUrl(discovered_from) if discovered_from else None,
                        screenshot_path=screenshot_name,
                        screenshot_sha256=sha256(screenshot_path.read_bytes()).hexdigest(),
                    )
                )
                if self._observation_observer is not None:
                    self._observation_observer(len(pages), pages[-1])
                frontier.pop(actual_url, None)
            if frontier and not warnings:
                warnings.append(f"{len(frontier)} safe observed links were not visited")
        except (ExplorationUnavailableError, InvalidLinkChoice) as error:
            blocked = True
            warnings.append(str(error))
        except Exception as error:
            blocked = True
            warnings.append(f"Unexpected exploration failure: {type(error).__name__}")
        finally:
            try:
                self._browser.close()
            except Exception:
                blocked = True
                warnings.append("Exploration browser cleanup failed")
        status = (
            ExplorationStatus.BLOCKED
            if blocked
            else ExplorationStatus.PARTIAL
            if frontier
            else ExplorationStatus.COMPLETE
        )
        return ExplorationReport(
            source_url=intent.source_url,
            status=status,
            pages=tuple(pages),
            warnings=tuple(warnings[:20]),
            unvisited_link_count=len(frontier),
        )

    @staticmethod
    def write(report: ExplorationReport, artifact_dir: Path) -> Path:
        path = safe_artifact_path(artifact_dir, ExplorationService.REPORT_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as temporary:
            temporary.write(report.model_dump_json(indent=2) + "\n")
            temporary.flush()
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)
        return path
