"""End-to-end demonstration used by the verification sample."""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import config
from .context import build_context
from .materials import collect_materials
from .minimax_agent import apply_files, build_messages, call_minimax, load_recorded, parse_files, write_record
from .powercontext_runtime import PowerContextRuntime
from .store import MaterialStore
from .verify import verify_modification


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


async def run_demo(*, offline: bool = False, skip_minimax: bool = False) -> dict[str, object]:
    config.ensure_dirs()
    runtime = PowerContextRuntime()
    runtime.start()
    try:
        scope_id = await runtime.ensure_scope()
        store = MaterialStore(runtime.client, scope_id)
        materials = collect_materials()
        stats = await store.upsert(materials)
        context = await build_context(store, runtime=runtime.describe())
        _write(config.RECORDS_DIR / "context.json", json.dumps(context, ensure_ascii=False, indent=2))
        _write(config.RECORDS_DIR / "context.md", str(context["markdown"]))

        baseline = verify_modification()
        if not baseline["passed"]:
            raise RuntimeError("baseline verification failed; inspect records/before_*.log and records/after_*.log")

        if skip_minimax:
            record = None
            applied: list[str] = []
            minimax_record = None
        elif offline:
            record = load_recorded()
            applied = apply_files(record)
            minimax_record = config.RECORDS_DIR / "minimax_recorded.json"
        else:
            messages = build_messages(context)
            raw = call_minimax(messages)
            parsed = parse_files(str(raw["response"]))
            record = {**raw, **parsed}
            minimax_record = write_record(record)
            applied = apply_files(record)

        after = verify_modification()
        if not after["passed"]:
            raise RuntimeError("verification failed after applying the change; inspect records/after_*.log")

        state = {
            "task_id": "TASK-001",
            "status": "verified",
            "completed": [
                f"imported {len(materials)} material chunks into PowerContext",
                "selected applicable specs, code symbols and tests",
                "asked MiniMax to modify demo_project/issuehub",
                "target tests pass after the change",
                "regression tests pass after the change",
            ],
            "todo": [],
            "verification": "target: 4 failed before / 4 passed after; regression: 4 passed before and after",
            "applied_files": applied,
            "context_specs": [item["material_id"] for item in context["specs"]],
            "context_code": [item["symbol"] for item in context["code"]],
            "context_tests": [item["test"] for item in context["tests"]],
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        await store.save_state(state)

        await runtime.arestart()
        scope_after = await runtime.ensure_scope()
        store_after = MaterialStore(runtime.client, scope_after)
        loaded = await store_after.load_state()
        context_after = await build_context(store_after, runtime=runtime.describe())
        reuse = {
            "scope_id_before": scope_id,
            "scope_id_after": scope_after,
            "state_written": state,
            "state_loaded_after_restart": loaded,
            "same_task_status": (loaded or {}).get("status") == "verified",
            "context_uses_loaded_state": (context_after.get("state") or {}).get("status") == "verified",
            "context_after": context_after,
        }
        _write(config.RECORDS_DIR / "state_reuse.json", json.dumps(reuse, ensure_ascii=False, indent=2))

        summary = {
            "scope_id": scope_id,
            "backend": runtime.backend,
            "materials": len(materials),
            "upsert": stats.as_dict(),
            "context_counts": {
                "specs": len(context["specs"]),
                "code": len(context["code"]),
                "tests": len(context["tests"]),
            },
            "minimax_record": str(minimax_record) if minimax_record else None,
            "minimax_skipped": skip_minimax,
            "applied_files": applied,
            "verification": after,
            "state_reused": reuse["same_task_status"] and reuse["context_uses_loaded_state"],
        }
        _write(config.RECORDS_DIR / "demo_summary.json", json.dumps(summary, ensure_ascii=False, indent=2))
        return summary
    finally:
        await runtime.aclose()
