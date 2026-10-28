"""SQLite 离线回退后端：Windows / macOS / 无 seekdb 环境也能完整跑通。

向量检索用 numpy 全量点积（文档量级是个人文献库，几百到几万片段足够）；
全文检索用自行实现的 BM25（中文按字 + 二元组切词，英文按单词），
不依赖 FTS5 的分词器，因此在任何 SQLite 版本上行为一致。
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import Counter
from pathlib import Path

import numpy as np

from ..library import Chunk, Document
from .base import Filters, RawHit, StoredChunk, _chunk_metadata, doc_row, now_iso

_WORD_RE = re.compile(r"[a-z0-9_]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    text = (text or "").lower()
    tokens = _WORD_RE.findall(text)
    chars = _CJK_RE.findall(text)
    tokens.extend(chars)
    tokens.extend(a + b for a, b in zip(chars, chars[1:]))
    return tokens


class SQLiteStore:
    name = "sqlite"

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS docs (
                doc_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                kind TEXT NOT NULL,
                path TEXT NOT NULL,
                sha1 TEXT NOT NULL,
                abstract TEXT,
                tags TEXT,
                year INTEGER,
                n_chunks INTEGER,
                imported_at TEXT
            );
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                doc_id TEXT NOT NULL,
                idx INTEGER NOT NULL,
                section TEXT,
                page INTEGER,
                text TEXT NOT NULL,
                chars INTEGER,
                title TEXT,
                kind TEXT,
                tags TEXT,
                year INTEGER,
                embedding BLOB
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
            """
        )
        self._conn.commit()

    # -- 写入 ---------------------------------------------------------
    def upsert_document(self, document: Document, vectors: np.ndarray) -> None:
        row = doc_row(document)
        with self._conn:
            self._conn.execute("DELETE FROM chunks WHERE doc_id = ?", (document.doc_id,))
            self._conn.execute(
                """
                INSERT INTO docs (doc_id, title, kind, path, sha1, abstract, tags, year, n_chunks, imported_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(doc_id) DO UPDATE SET
                    title=excluded.title, kind=excluded.kind, path=excluded.path, sha1=excluded.sha1,
                    abstract=excluded.abstract, tags=excluded.tags, year=excluded.year,
                    n_chunks=excluded.n_chunks, imported_at=excluded.imported_at
                """,
                (
                    row["doc_id"],
                    row["title"],
                    row["kind"],
                    row["path"],
                    row["sha1"],
                    row["abstract"],
                    ",".join(row["tags"]),
                    row["year"],
                    row["n_chunks"],
                    row["imported_at"],
                ),
            )
            payload = []
            for chunk, vector in zip(document.chunks, vectors):
                meta = _chunk_metadata(document, chunk)
                payload.append(
                    (
                        chunk.chunk_id,
                        chunk.doc_id,
                        chunk.index,
                        chunk.section,
                        chunk.page or 0,
                        chunk.text,
                        chunk.chars,
                        meta["title"],
                        meta["kind"],
                        meta["tags"],
                        meta["year"],
                        vector.astype(np.float32).tobytes(),
                    )
                )
            self._conn.executemany(
                """
                INSERT OR REPLACE INTO chunks
                    (chunk_id, doc_id, idx, section, page, text, chars, title, kind, tags, year, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )

    def delete_document(self, doc_id: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            self._conn.execute("DELETE FROM docs WHERE doc_id = ?", (doc_id,))

    # -- 读取 ---------------------------------------------------------
    def list_documents(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM docs ORDER BY year DESC, doc_id").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["tags"] = [t for t in (item.get("tags") or "").split(",") if t]
            result.append(item)
        return result

    def _rows(self, filters: Filters) -> list[sqlite3.Row]:
        sql = "SELECT * FROM chunks"
        clauses: list[str] = []
        params: list[object] = []
        if filters.doc_ids:
            clauses.append(f"doc_id IN ({','.join('?' * len(filters.doc_ids))})")
            params.extend(filters.doc_ids)
        if filters.kind:
            clauses.append("kind = ?")
            params.append(filters.kind)
        if filters.year_min is not None:
            clauses.append("year >= ?")
            params.append(filters.year_min)
        if filters.year_max is not None:
            clauses.append("year <= ?")
            params.append(filters.year_max)
        if filters.tags:
            clauses.append("(" + " OR ".join("tags LIKE ?" for _ in filters.tags) + ")")
            params.extend(f"%{tag}%" for tag in filters.tags)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        return self._conn.execute(sql, params).fetchall()

    def vector_search(self, vector: np.ndarray, top_k: int, filters: Filters) -> list[RawHit]:
        rows = self._rows(filters)
        if not rows:
            return []
        vectors = []
        ids = []
        for row in rows:
            if row["embedding"] is None:
                continue
            vectors.append(np.frombuffer(row["embedding"], dtype=np.float32))
            ids.append(row["chunk_id"])
        if not vectors:
            return []
        matrix = np.stack(vectors)
        query = np.asarray(vector, dtype=np.float32).reshape(-1)
        scores = matrix @ query
        order = np.argsort(-scores)[: max(top_k, 1)]
        return [RawHit(chunk_id=ids[i], score=float(scores[i]), rank=rank) for rank, i in enumerate(order)]

    def fulltext_search(self, query: str, top_k: int, filters: Filters) -> list[RawHit]:
        rows = self._rows(filters)
        if not rows:
            return []
        terms = tokenize(query)
        if not terms:
            return []
        unique_terms = list(dict.fromkeys(terms))
        docs_tokens = [Counter(tokenize(row["text"])) for row in rows]
        doc_freq = {term: sum(1 for counter in docs_tokens if term in counter) for term in unique_terms}
        n_docs = len(rows)
        avg_len = sum(sum(counter.values()) for counter in docs_tokens) / max(n_docs, 1)
        k1, b = 1.5, 0.75
        scored: list[tuple[str, float]] = []
        for row, counter in zip(rows, docs_tokens):
            length = sum(counter.values()) or 1
            score = 0.0
            for term in unique_terms:
                freq = counter.get(term, 0)
                if not freq:
                    continue
                idf = math.log(1 + (n_docs - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
                score += idf * (freq * (k1 + 1)) / (freq + k1 * (1 - b + b * length / avg_len))
            if score > 0:
                scored.append((row["chunk_id"], score))
        scored.sort(key=lambda item: -item[1])
        return [
            RawHit(chunk_id=chunk_id, score=float(score), rank=rank)
            for rank, (chunk_id, score) in enumerate(scored[: max(top_k, 1)])
        ]

    def get_chunks(self, chunk_ids: list[str]) -> list[StoredChunk]:
        if not chunk_ids:
            return []
        rows = self._conn.execute(
            f"SELECT * FROM chunks WHERE chunk_id IN ({','.join('?' * len(chunk_ids))})",
            chunk_ids,
        ).fetchall()
        index = {row["chunk_id"]: row for row in rows}
        output = []
        for chunk_id in chunk_ids:
            row = index.get(chunk_id)
            if row is None:
                continue
            output.append(
                StoredChunk(
                    chunk_id=row["chunk_id"],
                    doc_id=row["doc_id"],
                    text=row["text"],
                    section=row["section"] or "",
                    page=row["page"] or None,
                    metadata={
                        "title": row["title"],
                        "kind": row["kind"],
                        "tags": [t for t in (row["tags"] or "").split(",") if t],
                        "year": row["year"] or None,
                        "index": row["idx"],
                    },
                )
            )
        return output

    def stats(self) -> dict:
        docs = self._conn.execute("SELECT COUNT(*) AS n FROM docs").fetchone()["n"]
        chunks = self._conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
        chars = self._conn.execute("SELECT COALESCE(SUM(chars), 0) AS n FROM chunks").fetchone()["n"]
        terms = self._conn.execute("SELECT abstract FROM docs").fetchall()
        return {
            "backend": self.name,
            "documents": docs,
            "chunks": chunks,
            "total_chars": chars,
            "path": str(self.path),
            "abstract_preview": sum(len(row["abstract"] or "") for row in terms),
            "checked_at": now_iso(),
        }

    def reset(self) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM chunks")
            self._conn.execute("DELETE FROM docs")

    def close(self) -> None:
        self._conn.close()

    def dump_document(self, doc_id: str) -> dict:
        row = self._conn.execute("SELECT * FROM docs WHERE doc_id = ?", (doc_id,)).fetchone()
        if row is None:
            return {}
        item = dict(row)
        item["chunks"] = [
            dict(chunk)
            for chunk in self._conn.execute(
                "SELECT chunk_id, idx, section, page, chars FROM chunks WHERE doc_id = ? ORDER BY idx",
                (doc_id,),
            ).fetchall()
        ]
        return item
