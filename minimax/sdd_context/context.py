"""Assemble the development context returned to the coding agent."""

from __future__ import annotations

from .materials import task_text
from .select import render_markdown, select, sources
from .store import MaterialStore


async def build_context(store: MaterialStore, *, runtime: dict[str, object], task_id: str = "TASK-001") -> dict[str, object]:
    text = task_text()
    title = "Add priority and assignee filters to the issue list"
    for line in text.splitlines():
        if line.lower().startswith("title:"):
            title = line.split(":", 1)[1].strip()
            break
    entries = await store.entries()
    hits = await store.search(text, limit=40)
    selected = select(entries, hits, text)
    context: dict[str, object] = {
        "task": {"id": task_id, "title": title, "text": text},
        "runtime": runtime,
        "scope_id": store.scope_id,
        "specs": selected["specs"],
        "code": selected["code"],
        "tests": selected["tests"],
        "selection": selected["selection"],
        "state": await store.load_state(),
    }
    context["sources"] = sources(context, entries)
    context["markdown"] = render_markdown(context)
    return context
