"""Command line entry point for the SDD context module."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil

from . import config
from .context import build_context
from .demo import run_demo
from .materials import collect_materials
from .powercontext_runtime import PowerContextRuntime
from .store import MaterialStore
from .verify import verify_modification


async def _ingest() -> dict[str, object]:
    runtime = PowerContextRuntime()
    runtime.start()
    try:
        scope_id = await runtime.ensure_scope()
        store = MaterialStore(runtime.client, scope_id)
        stats = await store.upsert(collect_materials())
        return {"scope_id": scope_id, "backend": runtime.backend, **stats.as_dict()}
    finally:
        await runtime.aclose()


async def _context() -> dict[str, object]:
    runtime = PowerContextRuntime()
    runtime.start()
    try:
        scope_id = await runtime.ensure_scope()
        store = MaterialStore(runtime.client, scope_id)
        return await build_context(store, runtime=runtime.describe())
    finally:
        await runtime.aclose()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="sdd-context", description="SDD engineering context for issuehub")
    parser.add_argument("--db", choices=["auto", "seekdb", "sqlite"], default=None, help="database backend override")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ingest", help="import specs, code and tests into PowerContext")
    context_parser = sub.add_parser("context", help="print the selected context for TASK-001")
    context_parser.add_argument("--format", choices=["json", "markdown"], default="json")
    demo_parser = sub.add_parser("demo", help="run the full ingest -> selection -> MiniMax -> test -> restart flow")
    demo_parser.add_argument("--offline", action="store_true", help="replay records/minimax_recorded.json")
    demo_parser.add_argument("--skip-minimax", action="store_true", help="exercise the context/state pipeline without a model call")
    sub.add_parser("verify", help="run before/after target and regression tests")
    sub.add_parser("reset", help="remove the local PowerContext data directory")

    args = parser.parse_args(argv)
    if args.db:
        import os

        os.environ["SDD_DB"] = args.db

    known = config.database_backend()
    if args.command == "ingest":
        print(json.dumps(asyncio.run(_ingest()), ensure_ascii=False, indent=2))
    elif args.command == "context":
        context = asyncio.run(_context())
        if args.format == "markdown":
            print(context["markdown"])
        else:
            print(json.dumps(context, ensure_ascii=False, indent=2))
    elif args.command == "demo":
        summary = asyncio.run(run_demo(offline=args.offline, skip_minimax=args.skip_minimax))
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    elif args.command == "verify":
        print(json.dumps(verify_modification(), ensure_ascii=False, indent=2))
    elif args.command == "reset":
        target = config.data_dir()
        if target.exists():
            shutil.rmtree(target)
        print(f"removed {target} (backend={known})")
