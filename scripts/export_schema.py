"""Export the authoritative DemoSpec JSON Schema for other runtimes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = ROOT / "backend" / "src"
sys.path.insert(0, str(BACKEND_SRC))

from proofdemo.domain.demo_spec import DemoSpec  # noqa: E402


def main() -> None:
    """Write a stable, formatted schema to the shared contract directory."""
    output = ROOT / "shared" / "schemas" / "demo_spec.schema.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(DemoSpec.model_json_schema(mode="validation"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
