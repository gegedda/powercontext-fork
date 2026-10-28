"""记忆状态的数据结构（不依赖 PowerContext，便于单独测试与序列化）。"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field


def now() -> _dt.datetime:
    return _dt.datetime.now().astimezone()


@dataclass(slots=True)
class TopicState:
    doc_id: str
    title: str
    strength: float = 0.0
    attempts: int = 0
    correct: int = 0
    interval_days: float = 1.0
    last_review: str | None = None
    due: str | None = None
    history: list[dict] = field(default_factory=list)

    def as_payload(self) -> dict:
        return {
            "type": "topic",
            "doc_id": self.doc_id,
            "title": self.title,
            "strength": round(self.strength, 3),
            "attempts": self.attempts,
            "correct": self.correct,
            "interval_days": round(self.interval_days, 2),
            "last_review": self.last_review,
            "due": self.due,
            "history": self.history[-6:],
        }

    def is_weak(self) -> bool:
        return self.strength < 0.33

    def is_due(self) -> bool:
        if not self.due:
            return True
        try:
            return _dt.datetime.fromisoformat(self.due) <= now()
        except ValueError:
            return True


@dataclass(slots=True)
class MemoryState:
    profile: dict = field(default_factory=dict)
    topics: dict[str, TopicState] = field(default_factory=dict)
    ask_log: list[dict] = field(default_factory=list)

    @property
    def weak_docs(self) -> set[str]:
        return {doc_id for doc_id, topic in self.topics.items() if topic.is_weak() and topic.attempts > 0}

    def weak_titles(self) -> list[dict]:
        items = [t for t in self.topics.values() if t.is_weak() and t.attempts > 0]
        items.sort(key=lambda t: t.strength)
        return [{"doc_id": t.doc_id, "title": t.title, "strength": round(t.strength, 3)} for t in items]