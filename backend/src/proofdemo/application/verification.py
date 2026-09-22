"""Deterministic assertion evaluation and scene outcome models."""

from __future__ import annotations

from enum import StrEnum
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from proofdemo.domain.demo_spec import (
    AppStateEqualsAssertion,
    Assertion,
    DownloadCompletedAssertion,
    ElementVisibleAssertion,
    Scene,
    TextContainsAssertion,
    UrlEqualsAssertion,
)
from proofdemo.ports.browser import BrowserActionError, BrowserPort, BrowserUnavailableError


class OutcomeStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class VerificationStatus(StrEnum):
    NOT_RUN = "NOT_RUN"
    PASSED = "PASSED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class AssertionEvidence(BaseModel):
    """Expected and observed JSON-compatible values for one assertion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str
    expected: JsonValue
    observed: JsonValue


class AssertionResult(BaseModel):
    """One assertion outcome correlated by stable scene and assertion IDs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scene_id: str
    assertion_id: str
    assertion_type: str
    status: OutcomeStatus
    evidence: AssertionEvidence | None = None
    reason: str | None = Field(default=None, min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def validate_result(self) -> AssertionResult:
        if self.status is OutcomeStatus.PASSED:
            if self.evidence is None or self.reason is not None:
                raise ValueError("passed assertions require evidence and no reason")
        elif self.reason is None:
            raise ValueError("failed or blocked assertions require a reason")
        return self


class SceneResult(BaseModel):
    """Aggregate scene outcome with all of its assertion results."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scene_id: str
    status: OutcomeStatus
    assertion_results: tuple[AssertionResult, ...]
    reason: str | None = Field(default=None, min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def validate_result(self) -> SceneResult:
        if self.status is OutcomeStatus.PASSED:
            if self.reason is not None:
                raise ValueError("passed scenes cannot include a reason")
            if not self.assertion_results or any(
                result.status is not OutcomeStatus.PASSED for result in self.assertion_results
            ):
                raise ValueError("passed scenes require all assertions to pass")
        elif self.reason is None:
            raise ValueError("failed or blocked scenes require a reason")
        return self


def _canonical_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        return url
    default_port = 443 if parsed.scheme == "https" else 80
    port = parsed.port or default_port
    authority = parsed.hostname.lower()
    if port != default_port:
        authority = f"{authority}:{port}"
    return urlunsplit((parsed.scheme, authority, parsed.path or "/", parsed.query, parsed.fragment))


def assertion_problem(
    scene_id: str,
    assertion: Assertion,
    status: OutcomeStatus,
    reason: str,
) -> AssertionResult:
    """Create a reasoned assertion result when no observation is available."""
    return AssertionResult(
        scene_id=scene_id,
        assertion_id=assertion.id,
        assertion_type=assertion.type,
        status=status,
        reason=reason,
    )


def unverified_scene(scene: Scene, status: OutcomeStatus, reason: str) -> SceneResult:
    """Represent a scene whose assertions could not run after execution stopped."""
    return SceneResult(
        scene_id=scene.id,
        status=status,
        assertion_results=tuple(
            assertion_problem(
                scene.id,
                assertion,
                OutcomeStatus.BLOCKED,
                f"Not evaluated because scene execution did not complete: {reason}",
            )
            for assertion in scene.assertions
        ),
        reason=reason,
    )


class VerificationService:
    """Evaluate one scene's assertions from narrow browser observations."""

    def __init__(self, browser: BrowserPort) -> None:
        self._browser = browser

    def verify_scene(self, scene: Scene) -> SceneResult:
        results: list[AssertionResult] = []
        for index, assertion in enumerate(scene.assertions):
            try:
                evidence, passed, failure_reason = self._evaluate(assertion)
            except BrowserUnavailableError as error:
                reason = self._reason(error)
                results.append(
                    assertion_problem(scene.id, assertion, OutcomeStatus.BLOCKED, reason)
                )
                self._append_blocked_assertions(
                    results,
                    scene,
                    index,
                    f"Not evaluated after unavailable observation: {reason}",
                )
                break
            except BrowserActionError as error:
                results.append(
                    assertion_problem(
                        scene.id,
                        assertion,
                        OutcomeStatus.FAILED,
                        self._reason(error),
                    )
                )
                continue
            except Exception as error:  # defensive observation boundary
                reason = f"Unexpected observation error: {type(error).__name__}"
                results.append(
                    assertion_problem(scene.id, assertion, OutcomeStatus.BLOCKED, reason)
                )
                self._append_blocked_assertions(results, scene, index, reason)
                break

            results.append(
                AssertionResult(
                    scene_id=scene.id,
                    assertion_id=assertion.id,
                    assertion_type=assertion.type,
                    status=OutcomeStatus.PASSED if passed else OutcomeStatus.FAILED,
                    evidence=evidence,
                    reason=None if passed else failure_reason,
                )
            )
        return self._scene_result(scene, tuple(results))

    def _evaluate(self, assertion: Assertion) -> tuple[AssertionEvidence, bool, str]:
        if isinstance(assertion, ElementVisibleAssertion):
            visible_observed = self._browser.is_visible(
                assertion.target,
                timeout_ms=assertion.timeout_ms,
            )
            return (
                AssertionEvidence(
                    kind=assertion.type,
                    expected=True,
                    observed=visible_observed,
                ),
                visible_observed,
                "Expected element was not visible",
            )
        if isinstance(assertion, TextContainsAssertion):
            text_observed = self._browser.text_content(
                assertion.target,
                timeout_ms=assertion.timeout_ms,
            )
            text_passed = text_observed is not None and assertion.expected_text in text_observed
            return (
                AssertionEvidence(
                    kind=assertion.type,
                    expected=assertion.expected_text,
                    observed=text_observed,
                ),
                text_passed,
                "Observed text did not contain the expected text",
            )
        if isinstance(assertion, UrlEqualsAssertion):
            url_expected = _canonical_url(str(assertion.expected_url))
            url_observed = _canonical_url(self._browser.current_url())
            return (
                AssertionEvidence(
                    kind=assertion.type,
                    expected=url_expected,
                    observed=url_observed,
                ),
                url_observed == url_expected,
                "Current URL did not equal the expected URL",
            )
        if isinstance(assertion, DownloadCompletedAssertion):
            download_observation = self._browser.completed_download(
                assertion.filename,
                timeout_ms=assertion.timeout_ms,
            )
            download_expected: JsonValue = {
                "filename": assertion.filename,
                "completed": True,
            }
            download_observed: JsonValue = {
                "filename": download_observation.filename,
                "completed": download_observation.completed,
                "byte_count": download_observation.byte_count,
                "failure": download_observation.failure,
            }
            download_passed = (
                download_observation.filename == assertion.filename
                and download_observation.completed
            )
            return (
                AssertionEvidence(
                    kind=assertion.type,
                    expected=download_expected,
                    observed=download_observed,
                ),
                download_passed,
                "Expected download did not complete",
            )
        if isinstance(assertion, AppStateEqualsAssertion):
            app_observation = self._browser.application_state(assertion.key)
            app_expected: JsonValue = {"found": True, "value": assertion.expected_value}
            app_observed: JsonValue = {
                "found": app_observation.found,
                "value": app_observation.value,
            }
            app_passed = app_observation.found and app_observation.value == assertion.expected_value
            return (
                AssertionEvidence(
                    kind=assertion.type,
                    expected=app_expected,
                    observed=app_observed,
                ),
                app_passed,
                "Application state did not equal the expected JSON value",
            )
        raise BrowserActionError(f"Unsupported assertion type: {type(assertion).__name__}")

    @staticmethod
    def _scene_result(scene: Scene, assertion_results: tuple[AssertionResult, ...]) -> SceneResult:
        failed = next(
            (result for result in assertion_results if result.status is OutcomeStatus.FAILED),
            None,
        )
        if failed is not None:
            return SceneResult(
                scene_id=scene.id,
                status=OutcomeStatus.FAILED,
                assertion_results=assertion_results,
                reason=failed.reason or f"Assertion {failed.assertion_id} failed",
            )
        blocked = next(
            (result for result in assertion_results if result.status is OutcomeStatus.BLOCKED),
            None,
        )
        if blocked is not None:
            return SceneResult(
                scene_id=scene.id,
                status=OutcomeStatus.BLOCKED,
                assertion_results=assertion_results,
                reason=blocked.reason or f"Assertion {blocked.assertion_id} was blocked",
            )
        return SceneResult(
            scene_id=scene.id,
            status=OutcomeStatus.PASSED,
            assertion_results=assertion_results,
        )

    @staticmethod
    def _append_blocked_assertions(
        results: list[AssertionResult],
        scene: Scene,
        current_index: int,
        reason: str,
    ) -> None:
        results.extend(
            assertion_problem(scene.id, assertion, OutcomeStatus.BLOCKED, reason)
            for assertion in scene.assertions[current_index + 1 :]
        )

    @staticmethod
    def _reason(error: Exception) -> str:
        return str(error).strip() or type(error).__name__
