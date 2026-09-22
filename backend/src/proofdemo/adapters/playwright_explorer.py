"""Isolated Playwright read-only UI observation for grounded planning."""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, Route, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from proofdemo.domain.demo_spec import (
    CssTarget,
    ElementTarget,
    LabelTarget,
    RoleTarget,
    TestIdTarget,
)
from proofdemo.ports.explorer import (
    ControlSnapshot,
    ExplorationUnavailableError,
    PageSnapshot,
)

_VISIBLE_CONTROLS = """() => {
  const nodes = [...document.querySelectorAll(
    'a[href],button,input,textarea,select,[data-testid]')].slice(0, 500);
  return nodes.filter(node => {
    const style = getComputedStyle(node);
    return node.getClientRects().length > 0 && style.visibility !== 'hidden'
      && style.display !== 'none';
  }).slice(0, 180).map(node => {
    const tag = node.tagName.toLowerCase();
    const kind = tag === 'a' ? 'link' : tag === 'button' ? 'button'
      : ['input', 'textarea', 'select'].includes(tag) ? 'input' : 'element';
    const inputType = tag === 'input' ? (node.getAttribute('type') || 'text').toLowerCase() : '';
    const label = node.labels?.[0]?.innerText?.trim() || '';
    const name = kind === 'element' ? (node.getAttribute('data-testid') || '')
      : kind === 'input' ? (node.getAttribute('aria-label') || label ||
          node.getAttribute('placeholder') || node.getAttribute('title') || '').trim()
      : (node.getAttribute('aria-label') || label || node.innerText ||
          node.getAttribute('title') || '').trim();
    return {
      kind, inputType, name: name.slice(0, 200), label: label.slice(0, 200),
      testId: node.getAttribute('data-testid') || '',
      cssId: node.id ? '#' + CSS.escape(node.id) : '',
      href: kind === 'link' ? node.href : null,
      download: kind === 'link' && node.hasAttribute('download'),
    };
  });
}"""


def _origin(url: str) -> tuple[str, str, int] | None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    return parsed.scheme, parsed.hostname.lower(), port or (443 if parsed.scheme == "https" else 80)


class PlaywrightExplorer:
    """Visit same-origin URLs, inspect visible structure, and never click or fill."""

    def __init__(self, *, headless: bool = True) -> None:
        self._headless = headless
        self._origin: tuple[str, str, int] | None = None
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    def open(self, source_url: str) -> None:
        origin = _origin(source_url)
        if origin is None:
            raise ExplorationUnavailableError("exploration requires one HTTP(S) source origin")
        self._origin = origin
        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=self._headless)
            self._context = self._browser.new_context(
                viewport={"width": 1280, "height": 720},
                locale="en-US",
                accept_downloads=False,
                service_workers="block",
            )
            self._context.route("**/*", self._route_request)
            self._page = self._context.new_page()
        except Exception as error:
            with suppress(Exception):
                self.close()
            raise ExplorationUnavailableError("Chromium could not start for exploration") from error

    def visit(self, url: str, *, screenshot_path: Path, timeout_ms: int) -> PageSnapshot:
        if _origin(url) != self._origin or self._page is None:
            raise ExplorationUnavailableError("exploration navigation left the source origin")
        page = self._page
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            if _origin(page.url) != self._origin:
                raise ExplorationUnavailableError(
                    "exploration redirected outside the source origin"
                )
            page.locator("body").wait_for(state="visible", timeout=min(5_000, timeout_ms))
            page.wait_for_timeout(150)
            raw_controls: Any = page.evaluate(_VISIBLE_CONTROLS)
            if not isinstance(raw_controls, list):
                raise ExplorationUnavailableError("browser returned no control snapshot")
            headings = tuple(
                text.strip()[:200]
                for text in page.locator("h1,h2,h3").evaluate_all(
                    "nodes => nodes.slice(0, 30).map(node => node.innerText)"
                )
                if text.strip()
            )
            controls = tuple(
                self._control(page, item) for item in raw_controls if isinstance(item, dict)
            )
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(screenshot_path), full_page=False)
            return PageSnapshot(
                url=page.url,
                title=page.title()[:200],
                headings=headings,
                controls=tuple(control for control in controls if control is not None),
            )
        except ExplorationUnavailableError:
            raise
        except PlaywrightError as error:
            raise ExplorationUnavailableError("browser could not inspect this page") from error

    def close(self) -> None:
        context, browser, playwright = self._context, self._browser, self._playwright
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        if context is not None:
            context.close()
        if browser is not None:
            browser.close()
        if playwright is not None:
            playwright.stop()

    def _route_request(self, route: Route) -> None:
        request = route.request
        if request.method != "GET" or _origin(request.url) != self._origin:
            route.abort()
        else:
            try:
                response = route.fetch(max_redirects=0, timeout=10_000)
                if 300 <= response.status < 400:
                    route.abort()
                else:
                    route.fulfill(response=response)
            except PlaywrightError:
                route.abort()

    @staticmethod
    def _control(page: Page, raw: dict[str, Any]) -> ControlSnapshot | None:
        kind = raw.get("kind")
        name = raw.get("name")
        if raw.get("download"):
            return None
        if kind not in {"link", "button", "input", "element"} or not isinstance(name, str):
            return None
        name = name.strip()[:200]
        if not name or (kind == "input" and raw.get("inputType") in {"password", "hidden", "file"}):
            return None
        target: ElementTarget | None = None
        test_id = raw.get("testId")
        label = raw.get("label")
        css_id = raw.get("cssId")
        if isinstance(test_id, str) and test_id and page.get_by_test_id(test_id).count() == 1:
            target = TestIdTarget(strategy="test_id", test_id=test_id[:200])
        elif (
            kind == "input"
            and isinstance(label, str)
            and label
            and page.get_by_label(label, exact=True).count() == 1
        ):
            target = LabelTarget(strategy="label", label=label[:500])
        elif (
            kind in {"button", "link"}
            and page.get_by_role(cast(Any, kind), name=name, exact=True).count() == 1
        ):
            target = RoleTarget(strategy="role", role=kind, name=name)
        elif isinstance(css_id, str) and css_id and page.locator(css_id).count() == 1:
            target = CssTarget(strategy="css", selector=css_id[:1_000])
        href = None if raw.get("download") else raw.get("href")
        return ControlSnapshot(
            kind=kind,
            name=name,
            target=target,
            href=href if isinstance(href, str) else None,
        )
