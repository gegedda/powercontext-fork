from __future__ import annotations

from pathlib import Path

from wengu.embedding import HashEmbedder
from wengu.library import parse_document
from wengu.store.base import Filters
from wengu.store.sqlite_backend import SQLiteStore


class _Settings:
    chunk_size = 240
    chunk_overlap = 40


def _build_store(tmp_path: Path) -> tuple[SQLiteStore, str]:
    library = tmp_path / "library"
    library.mkdir()
    (library / "raft.md").write_text(
        "---\ntitle: Raft 共识算法\nyear: 2014\ntags: 分布式\n---\n\n"
        "## 日志复制\n\n当日志被多数派持久化后，Leader 推进 commitIndex 并返回客户端。\n\n"
        "## 选举\n\n任期号更大的节点会迫使其他节点转为 Follower。\n",
        encoding="utf-8",
    )
    (library / "lsm.md").write_text(
        "---\ntitle: LSM 存储\nyear: 1996\ntags: 存储引擎\n---\n\n"
        "## 机制\n\nMemTable 写满后转成 Immutable MemTable，随后刷成 SSTable，compaction 清理墓碑。\n",
        encoding="utf-8",
    )
    embedder = HashEmbedder(dim=64)
    store = SQLiteStore(tmp_path / "wengu.sqlite3")
    for path in sorted(library.iterdir()):
        document = parse_document(path, settings=_Settings())
        vectors = embedder.encode_documents([chunk.text for chunk in document.chunks])
        store.upsert_document(document, vectors)
    return store, str(tmp_path)


def test_sqlite_store_roundtrip(tmp_path: Path) -> None:
    store, _ = _build_store(tmp_path)
    stats = store.stats()
    assert stats["backend"] == "sqlite"
    assert stats["documents"] == 2
    assert stats["chunks"] >= 3

    documents = store.list_documents()
    assert {doc["doc_id"] for doc in documents} == {"raft", "lsm"}
    assert documents[0]["tags"]

    embedder = HashEmbedder(dim=64)
    hits = store.vector_search(embedder.encode_query("多数派提交"), 5, Filters())
    assert hits
    text_hits = store.fulltext_search("多数派 提交", 5, Filters())
    assert text_hits
    chunk = store.get_chunks([text_hits[0].chunk_id])[0]
    assert chunk.text
    assert chunk.metadata["title"]

    filtered = store.vector_search(embedder.encode_query("多数派"), 5, Filters(year_min=2000))
    assert filtered
    assert all("raft" in hit.chunk_id for hit in filtered)


def test_sqlite_store_reset_and_delete(tmp_path: Path) -> None:
    store, _ = _build_store(tmp_path)
    store.delete_document("lsm")
    assert [doc["doc_id"] for doc in store.list_documents()] == ["raft"]
    store.reset()
    assert store.stats()["documents"] == 0
    assert store.stats()["chunks"] == 0
