"""Regenerate the reviewer-facing diff and evidence summaries from current records."""

from __future__ import annotations

import difflib
import json
import shutil
from pathlib import Path

MINIMAX = Path(__file__).resolve().parents[1]
BEFORE = MINIMAX / "demo_project" / "snapshots" / "before" / "issuehub"
AFTER = MINIMAX / "demo_project" / "issuehub"
RECORDS = MINIMAX / "records"
RECORDS.mkdir(exist_ok=True)


def write_diff() -> None:
    chunks: list[str] = []
    for name in ("service.py", "api.py"):
        before = (BEFORE / name).read_text(encoding="utf-8").splitlines(keepends=True)
        after = (AFTER / name).read_text(encoding="utf-8").splitlines(keepends=True)
        chunks.extend(
            difflib.unified_diff(
                before,
                after,
                fromfile=f"demo_project/snapshots/before/issuehub/{name}",
                tofile=f"demo_project/issuehub/{name}",
            )
        )
    (RECORDS / "code.diff").write_text("".join(chunks), encoding="utf-8")
    for name in ("service.py", "api.py"):
        target = MINIMAX / "demo_project" / "snapshots" / "after" / "issuehub"
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(AFTER / name, target / name)


def write_summaries() -> None:
    results = json.loads((RECORDS / "test_results.json").read_text(encoding="utf-8"))
    lines = [
        "# Test results",
        "",
        "| phase | suite | exit | passed | failed | log |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for phase in ("before", "after"):
        for suite in ("target", "regression"):
            item = results[phase][suite]
            lines.append(
                f"| {phase} | {suite} | {item['exit_code']} | {item['passed']} | "
                f"{item['failed']} | `records/{phase}_{suite}.log` |"
            )
    lines += [
        "",
        "The same files and the same assertions are used in both phases. "
        "The only difference is the code under `demo_project/issuehub/`.",
    ]
    (RECORDS / "test_results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if (RECORDS / "state_reuse.json").is_file():
        state = json.loads((RECORDS / "state_reuse.json").read_text(encoding="utf-8"))
        lines = [
            "# PowerContext state reuse",
            "",
            f"- scope before restart: `{state['scope_id_before']}`",
            f"- scope after restart: `{state['scope_id_after']}`",
            f"- status loaded after restart: `{state['state_loaded_after_restart']['status']}`",
            f"- context uses loaded state: `{state['context_uses_loaded_state']}`",
            "",
            "The state entry is a PowerContext Memory (`kind=task-state`, material id "
            "`TASK-001-STATE`). The restart is a full Server stop/start against the same database.",
        ]
        (RECORDS / "powercontext_state.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    write_diff()
    write_summaries()
    print("wrote records/code.diff, snapshots/after, test_results.md, powercontext_state.md")
