"""PowerContext-backed persistence for materials and task state.

The module supports both the 1.2 Memory model (entry citations + revise) and
the 1.4 atomic-memory model (artifact records, append-only collection).  The
difference is isolated here so selection and the CLI do not branch on versions.
"""

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
class MemoryItem:
    text: str
    kind: str
    ref: str
    version: str
    revision: int
    citation: object | None = None


@dataclass(slots=True)
class SearchHit:
    material_id: str
    text: str
    score: float


@dataclass(slots=True)
class UpsertStats:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0

    def as_dict(self) -> dict[str, int]:
        return {"inserted": self.inserted, "updated": self.updated, "unchanged": self.unchanged}


def _to_item(raw: object) -> MemoryItem | None:
    text = getattr(raw, "text", None)
    if not isinstance(text, str):
        return None
    kind = str(getattr(raw, "kind", ""))
    citation = getattr(raw, "citation", None)
    if citation is not None:
        return MemoryItem(
            text=text,
            kind=kind,
            ref=str(getattr(citation, "entry_id", "")),
            version=str(getattr(citation, "entry_version_id", "")),
            revision=int(getattr(raw, "version", 0) or 0),
            citation=citation,
        )
    artifact = getattr(raw, "artifact", None)
    ref = str(getattr(artifact, "artifact_id", "")) if artifact is not None else ""
    artifact_revision = int(getattr(artifact, "revision", 0) or 0)
    state_version = int(getattr(raw, "state_version", 0) or 0)
    revision = max(artifact_revision, state_version)
    return MemoryItem(
        text=text,
        kind=kind,
        ref=ref,
        version=f"{ref}@{revision}",
        revision=revision,
        citation=None,
    )


class MaterialStore:
    def __init__(self, client: PowerContextClient, scope_id: str) -> None:
        self.client = client
        self.scope_id = scope_id

    async def entries(self) -> list[MemoryItem]:
        fields = set(ListMemoryEntriesRequest.model_fields)
        cursor: str | None = None
        items: list[MemoryItem] = []
        while True:
            kwargs: dict[str, object] = {"scope_id": self.scope_id, "include_inactive": False}
            if "limit" in fields:
                kwargs["limit"] = 50
            if cursor is not None and "cursor" in fields:
                kwargs["cursor"] = cursor
            response = await self.client.list_memory_entries(ListMemoryEntriesRequest(**kwargs))
            for raw in response.entries:
                item = _to_item(raw)
                if item is not None:
                    items.append(item)
            cursor = getattr(response, "next_cursor", None)
            if not cursor or "cursor" not in fields:
                break
        return items

    def latest_by_material(self, items: list[MemoryItem]) -> dict[str, MemoryItem]:
        """Pick the last/highest-revision record for each material id.

        PowerContext 1.4 stores atomic memories append-only, so a re-import
        creates a newer record while the old one remains in the collection.
        """

        latest: dict[str, MemoryItem] = {}
        for item in items:
            material_id = self.material_id(item.text)
            if not material_id:
                continue
            current = latest.get(material_id)
            if current is None or item.revision >= current.revision:
                latest[material_id] = item
        return latest

    async def search(self, query: str, limit: int = 30) -> list[SearchHit]:
        try:
            response = await self.client.search_memory(
                SearchMemoryRequest(scope_id=self.scope_id, query=query, limit=limit)
            )
        except Exception:
            return []
        hits: list[SearchHit] = []
        for raw in getattr(response, "hits", []):
            text = getattr(raw, "text", None)
            if isinstance(text, str):
                hits.append(SearchHit(self.material_id(text), text, float(getattr(raw, "score", 0.0))))
                continue
            memory = getattr(raw, "memory", None)
            memory_text = getattr(memory, "text", None)
            if isinstance(memory_text, str):
                hits.append(SearchHit(self.material_id(memory_text), memory_text, float(getattr(raw, "score", 0.0))))
        return hits

    async def upsert(self, materials: list[Material]) -> UpsertStats:
        stats = UpsertStats()
        existing = self.latest_by_material(await self.entries())
        for material in materials:
            current = existing.get(material.material_id)
            if current is None:
                await self._remember(material, reason=f"ingest {material.material_id}")
                stats.inserted += 1
                continue
            if current.text == material.text:
                stats.unchanged += 1
                continue
            if current.citation is not None:
                # PowerContext 1.2 exposes per-entry revisions.
                await self._revise(current, material)
                stats.updated += 1
                continue
            # PowerContext 1.4 is append-only; the newer atomic record wins in
            # latest_by_material on the next read.
            await self._remember(material, reason=f"re-ingest {material.material_id}")
            stats.updated += 1
        return stats

    async def _remember(self, material: Material, *, reason: str) -> None:
        await self.client.remember_memory(
            RememberMemoryRequest(
                scope_id=self.scope_id,
                kind=material.kind,
                text=material.text,
                reason=reason,
            )
        )

    async def _revise(self, current: MemoryItem, material: Material) -> None:
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
            fresh = self.latest_by_material(await self.entries())
            entry = fresh.get(material.material_id)
            if entry is None or entry.citation is None:
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
        latest = self.latest_by_material(await self.entries())
        item = latest.get(TASK_STATE_ID)
        if item is None:
            for candidate in await self.entries():
                meta = parse_entry_text(candidate.text)
                if meta.get("material") == TASK_STATE_ID:
                    item = candidate
                    break
        if item is None:
            return None
        try:
            return json.loads(str(parse_entry_text(item.text).get("body", "{}")))
        except json.JSONDecodeError:
            return None
