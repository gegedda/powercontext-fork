from __future__ import annotations

import datetime as dt

from wengu.coach import auto_quiz, build_session, score_answer
from wengu.state import MemoryState, TopicState
from wengu.store.base import StoredChunk


class FakeStore:
    name = "fake"

    def __init__(self, chunks: list[StoredChunk]) -> None:
        self._chunks = chunks

    def get_chunks(self, chunk_ids: list[str]) -> list[StoredChunk]:
        index = {chunk.chunk_id: chunk for chunk in self._chunks}
        return [index[chunk_id] for chunk_id in chunk_ids if chunk_id in index]


def _chunk(doc_id: str, index: int = 0, section: str = "定义") -> StoredChunk:
    return StoredChunk(
        chunk_id=f"{doc_id}#{index:03d}",
        doc_id=doc_id,
        text=f"【{section}】LSM-Tree 的读放大可以用 Bloom Filter 缓解，避免检查不存在的键。",
        section=section,
        page=None,
        metadata={"title": doc_id, "tags": ["存储"], "year": 2020, "index": index},
    )


def test_weak_and_due_topics_come_first() -> None:
    now = dt.datetime.now().astimezone()
    state = MemoryState(
        topics={
            "weak": TopicState(doc_id="weak", title="薄弱文档", strength=0.1, attempts=2, due=now.isoformat()),
            "strong": TopicState(doc_id="strong", title="已掌握", strength=0.9, attempts=3, due=now.isoformat()),
            "fresh": TopicState(doc_id="fresh", title="新文档"),
        }
    )
    store = FakeStore([_chunk("weak"), _chunk("strong"), _chunk("fresh")])
    documents = [
        {"doc_id": "weak", "title": "薄弱文档"},
        {"doc_id": "strong", "title": "已掌握"},
        {"doc_id": "fresh", "title": "新文档"},
    ]
    items = build_session(state, store, documents, quota=3, curated={})
    assert items[0].doc_id == "weak"
    assert items[0].reason.startswith("到期复习")
    assert len(items) == 3


def test_curated_quiz_is_preferred() -> None:
    state = MemoryState()
    store = FakeStore([_chunk("raft")])
    curated = {"raft": [{"q": "提交条件？", "a": "多数派持久化", "terms": ["多数派"], "section": "日志复制"}]}
    items = build_session(state, store, [{"doc_id": "raft", "title": "Raft"}], quota=1, curated=curated)
    assert items[0].source == "curated"
    assert items[0].question == "提交条件？"


def test_auto_quiz_masks_key_term() -> None:
    quiz = auto_quiz(_chunk("lsm"))
    assert "＿＿＿＿" in quiz["question"]
    assert quiz["answer"]


def test_score_answer_reports_missing_terms() -> None:
    result = score_answer(["写偏斜", "SSI"], "写偏斜可以用串行化解决")
    assert 0 <= result["score"] <= 1
    assert "写偏斜" in result["matched"]
    assert "SSI" in result["missing"]
