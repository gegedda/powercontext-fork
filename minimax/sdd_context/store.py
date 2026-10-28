"""PowerContext-backed persistence for materials and task state."""

from __future__ import annotations

import json
from dataclasses import dataclass

from powercontext.client import PowerContextClient
from powercontext.http import (
    ListMemoryEntriesRequest,
    RememberMemoryRequest,
    ReviseMemoryEntryRequest,
    SearchMemoryRequest,
)

from .materials import Material, parse_entry_text

TASK_STATE_ID = "TASK-001-STATE"


@dataclass(slots=True)
class UpsertStats:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0

    def as_dict(self) -> dict[str, int]:
        return {"inserted": self.inserted, "updated": self.updated, "unchanged": self.unchanged}


class MaterialStore:
    def __init__(self, client: PowerContextClient, scope_id: str) -> None:
        self.client = client
        self.scope_id = scope_id

    async def entries(self):
        response = await self.client.list_memory_entries(
            ListMemoryEntriesRequest(scope_id=self.scope_id, include_inactive=False)
        )
        return list(response.entries)

    async def search(self, query: str, limit: int = 30):
        try:
            response = await self.client.search_memory(
                SearchMemoryRequest(scope_id=self.scope_id, query=query, limit=limit)
            )
        except Exception:
            return []
        return list(response.hits)

    async def upsert(self, materials: list[Material]) -> UpsertStats:
        stats = UpsertStats()
        existing = {self.material_id(entry.text): entry for entry in await self.entries()}
        for material in materials:
            current = existing.get(material.material_id)
            if current is None:
                await self.client.remember_memory(
                    RememberMemoryRequest(
                        scope_id=self.scope_id,
                        kind=material.kind,
                        text=material.text,
                        reason=f"ingest {material.material_id}",
                    )
                )
                stats.inserted += 1
                continue
            if current.text == material.text:
                stats.unchanged += 1
                continue
            # Revising an entry advances the Memory artifact revision, so every
            # update must resolve a citation from the current head first.
            fresh = {self.material_id(entry.text): entry for entry in await self.entries()}
            entry = fresh.get(material.material_id)
            if entry is None:
                await self.client.remember_memory(
                    RememberMemoryRequest(
                        scope_id=self.scope_id,
                        kind=material.kind,
                        text=material.text,
                        reason=f"re-ingest {material.material_id}",
                    )
                )
                stats.inserted += 1
                continue
            await self._revise(entry, material)
            stats.updated += 1
        return stats

    async def _revise(self, current, material: Material) -> None:
        try:
            await self.client.revise_memory_entry(
                ReviseMemoryEntryRequest(
                    scope_id=self.scope_id,
                    citation=current.citation,
                    kind=material.kind,
                    text=material.text,
                    reason=f"update {material.material_id}",
                )
            )
        except Exception:
            # A concurrent ingest may have moved the entry; resolve the exact
            # material id again and retry once with the fresh citation.
            fresh = {self.material_id(entry.text): entry for entry in await self.entries()}
            entry = fresh.get(material.material_id)
            if entry is None:
                raise
            await self.client.revise_memory_entry(
                ReviseMemoryEntryRequest(
                    scope_id=self.scope_id,
                    citation=entry.citation,
                    kind=material.kind,
                    text=material.text,
                    reason=f"update {material.material_id}",
                )
            )

    @staticmethod
    def material_id(text: str) -> str:
        meta = parse_entry_text(text)
        return str(meta.get("material", "")) or str(meta.get("material_id", ""))

    async def save_state(self, state: dict[str, object]) -> None:
        material = Material(
            material_id=TASK_STATE_ID,
            kind="task-state",
            title="TASK-001 persisted state",
            path="records/task_state.json",
            tags=("state", "task"),
            body=json.dumps(state, ensure_ascii=False, indent=2),
        )
        await self.upsert([material])

    async def load_state(self) -> dict[str, object] | None:
        for entry in await self.entries():
            meta = parse_entry_text(entry.text)
            if meta.get("material") == TASK_STATE_ID:
                try:
                    return json.loads(str(meta.get("body", "{}")))
                except json.JSONDecodeError:
                    return None
        return None
