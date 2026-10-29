"""seekdb 后端：嵌入式（默认）或远端 Server，向量 + 全文 + 标量过滤都在数据库里做。

要点：
- 集合用 ``Schema`` 建：HNSW 向量索引（cosine）+ FulltextIndexConfig(analyzer="ik") 中文全文索引；
- 向量由应用侧显式提供（``embedding_function=None``），因此不依赖 seekdb 的默认模型；
- 全文检索走 ``hybrid_search`` 的 query 分支（不带 knn），由 seekdb 返回排序结果；
- 元数据过滤（doc_id / kind / year）下推为 ``where`` 条件，标签在检索层过滤。
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import numpy as np

from ..library import Document
from .base import Filters, RawHit, StoredChunk, _chunk_metadata, now_iso

DB_NAME = "wengu"
CHUNKS = "wengu_chunks"
DOCS = "wengu_docs"


def _sql_where(filters: Filters) -> dict | None:
    clauses: list[dict] = []
    if filters.doc_ids:
        clauses.append({"doc_id": {"$in": filters.doc_ids}})
    if filters.kind:
        clauses.append({"kind": {"$eq": filters.kind}})
    if filters.year_min is not None:
        clauses.append({"year": {"$gte": filters.year_min}})
    if filters.year_max is not None:
        clauses.append({"year": {"$lte": filters.year_max}})
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def _split_result(result: dict) -> list[dict]:
    """把 pyseekdb 的列式结果转成行列表。"""

    ids = (result.get("ids") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    documents = (result.get("documents") or [[]])[0]
    rows = []
    for position, chunk_id in enumerate(ids):
        rows.append(
            {
                "id": chunk_id,
                "distance": distances[position] if position < len(distances) else None,
                "metadata": metadatas[position] if position < len(metadatas) else {},
                "document": documents[position] if position < len(documents) else "",
            }
        )
    return rows


class SeekDBStore:
    name = "seekdb"

    def __init__(self, path: Path, dimension: int = 512) -> None:
        import pyseekdb

        self.pyseekdb = pyseekdb
        self.path = Path(path)
        self.dimension = int(dimension)
        self.path.mkdir(parents=True, exist_ok=True)
        self._collection_mode = ""
        self._ensure_database()
        self._client = pyseekdb.Client(path=str(self.path), database=DB_NAME)
        self._chunks = self._open_collection(CHUNKS)
        self._docs = self._open_collection(DOCS)

    # -- 建库建表 -----------------------------------------------------
    def _ensure_database(self) -> None:
        admin = self.pyseekdb.AdminClient(path=str(self.path))
        names = set()
        for database in admin.list_databases():
            names.add(getattr(database, "name", str(database)))
        if DB_NAME not in names:
            admin.create_database(DB_NAME)

    def _schema(self):
        py = self.pyseekdb
        return py.Schema(
            vector_index=py.VectorIndexConfig(
                hnsw=py.HNSWConfiguration(dimension=self.dimension, distance="cosine", M=16, ef_construction=200),
                embedding_function=None,
            ),
            fulltext_index=py.FulltextIndexConfig(analyzer="ik"),
        )

    def _open_collection(self, name: str):
        py = self.pyseekdb
        if self._client.has_collection(name):
            return self._client.get_collection(name)
        try:
            collection = self._client.create_collection(name, schema=self._schema())
            self._collection_mode = "schema"
            return collection
        except Exception:  # noqa: BLE001 - 老版本只有 deprecated 的 Configuration 入口
            configuration = py.Configuration(
                hnsw=py.HNSWConfiguration(dimension=self.dimension, distance="cosine"),
                fulltext_config=py.FulltextIndexConfig(analyzer="ik"),
            )
            collection = self._client.create_collection(name, configuration=configuration, embedding_function=None)
            self._collection_mode = "configuration"
            return collection

    # -- 写入 ---------------------------------------------------------
    def upsert_document(self, document: Document, vectors: np.ndarray) -> None:
        started = time.perf_counter()
        existing = self._docs.get(ids=[document.doc_id], include=["metadatas"])
        old_count = 0
        if existing.get("ids"):
            metadatas = existing.get("metadatas") or [{}]
            old_count = int((metadatas[0] or {}).get("n_chunks") or 0)
        chunk_ids = [f"{document.doc_id}#{index:03d}" for index in range(max(old_count, document.n_chunks))]
        if chunk_ids:
            self._chunks.delete(ids=chunk_ids)
        self._docs.upsert(
            ids=[document.doc_id],
            embeddings=[self._doc_vector(document)],
            documents=[document.abstract or document.title],
            metadatas=[
                {
                    "title": document.title,
                    "kind": document.kind,
                    "year": document.year if document.year is not None else 0,
                    "tags": ",".join(document.tags),
                    "n_chunks": document.n_chunks,
                    "chars": sum(chunk.chars for chunk in document.chunks),
                    "path": document.path,
                    "sha1": document.sha1,
                    "imported_at": now_iso(),
                }
            ],
        )
        new_ids = [chunk.chunk_id for chunk in document.chunks]
        if new_ids:
            metadatas = []
            for chunk in document.chunks:
                meta = _chunk_metadata(document, chunk)
                meta["chunk_id"] = chunk.chunk_id
                metadatas.append(meta)
            self._chunks.upsert(
                ids=new_ids,
                embeddings=[np.asarray(vector, dtype=np.float32).tolist() for vector in vectors],
                documents=[chunk.text for chunk in document.chunks],
                metadatas=metadatas,
            )
        self._chunks.refresh_index()
        self._docs.refresh_index()
        self.last_write_ms = (time.perf_counter() - started) * 1000

    def _doc_vector(self, document: Document) -> list[float]:
        """文档级向量只用于占位（文档表不做相似度检索），用标题哈希填充。"""

        digest = hashlib.blake2b(document.doc_id.encode("utf-8"), digest_size=8).digest()
        seed = int.from_bytes(digest, "little") % (2**32)
        rng = np.random.default_rng(seed)
        vector = rng.random(self.dimension, dtype=np.float32)
        return (vector / np.linalg.norm(vector)).tolist()

    def delete_document(self, doc_id: str) -> None:
        prefix_ids = [f"{doc_id}#{index:03d}" for index in range(0, 500)]
        self._chunks.delete(ids=prefix_ids)
        self._docs.delete(ids=[doc_id])

    def flush(self) -> None:
        self._chunks.refresh_index()
        self._docs.refresh_index()

    # -- 读取 ---------------------------------------------------------
    def list_documents(self) -> list[dict]:
        result = self._docs.get(include=["metadatas", "documents"], limit=1000)
        output = []
        for doc_id, meta in zip(result.get("ids") or [], result.get("metadatas") or []):
            item = dict(meta or {})
            item["doc_id"] = doc_id
            item["tags"] = [tag for tag in str(item.get("tags", "")).split(",") if tag]
            item["year"] = item.get("year") or None
            output.append(item)
        output.sort(key=lambda item: (-(item.get("year") or 0), item["doc_id"]))
        return output

    def vector_search(self, vector: np.ndarray, top_k: int, filters: Filters) -> list[RawHit]:
        where = _sql_where(filters)
        kwargs = {
            "query_embeddings": np.asarray(vector, dtype=np.float32).tolist(),
            "n_results": max(top_k, 1),
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where
        result = self._chunks.query(**kwargs)
        hits = []
        for row in _split_result(result):
            distance = row["distance"] if row["distance"] is not None else 1.0
            hits.append(RawHit(chunk_id=row["id"], score=1.0 - float(distance), rank=len(hits)))
        return hits

    def fulltext_search(self, query: str, top_k: int, filters: Filters) -> list[RawHit]:
        where = _sql_where(filters)
        query_branch: dict = {"where_document": {"$contains": query}, "n_results": max(top_k, 1)}
        if where:
            query_branch["where"] = where
        result = self._chunks.hybrid_search(
            query=query_branch,
            rank={"rrf": {"rank_window_size": max(top_k, 10), "rank_constant": 60}},
            n_results=max(top_k, 1),
            include=["documents", "metadatas", "distances"],
        )
        hits = []
        for row in _split_result(result):
            score = row["distance"] if row["distance"] is not None else 0.0
            hits.append(RawHit(chunk_id=row["id"], score=float(score), rank=len(hits)))
        return hits

    def native_hybrid(self, query: str, vector: np.ndarray, top_k: int, filters: Filters) -> list[dict]:
        """seekdb 原生 hybrid_search（向量 + 全文，数据库侧 RRF），用于交叉验证。"""

        where = _sql_where(filters)
        branch: dict = {"where_document": {"$contains": query}, "n_results": max(top_k, 1)}
        knn: dict = {"query_embeddings": np.asarray(vector, dtype=np.float32).tolist(), "n_results": max(top_k, 1)}
        if where:
            branch["where"] = where
            knn["where"] = where
        result = self._chunks.hybrid_search(
            query=branch,
            knn=knn,
            rank={"rrf": {"rank_window_size": max(top_k, 10), "rank_constant": 60}},
            n_results=max(top_k, 1),
            include=["documents", "metadatas", "distances"],
        )
        return [{"chunk_id": row["id"], "score": row["distance"]} for row in _split_result(result)]

    def get_chunks(self, chunk_ids: list[str]) -> list[StoredChunk]:
        if not chunk_ids:
            return []
        result = self._chunks.get(ids=chunk_ids, include=["documents", "metadatas"])
        ids = result.get("ids") or []
        documents = result.get("documents") or []
        metadatas = result.get("metadatas") or []
        found = {}
        for position, chunk_id in enumerate(ids):
            meta = dict(metadatas[position] or {}) if position < len(metadatas) else {}
            text = documents[position] if position < len(documents) else ""
            found[chunk_id] = StoredChunk(
                chunk_id=chunk_id,
                doc_id=str(meta.get("doc_id", chunk_id.split("#")[0])),
                text=text or "",
                section=str(meta.get("section", "")),
                page=int(meta["page"]) if str(meta.get("page", "")).isdigit() and int(meta.get("page", 0)) > 0 else None,
                metadata={
                    "title": meta.get("title", ""),
                    "kind": meta.get("kind", ""),
                    "tags": [tag for tag in str(meta.get("tags", "")).split(",") if tag],
                    "year": meta.get("year") or None,
                    "index": meta.get("index", meta.get("idx", 0)),
                },
            )
        return [found[chunk_id] for chunk_id in chunk_ids if chunk_id in found]

    def stats(self) -> dict:
        documents = self._docs.count()
        chunks = self._chunks.count()
        total_chars = 0
        for meta in self._docs.get(include=["metadatas"], limit=1000).get("metadatas") or []:
            try:
                total_chars += int((meta or {}).get("chars") or 0)
            except (TypeError, ValueError):
                continue
        return {
            "backend": self.name,
            "mode": "embedded",
            "path": str(self.path),
            "database": DB_NAME,
            "collections": [CHUNKS, DOCS],
            "documents": documents,
            "chunks": chunks,
            "total_chars": total_chars,
            "dimension": self.dimension,
            "vector_index": "HNSW(cosine)",
            "fulltext_analyzer": "ik",
            "collection_mode": self._collection_mode or "existing",
            "pyseekdb": getattr(self.pyseekdb, "__version__", "unknown"),
            "checked_at": now_iso(),
        }

    def reset(self) -> None:
        for collection in (self._chunks, self._docs):
            ids = collection.get(include=[], limit=5000).get("ids") or []
            if ids:
                collection.delete(ids=ids)
            collection.refresh_index()

    def dump_document(self, doc_id: str) -> dict:
        result = self._docs.get(ids=[doc_id], include=["metadatas", "documents"])
        ids = result.get("ids") or []
        if not ids:
            return {}
        item = dict(result.get("metadatas", [{}])[0] or {})
        item["doc_id"] = ids[0]
        item["abstract"] = (result.get("documents") or [""])[0]
        return item

    def close(self) -> None:
        """尽量优雅关闭嵌入式 seekdb；不支持时交给进程退出。"""

        for candidate in ("close", "disconnect", "shutdown"):
            for target in (self._client, getattr(self, "_chunks", None), getattr(self, "_docs", None)):
                method = getattr(target, candidate, None)
                if callable(method):
                    try:
                        method()
                    except Exception:  # noqa: BLE001 - 关闭阶段不再抛错
                        pass
