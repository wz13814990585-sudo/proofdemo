"""Serve the deterministic Stage 1 Todo fixture with the standard library."""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "examples" / "todo_app"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=4173, type=int)
    args = parser.parse_args()
    handler = partial(SimpleHTTPRequestHandler, directory=str(FIXTURE_DIR))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Todo fixture listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
