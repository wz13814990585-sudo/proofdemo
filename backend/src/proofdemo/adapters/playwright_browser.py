"""Synchronous Playwright implementation of the deterministic browser port."""

from __future__ import annotations

from pathlib import Path
from time import monotonic
from typing import Any, cast
from urllib.parse import urlsplit

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Download,
    Locator,
    Page,
    Playwright,
    sync_playwright,
)
from playwright.sync_api import (
    Error as PlaywrightError,
)
from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
)
from pydantic import JsonValue, TypeAdapter, ValidationError

from proofdemo.domain.demo_spec import (
    CssTarget,
    ElementTarget,
    LabelTarget,
    RoleTarget,
    TestIdTarget,
    TextTarget,
)
from proofdemo.ports.browser import (
    AppStateObservation,
    BrowserActionError,
    BrowserUnavailableError,
    DownloadObservation,
)

Origin = tuple[str, str, int]
JSON_VALUE_ADAPTER: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


def _origin(url: str) -> Origin:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        raise BrowserActionError("browser navigation requires an HTTP(S) URL with a host")
    default_port = 443 if parsed.scheme == "https" else 80
    return parsed.scheme, parsed.hostname.lower(), parsed.port or default_port


class PlaywrightBrowser:
    """One isolated Chromium page with runtime same-origin enforcement."""

    def __init__(self, *, headless: bool = True) -> None:
        self._headless = headless
        self._allowed_origin: Origin | None = None
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._downloads: list[Download] = []

    def open(self, source_url: str) -> None:
        self._allowed_origin = _origin(source_url)
        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=self._headless)
            self._context = self._browser.new_context(
                viewport={"width": 1280, "height": 720},
                locale="en-US",
                accept_downloads=True,
            )
            self._page = self._context.new_page()
            self._page.on("download", lambda download: self._downloads.append(download))
        except Exception as error:
            self._shutdown()
            raise BrowserUnavailableError(f"Chromium could not start: {error}") from error

    def goto(self, url: str, *, timeout_ms: int) -> None:
        if self._allowed_origin is None:
            raise BrowserUnavailableError("browser session is not open")
        if _origin(url) != self._allowed_origin:
            raise BrowserActionError("navigation attempted to leave the source origin")
        page = self._require_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            if _origin(page.url) != self._allowed_origin:
                raise BrowserActionError("navigation redirected outside the source origin")
        except BrowserActionError:
            raise
        except PlaywrightTimeoutError as error:
            raise BrowserActionError(f"navigation timed out after {timeout_ms} ms") from error
        except PlaywrightError as error:
            raise BrowserActionError(f"navigation failed: {error}") from error

    def click(self, target: ElementTarget, *, timeout_ms: int) -> None:
        try:
            self._locator(target).click(timeout=timeout_ms)
        except PlaywrightTimeoutError as error:
            raise BrowserActionError(
                f"click target was not actionable within {timeout_ms} ms"
            ) from error
        except PlaywrightError as error:
            raise BrowserActionError(f"click failed: {error}") from error

    def fill(self, target: ElementTarget, value: str, *, timeout_ms: int) -> None:
        try:
            self._locator(target).fill(value, timeout=timeout_ms)
        except PlaywrightTimeoutError as error:
            raise BrowserActionError(
                f"fill target was not actionable within {timeout_ms} ms"
            ) from error
        except PlaywrightError as error:
            raise BrowserActionError(f"fill failed: {error}") from error

    def pause(self, duration_ms: int) -> None:
        self._require_page().wait_for_timeout(duration_ms)

    def screenshot(self, path: Path, *, full_page: bool) -> None:
        try:
            self._require_page().screenshot(path=str(path), full_page=full_page)
        except PlaywrightError as error:
            raise BrowserActionError(f"could not capture screenshot: {error}") from error

    def is_visible(self, target: ElementTarget, *, timeout_ms: int) -> bool:
        try:
            self._locator(target).wait_for(state="visible", timeout=timeout_ms)
            return True
        except PlaywrightTimeoutError:
            return False
        except PlaywrightError as error:
            raise BrowserActionError(f"visibility observation failed: {error}") from error

    def text_content(self, target: ElementTarget, *, timeout_ms: int) -> str | None:
        try:
            return self._locator(target).text_content(timeout=timeout_ms)
        except PlaywrightTimeoutError:
            return None
        except PlaywrightError as error:
            raise BrowserActionError(f"text observation failed: {error}") from error

    def current_url(self) -> str:
        return self._require_page().url

    def completed_download(self, filename: str, *, timeout_ms: int) -> DownloadObservation:
        page = self._require_page()
        deadline = monotonic() + (timeout_ms / 1_000)
        while monotonic() < deadline:
            matching = [item for item in self._downloads if item.suggested_filename == filename]
            if matching:
                download = matching[-1]
                try:
                    failure = download.failure()
                    path = download.path() if failure is None else None
                    byte_count = path.stat().st_size if path is not None else None
                except PlaywrightError as error:
                    raise BrowserActionError(f"download observation failed: {error}") from error
                return DownloadObservation(
                    filename=filename,
                    completed=failure is None and path is not None,
                    byte_count=byte_count,
                    failure=failure,
                )
            page.wait_for_timeout(min(50, max(1, int((deadline - monotonic()) * 1_000))))
        return DownloadObservation(filename=None, completed=False)

    def application_state(self, key: str) -> AppStateObservation:
        try:
            raw = self._require_page().evaluate(
                """
                key => {
                  const state = window.__PROOFDEMO_STATE__;
                  if (state === null || typeof state !== "object") {
                    return { found: false, value: null };
                  }
                  if (!Object.prototype.hasOwnProperty.call(state, key)) {
                    return { found: false, value: null };
                  }
                  return { found: true, value: state[key] };
                }
                """,
                key,
            )
            if not isinstance(raw, dict) or not isinstance(raw.get("found"), bool):
                raise BrowserActionError("application-state hook returned an invalid envelope")
            return AppStateObservation(
                found=raw["found"],
                value=JSON_VALUE_ADAPTER.validate_python(raw.get("value")),
            )
        except BrowserActionError:
            raise
        except (PlaywrightError, ValidationError) as error:
            raise BrowserActionError(f"application-state observation failed: {error}") from error

    def close(self) -> None:
        errors = self._shutdown()
        if errors:
            raise BrowserUnavailableError(f"browser cleanup failed: {errors[0]}")

    def _locator(self, target: ElementTarget) -> Locator:
        page = self._require_page()
        if isinstance(target, RoleTarget):
            return page.get_by_role(
                cast(Any, target.role),
                name=target.name,
                exact=target.exact,
            )
        if isinstance(target, LabelTarget):
            return page.get_by_label(target.label, exact=target.exact)
        if isinstance(target, TextTarget):
            return page.get_by_text(target.text, exact=target.exact)
        if isinstance(target, TestIdTarget):
            return page.get_by_test_id(target.test_id)
        if isinstance(target, CssTarget):
            return page.locator(target.selector)
        raise BrowserActionError(f"unsupported target type: {type(target).__name__}")

    def _require_page(self) -> Page:
        if self._page is None:
            raise BrowserUnavailableError("browser session is not open")
        return self._page

    def _shutdown(self) -> list[Exception]:
        errors: list[Exception] = []
        if self._context is not None:
            try:
                self._context.close()
            except Exception as error:
                errors.append(error)
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception as error:
                errors.append(error)
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception as error:
                errors.append(error)
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        self._allowed_origin = None
        self._downloads = []
        return errors
