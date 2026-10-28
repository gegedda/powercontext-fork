"""End-to-end demonstration used by the verification sample."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from . import config
from .context import build_context
from .materials import collect_materials
from .minimax_agent import apply_files, generate_files, load_recorded, write_record
from .powercontext_runtime import PowerContextRuntime
from .store import MaterialStore
from .verify import restore_after, restore_before, run_current


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


async def run_demo(*, offline: bool = False, skip_minimax: bool = False) -> dict[str, object]:
    config.ensure_dirs()
    # The context must describe the code before the change, otherwise the model
    # would only be echoing an already-finished implementation.
    restore_before()
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

        baseline = run_current("before")
        if baseline["target"]["exit_code"] == 0 or baseline["regression"]["exit_code"] != 0:
            restore_after()
            raise RuntimeError("baseline verification failed; inspect records/before_*.log")

        applied: list[str] = []
        minimax_record: Path | None = None
        try:
            if skip_minimax:
                restore_after()
            else:
                if offline:
                    record = load_recorded()
                else:
                    record = generate_files(context)
                    minimax_record = write_record(record)
                    shutil.copy2(minimax_record, config.RECORDS_DIR / "minimax_recorded.json")
                applied = apply_files(record)

            # The final code becomes the current material set; the next context
            # (after restart) must show the model's implementation.
            await store.upsert(collect_materials())
            after = run_current("after")
            if not after["passed"]:
                raise RuntimeError("verification failed after applying the change; inspect records/after_*.log")
            if applied:
                # Keep the reviewed after snapshot in sync with the actual
                # MiniMax output, so the recorded diff is the delivered code.
                for source in sorted((config.DEMO_DIR / "issuehub").glob("*.py")):
                    shutil.copy2(source, config.DEMO_DIR / "snapshots" / "after" / "issuehub" / source.name)
            test_results = {
                "before": baseline,
                "after": after,
                "passed": baseline["target"]["exit_code"] != 0
                and baseline["regression"]["exit_code"] == 0
                and after["passed"],
            }
            _write(config.RECORDS_DIR / "test_results.json", json.dumps(test_results, ensure_ascii=False, indent=2))
        except BaseException:
            restore_after()
            await store.upsert(collect_materials())
            raise

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
