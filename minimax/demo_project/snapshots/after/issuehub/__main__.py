"""Run the demo API: python -m issuehub --port 8766."""

from __future__ import annotations

import argparse

from .api import run_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the issuehub demo API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    print(f"issuehub listening on http://{args.host}:{args.port}")
    run_server(args.host, args.port)


if __name__ == "__main__":
    main()
