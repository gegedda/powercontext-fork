"""存储后端选择。"""

from __future__ import annotations

from pathlib import Path

from ..tracing import TRACER
from .base import Filters, KnowledgeStore, RawHit, StoredChunk  # noqa: F401 - 对外导出
from .sqlite_backend import SQLiteStore


def _seekdb_available() -> tuple[bool, str]:
    try:
        import pyseekdb  # noqa: F401
        import pylibseekdb  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return False, f"pyseekdb/pylibseekdb 不可用：{exc}"
    return True, ""


def build_store(settings, dimension: int) -> tuple[KnowledgeStore, dict]:
    """按配置选择后端；auto 在 seekdb 可用时优先 seekdb。"""

    requested = settings.store
    attempts: list[str] = []
    if requested == "auto":
        candidates = ["seekdb", "sqlite"]
    elif requested in {"seekdb", "sqlite"}:
        candidates = [requested]
    else:
        candidates = ["sqlite"]

    for candidate in candidates:
        if candidate == "seekdb":
            available, reason = _seekdb_available()
            if not available:
                attempts.append(reason)
                if requested == "seekdb":
                    raise RuntimeError(f"WENGU_STORE=seekdb，但 {reason}")
                continue
            try:
                from .seekdb_backend import SeekDBStore

                store = SeekDBStore(Path(settings.seekdb_path), dimension=dimension)
                info = store.stats()
                info["attempts"] = attempts
                TRACER.record("seekdb.open", {"path": str(settings.seekdb_path), "collections": info["collections"]})
                return store, info
            except Exception as exc:  # noqa: BLE001
                attempts.append(f"seekdb 初始化失败：{exc}")
                if requested == "seekdb":
                    raise RuntimeError(
                        "seekdb 打开失败：同一个 WENGU_DATA_DIR 下的嵌入式 seekdb 同一时间只能被一个进程打开"
                        f"（先停掉 Web 服务再跑 CLI，或换一个 WENGU_DATA_DIR）。原始错误：{exc}"
                    ) from exc
                continue
        store = SQLiteStore(Path(settings.sqlite_path))
        info = store.stats()
        info["attempts"] = attempts
        info["mode"] = "embedded"
        TRACER.record("sqlite.open", {"path": str(settings.sqlite_path)})
        return store, info
    raise RuntimeError("没有可用的存储后端")
