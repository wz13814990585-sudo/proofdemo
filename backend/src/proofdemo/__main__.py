"""Command-line entry point for the development API server."""

import uvicorn

from proofdemo.config import Settings


def main() -> None:
    """Run the ProofDemo API using environment-backed settings."""
    settings = Settings.from_env()
    uvicorn.run(
        "proofdemo.api:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.environment == "development",
    )


if __name__ == "__main__":
    main()
