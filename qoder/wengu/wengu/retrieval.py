"""检索融合与答案组织。

单路召回（向量 / 全文）由存储后端提供，这里负责：
1. RRF（Reciprocal Rank Fusion）融合，避免两路分数量纲不一致；
2. 薄弱知识点加权：把 PowerContext 里记住的薄弱主题作为重排信号；
3. 组装带出处的摘录式答案（可选接入 LLM 做摘要，没配置也能用）。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import numpy as np

from .store.base import Filters, KnowledgeStore, RawHit, StoredChunk

RRF_K = 60
VECTOR_WEIGHT = 1.0
FULLTEXT_WEIGHT = 1.0
WEAK_BOOST = 1.18


@dataclass(slots=True)
class RetrievedChunk:
    chunk_id: str
    doc_id: str
    title: str
    section: str
    page: int | None
    text: str
    score: float
    vector_rank: int | None = None
    fulltext_rank: int | None = None
    weak_boost: float = 1.0

    def as_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "title": self.title,
            "section": self.section,
            "page": self.page,
            "score": round(self.score, 6),
            "vector_rank": self.vector_rank,
            "fulltext_rank": self.fulltext_rank,
            "weak_boost": round(self.weak_boost, 3),
        }


@dataclass(slots=True)
class SearchTrace:
    query: str
    filters: dict
    backend: str
    embedder: dict
    vector_hits: list[dict] = field(default_factory=list)
    fulltext_hits: list[dict] = field(default_factory=list)
    fused: list[dict] = field(default_factory=list)
    timings_ms: dict = field(default_factory=dict)
    weak_topics: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "query": self.query,
            "filters": self.filters,
            "backend": self.backend,
            "embedder": self.embedder,
            "vector_hits": self.vector_hits,
            "fulltext_hits": self.fulltext_hits,
            "fused": self.fused,
            "timings_ms": {k: round(v, 2) for k, v in self.timings_ms.items()},
            "weak_topics": self.weak_topics,
        }


def rrf_fuse(
    vector_hits: list[RawHit],
    fulltext_hits: list[RawHit],
    weak_docs: set[str] | None = None,
    weak_tags: set[str] | None = None,
    doc_meta: dict[str, dict] | None = None,
) -> list[dict]:
    """RRF 融合两路召回，并按薄弱主题重排。"""

    weak_docs = weak_docs or set()
    weak_tags = weak_tags or set()
    doc_meta = doc_meta or {}
    scores: dict[str, float] = {}
    detail: dict[str, dict] = {}

    def touch(chunk_id: str) -> dict:
        if chunk_id not in detail:
            detail[chunk_id] = {
                "chunk_id": chunk_id,
                "vector_rank": None,
                "fulltext_rank": None,
                "vector_score": None,
                "fulltext_score": None,
            }
        return detail[chunk_id]

    for hit in vector_hits:
        entry = touch(hit.chunk_id)
        entry["vector_rank"] = hit.rank + 1
        entry["vector_score"] = hit.score
        scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + VECTOR_WEIGHT / (RRF_K + hit.rank + 1)
    for hit in fulltext_hits:
        entry = touch(hit.chunk_id)
        entry["fulltext_rank"] = hit.rank + 1
        entry["fulltext_score"] = hit.score
        scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + FULLTEXT_WEIGHT / (RRF_K + hit.rank + 1)

    fused = []
    for chunk_id, score in scores.items():
        entry = detail[chunk_id]
        doc_id = chunk_id.split("#")[0]
        boost = 1.0
        tags = set((doc_meta.get(doc_id, {}).get("tags") or []))
        if doc_id in weak_docs or (weak_tags and tags & weak_tags):
            boost = WEAK_BOOST
        entry["score"] = score * boost
        entry["weak_boost"] = boost
        entry["doc_id"] = doc_id
        fused.append(entry)
    fused.sort(key=lambda item: -item["score"])
    return fused


def hybrid_search(
    store: KnowledgeStore,
    embedder,
    query: str,
    *,
    filters: Filters | None = None,
    top_k: int = 8,
    weak_docs: set[str] | None = None,
    weak_tags: set[str] | None = None,
    doc_meta: dict[str, dict] | None = None,
) -> tuple[list[RetrievedChunk], SearchTrace]:
    filters = filters or Filters()
    started = time.perf_counter()
    query_vector = embedder.encode_query(query)
    embed_ms = (time.perf_counter() - started) * 1000

    recall_k = max(top_k * 3, 12)
    t0 = time.perf_counter()
    vector_hits = store.vector_search(np.asarray(query_vector, dtype=np.float32), recall_k, filters)
    vector_ms = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    fulltext_hits = store.fulltext_search(query, recall_k, filters)
    fulltext_ms = (time.perf_counter() - t0) * 1000

    fused = rrf_fuse(vector_hits, fulltext_hits, weak_docs, weak_tags, doc_meta)
    selected = fused[:top_k]

    t0 = time.perf_counter()
    hydrated = {chunk.chunk_id: chunk for chunk in store.get_chunks([item["chunk_id"] for item in selected])}
    fetch_ms = (time.perf_counter() - t0) * 1000

    results: list[RetrievedChunk] = []
    for item in selected:
        chunk = hydrated.get(item["chunk_id"])
        if chunk is None:
            continue
        results.append(
            RetrievedChunk(
                chunk_id=chunk.chunk_id,
                doc_id=chunk.doc_id,
                title=chunk.metadata.get("title", chunk.doc_id),
                section=chunk.section,
                page=chunk.page,
                text=chunk.text,
                score=item["score"],
                vector_rank=item["vector_rank"],
                fulltext_rank=item["fulltext_rank"],
                weak_boost=item["weak_boost"],
            )
        )

    trace = SearchTrace(
        query=query,
        filters=filters.as_dict(),
        backend=store.name,
        embedder=embedder.describe(),
        vector_hits=[
            {"chunk_id": h.chunk_id, "score": round(h.score, 6), "rank": h.rank + 1} for h in vector_hits[:recall_k]
        ],
        fulltext_hits=[
            {"chunk_id": h.chunk_id, "score": round(h.score, 6), "rank": h.rank + 1} for h in fulltext_hits[:recall_k]
        ],
        fused=selected,
        timings_ms={
            "embed": embed_ms,
            "vector": vector_ms,
            "fulltext": fulltext_ms,
            "fetch": fetch_ms,
            "total": (time.perf_counter() - started) * 1000,
        },
        weak_topics=sorted(weak_docs or []),
    )
    return results, trace


def _sentences(text: str) -> list[str]:
    body = re.sub(r"^【[^】]*】", "", text).strip()
    parts = re.split(r"(?<=[。！？；!?;])|\n+", body)
    return [p.strip() for p in parts if p and len(p.strip()) >= 8]


def features(text: str) -> set[str]:
    """中文用二元字组 + 英文单词做特征，避免依赖分词器。"""

    lowered = (text or "").lower()
    words = set(re.findall(r"[a-z0-9_]{2,}", lowered))
    han = re.findall(r"[\u4e00-\u9fff]", lowered)
    bigrams = {a + b for a, b in zip(han, han[1:])}
    return words | bigrams


def _rank_sentences(query: str, text: str, limit: int = 2) -> list[str]:
    sentences = _sentences(text)
    if not sentences:
        return []
    query_features = features(query)
    scored = []
    for position, sentence in enumerate(sentences):
        sentence_features = features(sentence)
        overlap = len(sentence_features & query_features)
        density = overlap / (len(sentence_features) ** 0.5 or 1.0)
        scored.append((density, -position, sentence))
    scored.sort(reverse=True)
    chosen = [item[2] for item in scored[:limit]]
    return [sentence for sentence in sentences if sentence in chosen]


def compose_extractive_answer(query: str, results: list[RetrievedChunk], limit: int = 3) -> dict:
    """无 LLM 时的摘录式回答：给出最相关原文片段 + 出处，并说明匹配原因。

    相关性门控：优先保留「自身内容与问题有特征重叠」的结果，以及得分最高的前两条，
    避免 RRF 融合里偶然靠前的噪声片段挤进答案。
    """

    query_features = features(query)
    gated = []
    for position, item in enumerate(results):
        overlap = len(features(item.text) & query_features)
        keep = overlap >= 2 or position < 2
        gated.append((keep, overlap, position, item))
    gated = [entry for entry in gated if entry[0]]
    if not gated:
        gated = [(True, 0, position, item) for position, item in enumerate(results[:limit])]

    blocks = []
    for _, overlap, _, item in gated[:limit]:
        ranked = _rank_sentences(query, item.text, limit=2)
        quote = "".join(ranked) or item.text[:180]
        quote = re.sub(r"[*`]{1,2}", "", quote).strip()
        blocks.append(
            {
                "title": item.title,
                "section": item.section,
                "page": item.page,
                "doc_id": item.doc_id,
                "chunk_id": item.chunk_id,
                "quote": quote.strip(),
                "score": round(item.score, 6),
                "overlap": overlap,
                "matched_by": _matched_by(item),
                "weak_topic": item.weak_boost > 1.0,
            }
        )
    return {
        "mode": "extractive",
        "summary": _extractive_summary(blocks),
        "blocks": blocks,
    }


def citations_from_blocks(blocks: list[dict]) -> list[dict]:
    seen: set[str] = set()
    output = []
    for block in blocks:
        key = f"{block.get('doc_id')}#{block.get('section')}"
        if key in seen:
            continue
        seen.add(key)
        output.append(
            {
                "doc_id": block.get("doc_id"),
                "title": block.get("title"),
                "section": block.get("section"),
                "page": block.get("page"),
                "chunk_id": block.get("chunk_id"),
            }
        )
    return output


def _extractive_summary(blocks: list[dict]) -> str:
    if not blocks:
        return "知识库里没有找到相关片段。先导入文献，或换个说法再问一次。"
    first = blocks[0]
    location = f"「{first['title']}」· {first['section']}"
    return f"最相关的内容在 {location}：{first['quote'][:160]}"


def _matched_by(item: RetrievedChunk) -> list[str]:
    tags = []
    if item.vector_rank:
        tags.append(f"语义第 {item.vector_rank} 名")
    if item.fulltext_rank:
        tags.append(f"关键词第 {item.fulltext_rank} 名")
    return tags


def citations(results: list[RetrievedChunk]) -> list[dict]:
    seen: set[str] = set()
    output = []
    for item in results:
        key = f"{item.doc_id}#{item.section}"
        if key in seen:
            continue
        seen.add(key)
        output.append(
            {
                "doc_id": item.doc_id,
                "title": item.title,
                "section": item.section,
                "page": item.page,
                "chunk_id": item.chunk_id,
            }
        )
    return output
