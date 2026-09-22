"""Chromium exploration must not submit, leak input values or leave the origin."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from proofdemo.adapters.playwright_browser import PlaywrightBrowser
from proofdemo.adapters.playwright_explorer import PlaywrightExplorer
from proofdemo.application.exploration import ExplorationService
from proofdemo.domain.demo_spec import RoleTarget
from proofdemo.domain.exploration import ExplorationStatus
from proofdemo.domain.planning import DemoIntent
from proofdemo.ports.browser import BrowserActionError


@pytest.fixture
def guarded_site() -> Iterator[tuple[str, dict[str, int]]]:
    counts = {"post": 0, "cross_origin": 0}

    class RemoteHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            counts["cross_origin"] += 1
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"remote")

        def log_message(self, format: str, *args: object) -> None:
            pass

    remote = ThreadingHTTPServer(("127.0.0.1", 0), RemoteHandler)
    remote_url = f"http://127.0.0.1:{remote.server_address[1]}/probe"

    class SourceHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", remote_url)
                self.end_headers()
                return
            body = f"""<!doctype html><html><head><title>Guarded</title></head><body>
              <h1>Safe home</h1><label for="name">Name</label>
              <input id="name" value="secret-sentinel">
              <label for="password">Password</label>
              <input id="password" type="password" value="password-sentinel">
              <a href="/details">Details</a>
              <a href="{remote_url}">External</a>
              <img src="{remote_url}">
              <script>fetch('/mutation', {{method: 'POST', body: 'secret-sentinel'}});</script>
              </body></html>""".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            counts["post"] += 1
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass

    source = ThreadingHTTPServer(("127.0.0.1", 0), SourceHandler)
    threads = [
        threading.Thread(target=remote.serve_forever, daemon=True),
        threading.Thread(target=source.serve_forever, daemon=True),
    ]
    for thread in threads:
        thread.start()
    try:
        yield f"http://127.0.0.1:{source.server_address[1]}/", counts
    finally:
        source.shutdown()
        remote.shutdown()
        source.server_close()
        remote.server_close()
        for thread in threads:
            thread.join(timeout=2)


def test_real_explorer_blocks_posts_cross_origin_and_input_values(
    guarded_site: tuple[str, dict[str, int]], tmp_path: Path
) -> None:
    url, counts = guarded_site
    browser = PlaywrightExplorer()
    browser.open(url)
    try:
        snapshot = browser.visit(url, screenshot_path=tmp_path / "page.png", timeout_ms=15_000)
    finally:
        browser.close()

    assert snapshot.title == "Guarded"
    assert any(control.name == "Name" for control in snapshot.controls)
    assert not any(control.name == "Password" for control in snapshot.controls)
    assert "secret-sentinel" not in str(snapshot)
    assert "password-sentinel" not in str(snapshot)
    assert counts == {"post": 0, "cross_origin": 0}
    assert (tmp_path / "page.png").stat().st_size > 0


class NoLinks:
    def choose(self, intent: DemoIntent, pages: tuple, candidates: tuple[str, ...]) -> None:
        return None


def test_cross_origin_redirect_blocks_report(
    guarded_site: tuple[str, dict[str, int]], tmp_path: Path
) -> None:
    url, counts = guarded_site
    report = ExplorationService(PlaywrightExplorer(), NoLinks()).explore(
        DemoIntent(source_url=f"{url}redirect", goal="Show details"), tmp_path
    )

    assert report.status is ExplorationStatus.BLOCKED
    assert report.pages == ()
    assert report.warnings
    assert counts["cross_origin"] == 0


def test_execution_browser_blocks_cross_origin_click_and_redirect(
    guarded_site: tuple[str, dict[str, int]],
) -> None:
    url, counts = guarded_site
    browser = PlaywrightBrowser()
    browser.open(url)
    try:
        browser.goto(url, timeout_ms=5_000)
        with pytest.raises(BrowserActionError):
            browser.click(
                RoleTarget(strategy="role", role="link", name="External"),
                timeout_ms=5_000,
            )
        with pytest.raises(BrowserActionError):
            browser.goto(f"{url}redirect", timeout_ms=5_000)
    finally:
        browser.close()
    assert counts["cross_origin"] == 0
