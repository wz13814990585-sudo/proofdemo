"""Synchronous Playwright implementation of the Stage 1 browser port."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from playwright.sync_api import (
    Browser,
    BrowserContext,
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

from proofdemo.domain.demo_spec import (
    CssTarget,
    ElementTarget,
    LabelTarget,
    RoleTarget,
    TestIdTarget,
    TextTarget,
)
from proofdemo.ports.browser import BrowserActionError, BrowserUnavailableError

Origin = tuple[str, str, int]


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

    def open(self, source_url: str) -> None:
        self._allowed_origin = _origin(source_url)
        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=self._headless)
            self._context = self._browser.new_context(
                viewport={"width": 1280, "height": 720},
                locale="en-US",
            )
            self._page = self._context.new_page()
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
        return errors
