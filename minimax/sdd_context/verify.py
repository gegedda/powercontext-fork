"""Prove that the same tests fail before the change and pass after it."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import config

TARGET = "tests/test_issue_filters.py"
REGRESSION = "tests/test_regressions.py"


def _run(cwd: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(cwd)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args, "-q"],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def _counts(output: str) -> dict[str, int]:
    counts = {"passed": 0, "failed": 0}
    for key in counts:
        match = re.search(rf"(\d+) {key}", output)
        if match:
            counts[key] = int(match.group(1))
    return counts


def _log(name: str, result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    config.ensure_dirs()
    (config.RECORDS_DIR / name).write_text(result.stdout + result.stderr, encoding="utf-8")
    return {
        "command": "python -m pytest " + " ".join(result.args[3:]),
        "exit_code": result.returncode,
        **_counts(result.stdout + result.stderr),
    }


def verify_modification() -> dict[str, object]:
    """Run target + regression tests against the frozen before snapshot and the current tree."""

    work = Path(tempfile.mkdtemp(prefix="issuehub-verify-"))
    try:
        shutil.copytree(config.DEMO_DIR, work / "demo", ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        project = work / "demo"
        before = config.DEMO_DIR / "snapshots" / "before" / "issuehub"
        for source in sorted(before.glob("*.py")):
            shutil.copy2(source, project / "issuehub" / source.name)

        before_target = _run(project, [TARGET])
        before_regression = _run(project, [REGRESSION])

        for source in sorted((config.DEMO_DIR / "issuehub").glob("*.py")):
            shutil.copy2(source, project / "issuehub" / source.name)

        after_target = _run(project, [TARGET])
        after_regression = _run(project, [REGRESSION])

        result = {
            "before": {
                "target": _log("before_target.log", before_target),
                "regression": _log("before_regression.log", before_regression),
            },
            "after": {
                "target": _log("after_target.log", after_target),
                "regression": _log("after_regression.log", after_regression),
            },
            "passed": before_target.returncode != 0
            and before_regression.returncode == 0
            and after_target.returncode == 0
            and after_regression.returncode == 0,
        }
        config.ensure_dirs()
        (config.RECORDS_DIR / "test_results.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)
