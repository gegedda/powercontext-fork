"""复习教练：从「谁薄弱、谁到期」出发组卷，并把结果写回记忆。

组卷优先级：到期且薄弱 > 薄弱 > 没复习过 > 其余；
题目来源：``sample_library/quizzes.json`` 的人工考点，缺失时用原文自动出题（完形/要点复述）。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .state import MemoryState, TopicState
from .store.base import KnowledgeStore, StoredChunk

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_STOPWORDS = {
    "我们",
    "一个",
    "这个",
    "可以",
    "不是",
    "就是",
    "因为",
    "所以",
    "但是",
    "需要",
    "通过",
    "使用",
    "进行",
    "已经",
    "以及",
    "这些",
    "那些",
    "the",
    "and",
    "for",
    "with",
}

GRADE_LABELS = {"forgot": "忘了", "vague": "模糊", "known": "记得"}
GRADE_SCORE = {"forgot": 0.0, "vague": 0.5, "known": 1.0}


@dataclass(slots=True)
class ReviewItem:
    item_id: str
    chunk_id: str
    doc_id: str
    title: str
    section: str
    question: str
    answer: str
    terms: list[str]
    source: str
    reason: str
    strength: float = 0.0
    due_at: str | None = None
    attempts: int = 0

    def as_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "title": self.title,
            "section": self.section,
            "question": self.question,
            "answer": self.answer,
            "terms": self.terms,
            "source": self.source,
            "reason": self.reason,
            "strength": round(self.strength, 3),
            "due_at": self.due_at,
            "attempts": self.attempts,
        }


def load_curated(path: Path | None) -> dict[str, list[dict]]:
    if not path or not Path(path).is_file():
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {key: value for key, value in data.items() if isinstance(value, list)}


def _priority(topic: TopicState | None) -> tuple[int, float]:
    if topic is None:
        return (2, 0.0)
    reviewed = topic.attempts > 0
    if reviewed and topic.is_weak():
        return (0 if topic.is_due() else 1, topic.strength)
    if not reviewed:
        return (2, 0.0)
    if topic.is_due():
        return (3, topic.strength)
    return (4, topic.strength)


def _reason(topic: TopicState | None) -> str:
    if topic is None:
        return "还没复习过"
    reviewed = topic.attempts > 0
    if reviewed and topic.is_weak() and topic.is_due():
        return "到期复习，而且上次掌握度偏低"
    if reviewed and topic.is_weak():
        return "这里一直薄弱，多练一次"
    if not reviewed:
        return "新导入的文献，先摸摸底"
    if topic.is_due():
        return "到复习时间了"
    return "巩固已掌握内容"


def _stable_pick(items: list, key: str, attempts: int):
    if not items:
        return None
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=4).digest()
    offset = int.from_bytes(digest, "little") + attempts
    return items[offset % len(items)]


def _terms_from_text(text: str, limit: int = 4) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9_\-]{2,}|[\u4e00-\u9fff]{2,6}", text)
    counts: dict[str, int] = {}
    for word in words:
        if word.lower() in _STOPWORDS or any(_CJK_RE.match(c) and len(word) < 2 for c in word[:1]):
            continue
        counts[word] = counts.get(word, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0])))
    return [word for word, _ in ranked[:limit]]


def auto_quiz(chunk: StoredChunk, seed: str = "") -> dict:
    """没有人工考点时，用原文句子做「完形填空 + 要点复述」。"""

    body = re.sub(r"^【[^】]*】", "", chunk.text).strip()
    sentences = [s.strip() for s in re.split(r"(?<=[。！？])|\n+", body) if len(s.strip()) >= 16]
    if not sentences:
        sentences = [body[:120]]
    terms = _terms_from_text(body)
    target = sentences[0]
    if terms:
        term = terms[0]
        for sentence in sentences:
            if term in sentence:
                target = sentence
                break
        masked = target.replace(term, "＿＿＿＿", 1)
        return {
            "question": f"补全这一句（原文出自「{chunk.section}」）：\n{masked}",
            "answer": f"{target}（关键术语：{term}）",
            "terms": [term],
        }
    return {
        "question": f"用自己的话复述「{chunk.section}」这一节的要点。",
        "answer": target,
        "terms": [],
    }


def build_session(
    state: MemoryState,
    store: KnowledgeStore,
    documents: list[dict],
    *,
    quota: int = 6,
    curated: dict[str, list[dict]] | None = None,
) -> list[ReviewItem]:
    curated = curated or {}
    titles = {str(doc.get("doc_id")): str(doc.get("title", doc.get("doc_id"))) for doc in documents}
    candidates: list[tuple[tuple[int, float], str, TopicState | None]] = []
    for doc_id, title in titles.items():
        topic = state.topics.get(doc_id)
        candidates.append((_priority(topic), doc_id, topic))
    for doc_id, topic in state.topics.items():
        if doc_id not in titles:
            candidates.append((_priority(topic), doc_id, topic))
    candidates.sort(key=lambda item: item[0])

    items: list[ReviewItem] = []
    for _, doc_id, topic in candidates:
        if len(items) >= quota:
            break
        attempts = topic.attempts if topic else 0
        title = topic.title if topic else titles.get(doc_id, doc_id)
        curated_items = curated.get(doc_id) or []
        if curated_items:
            picked = _stable_pick(curated_items, f"{doc_id}:{attempts}", attempts)
            items.append(
                ReviewItem(
                    item_id=f"{doc_id}:curated:{curated_items.index(picked)}",
                    chunk_id=f"{doc_id}#curated",
                    doc_id=doc_id,
                    title=title,
                    section=str(picked.get("section", "")),
                    question=str(picked.get("q", "")),
                    answer=str(picked.get("a", "")),
                    terms=list(picked.get("terms", [])),
                    source="curated",
                    reason=_reason(topic),
                    strength=topic.strength if topic else 0.0,
                    due_at=topic.due if topic else None,
                    attempts=attempts,
                )
            )
            if len(items) < quota and topic and topic.is_weak() and topic.attempts > 0:
                items.append(
                    _auto_item(store, doc_id, title, topic, f"{doc_id}:auto:{attempts}")
                )
            continue
        item = _auto_item(store, doc_id, title, topic, f"{doc_id}:auto:{attempts}")
        if item is not None:
            items.append(item)
    return [item for item in items if item is not None][:quota]


def _auto_item(
    store: KnowledgeStore,
    doc_id: str,
    title: str,
    topic: TopicState | None,
    seed: str,
) -> ReviewItem | None:
    chunks = store.get_chunks([f"{doc_id}#{index:03d}" for index in range(0, 12)])
    if not chunks:
        return None
    chunk = _stable_pick(chunks, seed, topic.attempts if topic else 0)
    quiz = auto_quiz(chunk, seed)
    return ReviewItem(
        item_id=f"{doc_id}:auto:{chunk.chunk_id}",
        chunk_id=chunk.chunk_id,
        doc_id=doc_id,
        title=title,
        section=chunk.section,
        question=str(quiz["question"]),
        answer=str(quiz["answer"]),
        terms=list(quiz["terms"]),
        source="auto",
        reason=_reason(topic),
        strength=topic.strength if topic else 0.0,
        due_at=topic.due if topic else None,
        attempts=topic.attempts if topic else 0,
    )


def score_answer(expected_terms: list[str], answer_text: str) -> dict:
    """关键词覆盖率打分：给「自己写答案」的场景一个可解释的分数。"""

    answer_text = (answer_text or "").strip()
    if not expected_terms:
        return {"score": None, "matched": [], "missing": [], "note": "本题以自评为主"}
    matched = [term for term in expected_terms if term and term.lower() in answer_text.lower()]
    missing = [term for term in expected_terms if term not in matched]
    return {
        "score": round(len(matched) / len(expected_terms), 2),
        "matched": matched,
        "missing": missing,
        "note": "命中关键术语即视为答对要点" if matched else "一个关键术语都没提到，建议重看原文",
    }
