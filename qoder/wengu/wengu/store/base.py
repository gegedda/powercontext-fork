"""知识库存储接口 + 两种实现（seekdb 为主，SQLite 为离线回退）。

两种后端都提供同一组操作：
- ``upsert_document`` / ``delete_document`` / ``list_documents``
- ``vector_search`` / ``fulltext_search`` / ``get_chunks`` / ``stats``

检索融合（RRF、薄弱点加权）在 :mod:`wengu.retrieval` 里做，后端只负责单路召回，
这样两套存储的排序语义完全一致，也可以单独验证任意一路。
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from ..library import Chunk, Document


@dataclass(slots=True)
class Filters:
    doc_ids: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    kind: str = ""
    year_min: int | None = None
    year_max: int | None = None

    def is_empty(self) -> bool:
        return not (self.doc_ids or self.tags or self.kind or self.year_min or self.year_max)

    def as_dict(self) -> dict:
        data = {
            "doc_ids": self.doc_ids,
            "tags": self.tags,
            "kind": self.kind,
            "year_min": self.year_min,
            "year_max": self.year_max,
        }
        return {k: v for k, v in data.items() if v not in (None, "", [])}


@dataclass(slots=True)
class RawHit:
    chunk_id: str
    score: float
    rank: int


@dataclass(slots=True)
class StoredChunk:
    chunk_id: str
    doc_id: str
    text: str
    section: str
    page: int | None
    metadata: dict


class KnowledgeStore(Protocol):
    name: str

    def upsert_document(self, document: Document, vectors: np.ndarray) -> None: ...

    def delete_document(self, doc_id: str) -> None: ...

    def list_documents(self) -> list[dict]: ...

    def vector_search(self, vector: np.ndarray, top_k: int, filters: Filters) -> list[RawHit]: ...

    def fulltext_search(self, query: str, top_k: int, filters: Filters) -> list[RawHit]: ...

    def get_chunks(self, chunk_ids: list[str]) -> list[StoredChunk]: ...

    def stats(self) -> dict: ...

    def reset(self) -> None: ...


def now_iso() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def doc_row(document: Document) -> dict:
    return {
        "doc_id": document.doc_id,
        "title": document.title,
        "kind": document.kind,
        "path": document.path,
        "sha1": document.sha1,
        "abstract": document.abstract,
        "tags": list(document.tags),
        "year": document.year,
        "n_chunks": document.n_chunks,
        "imported_at": now_iso(),
    }


def _chunk_metadata(document: Document, chunk: Chunk) -> dict:
    return {
        "doc_id": document.doc_id,
        "title": document.title,
        "kind": document.kind,
        "section": chunk.section,
        "page": chunk.page if chunk.page is not None else 0,
        "index": chunk.index,
        "tags": ",".join(document.tags),
        "year": document.year if document.year is not None else 0,
        "chars": chunk.chars,
    }
