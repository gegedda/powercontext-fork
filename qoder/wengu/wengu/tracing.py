"""技术证据记录：把每次 seekdb 查询与 PowerContext 记忆读写留痕。

界面上的「技术证据」面板、``wengu demo`` 产出的 records 都来自这里，
评审可以直接看到「哪条 SQL/查询、什么参数、命中什么、耗时多少」。
"""

from __future__ import annotations

import datetime as _dt
import threading
from collections import deque


def _now() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="milliseconds")


class Tracer:
    def __init__(self, limit: int = 60) -> None:
        self._events: deque[dict] = deque(maxlen=max(limit, 10))
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}

    def record(self, kind: str, payload: dict | None = None) -> None:
        with self._lock:
            self._counters[kind] = self._counters.get(kind, 0) + 1
            event = {**(payload or {}), "ts": _now(), "kind": kind, "seq": sum(self._counters.values())}
            self._events.append(event)

    def recent(self, limit: int = 20, kind_prefix: str = "") -> list[dict]:
        with self._lock:
            events = list(self._events)
        if kind_prefix:
            events = [e for e in events if e["kind"].startswith(kind_prefix)]
        return list(reversed(events))[:limit]

    def counters(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counters)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._counters.clear()


TRACER = Tracer()
