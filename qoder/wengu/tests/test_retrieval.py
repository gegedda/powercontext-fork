from __future__ import annotations

import numpy as np

from wengu.retrieval import (
    RetrievedChunk,
    citations_from_blocks,
    compose_extractive_answer,
    features,
    rrf_fuse,
)
from wengu.store.base import RawHit


def test_features_are_language_agnostic() -> None:
    assert "raft" in features("Raft 共识算法")
    assert "共识" in features("Raft 共识算法")


def test_rrf_fuse_prefers_both_channels() -> None:
    vector = [RawHit(chunk_id="a#000", score=0.9, rank=0), RawHit(chunk_id="b#000", score=0.8, rank=1)]
    fulltext = [RawHit(chunk_id="b#000", score=3.0, rank=0), RawHit(chunk_id="c#000", score=2.0, rank=1)]
    fused = rrf_fuse(vector, fulltext)
    assert fused[0]["chunk_id"] == "b#000"
    assert fused[0]["vector_rank"] == 2
    assert fused[0]["fulltext_rank"] == 1


def test_rrf_fuse_applies_weak_boost() -> None:
    vector = [RawHit(chunk_id="weak#000", score=0.5, rank=0), RawHit(chunk_id="other#000", score=0.51, rank=1)]
    fused = rrf_fuse(vector, [], weak_docs={"weak"})
    assert fused[0]["chunk_id"] == "weak#000"
    assert fused[0]["weak_boost"] > 1.0


def _result(chunk_id: str, text: str, score: float, vector_rank: int = 1) -> RetrievedChunk:
    doc_id = chunk_id.split("#")[0]
    return RetrievedChunk(
        chunk_id=chunk_id,
        doc_id=doc_id,
        title=doc_id,
        section="定义",
        page=None,
        text=text,
        score=score,
        vector_rank=vector_rank,
        fulltext_rank=1,
    )


def test_extractive_answer_gates_unrelated_chunks() -> None:
    results = [
        _result("raft#000", "当日志被多数派持久化后，Leader 提交并把结果返回客户端。", 0.03),
        _result("lsm#000", "LSM 的 compaction 会消除墓碑记录。", 0.029),
        _result("mvcc#000", "快照隔离无法避免写偏斜，两个事务会读到重叠数据。", 0.028),
    ]
    answer = compose_extractive_answer("快照隔离为什么会出现写偏斜？", results, limit=3)
    chunk_ids = [block["chunk_id"] for block in answer["blocks"]]
    assert "mvcc#000" in chunk_ids
    assert answer["mode"] == "extractive"
    assert citations_from_blocks(answer["blocks"])


def test_extractive_answer_handles_empty() -> None:
    answer = compose_extractive_answer("没有命中的问题", [], limit=3)
    assert answer["blocks"] == []
    assert "没有找到" in answer["summary"]


def test_normalized_embeddings_are_unit_length() -> None:
    from wengu.embedding import HashEmbedder

    embedder = HashEmbedder(dim=64)
    matrix = embedder.encode_documents(["Raft 日志复制", "快照隔离与写偏斜"])
    norms = np.linalg.norm(matrix, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)
