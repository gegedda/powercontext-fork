"""Locations and runtime switches for the SDD context module."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
MINIMAX_ROOT = PACKAGE_ROOT.parent
REPO_ROOT = Path(os.environ.get("SDD_REPO_ROOT", MINIMAX_ROOT.parent)).expanduser().resolve()
MATERIALS_DIR = Path(
    os.environ.get("SDD_MATERIALS_DIR", REPO_ROOT / "materials" if os.environ.get("SDD_REPO_ROOT") else MINIMAX_ROOT / "materials")
).expanduser().resolve()
DEMO_DIR = Path(
    os.environ.get("SDD_DEMO_DIR", REPO_ROOT / "demo_project" if os.environ.get("SDD_REPO_ROOT") else MINIMAX_ROOT / "demo_project")
).expanduser().resolve()
RECORDS_DIR = MINIMAX_ROOT / "records"
DOCS_DIR = MINIMAX_ROOT / "docs"


def load_env_file() -> None:
    """Load ``minimax/.env`` without overriding an already exported variable."""

    path = MINIMAX_ROOT / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_env_file()


def data_dir() -> Path:
    return Path(os.environ.get("SDD_DATA_DIR", MINIMAX_ROOT / ".sdd")).expanduser().resolve()


def _seekdb_available() -> bool:
    try:
        return importlib.util.find_spec("pylibseekdb") is not None
    except (ImportError, ValueError):
        return False


def database_backend() -> str:
    """Return ``seekdb`` or ``sqlite``.

    ``auto`` prefers embedded seekdb (the graded path) and falls back to SQLite
    on platforms where pylibseekdb is unavailable, such as Windows.
    """

    configured = os.environ.get("SDD_DB", "auto").strip().lower()
    if configured in {"seekdb", "sqlite"}:
        if configured == "seekdb" and not _seekdb_available():
            raise RuntimeError(
                "SDD_DB=seekdb requires pylibseekdb. Install powercontext[seekdb] on Linux or macOS, "
                "or use SDD_DB=sqlite for local development."
            )
        return configured
    if configured not in {"auto", ""}:
        raise RuntimeError("SDD_DB must be auto, seekdb or sqlite")
    return "seekdb" if _seekdb_available() else "sqlite"


def scope_key() -> str:
    return os.environ.get("SDD_SCOPE_KEY", "sdd-minimax-issuehub-v1")


def minimax_model() -> str:
    return os.environ.get("MINIMAX_MODEL", "MiniMax-M2.1")


def minimax_base_url() -> str:
    return os.environ.get("MINIMAX_BASE_URL", "https://api.minimaxi.com/v1/chat/completions")


def minimax_api_key() -> str | None:
    value = os.environ.get("MINIMAX_API_KEY", "").strip()
    return value or None


def ensure_dirs() -> None:
    for directory in (data_dir(), RECORDS_DIR, DOCS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
