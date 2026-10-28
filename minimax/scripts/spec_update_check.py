"""Prove that re-importing a changed spec changes the selected context.

This runs the real CLI twice in isolated copies: once with the repository specs
and once after appending a new requirement to SPEC-102.  It is intentionally a
subprocess check so the two runs cannot share an in-process cache.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

MINIMAX = Path(__file__).resolve().parents[1]
REPO = MINIMAX.parent
MARKER = "SPEC-102.9 Runtime refresh proof: the selector must use this newly imported sentence."


def _copy_tree(root: Path, *, append: bool) -> None:
    shutil.copytree(MINIMAX / "materials", root / "materials")
    shutil.copytree(MINIMAX / "demo_project", root / "demo_project", ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    if append:
        spec = root / "materials" / "specs" / "SPEC-102-invalid-priority.md"
        spec.write_text(
            spec.read_text(encoding="utf-8")
            + "\n## SPEC-102.9 Runtime refresh proof\n"
            + MARKER
            + "\n",
            encoding="utf-8",
        )


def _run(root: Path) -> dict[str, object]:
    env = dict(os.environ)
    env.update(
        {
            "SDD_REPO_ROOT": str(root),
            "SDD_MATERIALS_DIR": str(root / "materials"),
            "SDD_DEMO_DIR": str(root / "demo_project"),
            "SDD_DATA_DIR": str(root / ".sdd"),
            "SDD_DB": "sqlite",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    def invoke(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "sdd_context", "--db", "sqlite", *args],
            cwd=MINIMAX,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,
            check=True,
        )

    invoke("ingest")
    completed = invoke("context", "--format", "json")
    return json.loads(completed.stdout)


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="sdd-spec-update-"))
    try:
        baseline_root = work / "baseline"
        updated_root = work / "updated"
        _copy_tree(baseline_root, append=False)
        _copy_tree(updated_root, append=True)

        baseline = _run(baseline_root)
        updated = _run(updated_root)
        baseline_ids = {item["material_id"] for item in baseline["specs"]}
        updated_ids = {item["material_id"] for item in updated["specs"]}
        updated_text = "\n".join(str(item["text"]) for item in updated["specs"])
        result = {
            "baseline_has_new_section": "SPEC-102.9" in baseline_ids,
            "updated_has_new_section": "SPEC-102.9" in updated_ids,
            "updated_text_has_marker": MARKER in updated_text,
            "baseline_specs": sorted(baseline_ids),
            "updated_specs": sorted(updated_ids),
            "passed": "SPEC-102.9" not in baseline_ids and "SPEC-102.9" in updated_ids and MARKER in updated_text,
        }
        records = MINIMAX / "records"
        records.mkdir(exist_ok=True)
        (records / "spec_update_proof.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["passed"]:
            raise SystemExit(1)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        records = MINIMAX / "records"
        records.mkdir(exist_ok=True)
        (records / "spec_update_error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
