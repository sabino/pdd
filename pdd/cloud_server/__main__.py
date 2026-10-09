"""Start the optional service independently from a project workspace."""

from __future__ import annotations

import argparse
import os

import uvicorn

from pdd.cloud_server.app import create_app
from pdd.cloud_server.config import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the PDD self-hosted API and command relay"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9877)
    arguments = parser.parse_args()
    browser_host = "127.0.0.1" if arguments.host == "0.0.0.0" else arguments.host
    os.environ.setdefault(
        "PDD_SERVER_PUBLIC_URL", f"http://{browser_host}:{arguments.port}"
    )
    os.environ["PDD_FORCE_LOCAL"] = "1"
    os.environ["PDD_NO_INTERACTIVE"] = "1"
    try:
        settings = load_settings()
    except (ValueError, OSError) as error:
        parser.error(str(error))
    uvicorn.run(create_app(settings), host=arguments.host, port=arguments.port)


if __name__ == "__main__":
    main()
