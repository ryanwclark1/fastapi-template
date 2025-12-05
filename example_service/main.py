"""Main entry point for example-service.

This module serves as the unified entry point for both CLI and FastAPI modes.
It detects the mode based on command-line arguments:
- If arguments are provided: runs CLI
- If --server flag is provided: runs FastAPI server
- Default: runs CLI
"""

from __future__ import annotations

import sys
from typing import NoReturn


def run_fastapi_server() -> NoReturn:
    """Run the FastAPI application server.

    Uses uvicorn as the ASGI server with settings from configuration.
    """
    import uvicorn

    from example_service.core.settings import get_app_settings, get_logging_settings

    settings = get_app_settings()
    log_settings = get_logging_settings()

    uvicorn.run(
        "example_service.app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        access_log=settings.debug,
        log_level=log_settings.level.lower(),
    )
    sys.exit(0)


def run_cli() -> NoReturn:
    """Run the CLI interface."""
    from example_service.cli.main import main as cli_main

    cli_main()
    sys.exit(0)


def main() -> NoReturn:
    """Main entry point - routes to CLI or server based on arguments.

    Routing logic:
    - If --server flag is present: run FastAPI server
    - If any other arguments: run CLI
    - If no arguments: run CLI (shows help)
    """
    # Check if --server flag is present
    if "--server" in sys.argv:
        # Remove --server flag before running
        sys.argv.remove("--server")
        run_fastapi_server()
    else:
        # Run CLI for all other cases
        run_cli()


if __name__ == "__main__":
    main()
