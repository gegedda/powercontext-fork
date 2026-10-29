"""PowerContext 记忆层：学习档案、知识点掌握度、复习计划、提问历史。

实现要点（对应 PowerContext 1.4.1 的 Artifact 契约）：
- 每条记忆是一个 ``atomic-memory`` Artifact，正文是 JSON，``id`` 字段是逻辑主键；
- 新建走 ``create_artifact``，更新走 ``replace_artifact``（带 ``expected_etag``），
  所以每次「复习一次」「改一次偏好」都会推进 artifact revision，历史可回看；
- 服务重启后 ``list_atomic_memories`` 即可恢复全部状态，这是「越用越懂你」的来源。
"""

from __future__ import annotations

import datetime as _dt
import json
import time
from dataclasses import dataclass

from powercontext.client import PowerContextClient
from powercontext.http._generated.models import (
    AtomicMemoryState,
    AtomicMemoryWriteContent,
    CreateArtifactRequest,
    CreateAtomicMemoryArtifactRequest,
    ListArtifactRevisionsRequest,
    ListAtomicMemoryRequest,
    ReplaceArtifactRequest,
    ReplaceAtomicMemoryArtifactRequest,
)

from .state import MemoryState, TopicState, now
from .tracing import TRACER

FAMILY = "atomic-memory"
KIND_PROFILE = "wengu-profile"
KIND_TOPIC = "wengu-topic"
KIND_ASKLOG = "wengu-ask-log"
PROFILE_ID = "PROFILE-1"
ASKLOG_ID = "ASKLOG-1"


def _etag(revision: int) -> str:
    return f'"revision:{revision}"'


@dataclass(slots=True)
class MemoryEntry:
    entry_id: str
    kind: str
    text: str
    artifact_id: str
    revision: int
    state: str

    @property
    def etag(self) -> str:
        return _etag(self.revision)


class LearningMemory:
    """对 PowerContext Memory 的一层薄封装：读、写、版本都带证据记录。"""

    def __init__(self, client: PowerContextClient, scope_id: str, quota: int = 6) -> None:
        self.client = client
        self.scope_id = scope_id
        self.quota = quota
        self.state = MemoryState(profile=self._default_profile())
        self._entries: dict[str, MemoryEntry] = {}
        self.last_load_ms = 0.0
        self.reads = 0
        self.writes = 0

    # -- 读取 ---------------------------------------------------------
    def _default_profile(self) -> dict:
        return {
            "id": PROFILE_ID,
            "type": "profile",
            "nickname": "同学",
            "goal": "把数据库系统笔记真正记住",
            "style": "要点优先",
            "daily_quota": self.quota,
            "created_at": now().isoformat(timespec="seconds"),
        }

    async def refresh(self) -> MemoryState:
        started = time.perf_counter()
        response = await self.client.list_atomic_memories(ListAtomicMemoryRequest(scope_id=self.scope_id))
        state = MemoryState(profile=self._default_profile())
        entries: dict[str, MemoryEntry] = {}
        for item in response.items:
            try:
                payload = json.loads(item.text)
            except (TypeError, ValueError):
                continue
            if not isinstance(payload, dict) or "id" not in payload:
                continue
            entry = MemoryEntry(
                entry_id=str(payload["id"]),
                kind=str(item.kind),
                text=item.text,
                artifact_id=item.artifact.artifact_id,
                revision=int(item.artifact.revision),
                state=str(item.state),
            )
            entries[entry.entry_id] = entry
            if entry.entry_id == PROFILE_ID:
                state.profile.update({k: v for k, v in payload.items() if k != "id"})
            elif entry.entry_id == ASKLOG_ID:
                state.ask_log = list(payload.get("items", []))
            elif payload.get("type") == "topic":
                state.topics[str(payload.get("doc_id"))] = TopicState(
                    doc_id=str(payload.get("doc_id")),
                    title=str(payload.get("title", "")),
                    strength=float(payload.get("strength", 0.0)),
                    attempts=int(payload.get("attempts", 0)),
                    correct=int(payload.get("correct", 0)),
                    interval_days=float(payload.get("interval_days", 1.0)),
                    last_review=payload.get("last_review"),
                    due=payload.get("due"),
                    history=list(payload.get("history", [])),
                )
        self._entries = entries
        self.state = state
        self.reads += 1
        self.last_load_ms = (time.perf_counter() - started) * 1000
        TRACER.record(
            "powercontext.list_atomic_memories",
            {
                "scope_id": self.scope_id,
                "entries": len(entries),
                "topics": len(state.topics),
                "latency_ms": round(self.last_load_ms, 2),
            },
        )
        return state

    # -- 写入 ---------------------------------------------------------
    def _payload(self, entry_id: str, payload: dict) -> str:
        body = dict(payload)
        body["id"] = entry_id
        body["updated_at"] = now().isoformat(timespec="seconds")
        text = json.dumps(body, ensure_ascii=False)
        if len(text.encode("utf-8")) > 8000:
            # PowerContext 单条记忆上限 8192 字节，超长时裁掉历史明细
            body.pop("history", None)
            body.pop("items", None)
            text = json.dumps(body, ensure_ascii=False)
        return text

    async def _write(self, entry_id: str, kind: str, payload: dict, reason: str) -> None:
        text = self._payload(entry_id, payload)
        existing = self._entries.get(entry_id)
        if existing is None:
            created = await self.client.create_artifact(
                self.scope_id,
                CreateArtifactRequest(
                    root=CreateAtomicMemoryArtifactRequest(
                        family=FAMILY,
                        content=AtomicMemoryWriteContent(kind=kind, text=text),
                    )
                ),
            )
            self.writes += 1
            TRACER.record(
                "powercontext.create_artifact",
                {
                    "entry_id": entry_id,
                    "memory_kind": kind,
                    "artifact_id": created.artifact_id,
                    "revision": created.revision,
                    "bytes": len(text.encode("utf-8")),
                    "reason": reason,
                },
            )
            return
        revision = await self.client.replace_artifact(
            self.scope_id,
            FAMILY,
            existing.artifact_id,
            ReplaceArtifactRequest(
                root=ReplaceAtomicMemoryArtifactRequest(content=AtomicMemoryWriteContent(kind=kind, text=text))
            ),
            expected_etag=existing.etag,
        )
        self.writes += 1
        TRACER.record(
            "powercontext.replace_artifact",
            {
                "entry_id": entry_id,
                "memory_kind": kind,
                "artifact_id": existing.artifact_id,
                "from_revision": existing.revision,
                "to_revision": revision.revision,
                "bytes": len(text.encode("utf-8")),
                "reason": reason,
            },
        )

    async def save_profile(self, **updates) -> dict:
        profile = dict(self.state.profile)
        profile.update({k: v for k, v in updates.items() if v is not None})
        payload = {k: v for k, v in profile.items() if k != "id"}
        payload["type"] = "profile"
        await self._write(PROFILE_ID, KIND_PROFILE, payload, "更新学习偏好")
        await self.refresh()
        return self.state.profile

    # -- 复习 ---------------------------------------------------------
    async def record_review(self, topic: TopicState, grade: str, question: str = "") -> TopicState:
        grade = grade if grade in {"forgot", "vague", "known"} else "vague"
        delta = {"forgot": -0.30, "vague": 0.12, "known": 0.35}[grade]
        factor = {"forgot": 1.0, "vague": 1.5, "known": 2.2}[grade]
        topic.strength = max(0.0, min(1.0, topic.strength + delta))
        topic.attempts += 1
        if grade == "known":
            topic.correct += 1
        topic.interval_days = max(1.0, min(60.0, topic.interval_days * factor))
        stamp = now()
        topic.last_review = stamp.isoformat(timespec="seconds")
        topic.due = (stamp + _dt.timedelta(days=topic.interval_days)).isoformat(timespec="seconds")
        topic.history.append(
            {
                "at": topic.last_review,
                "grade": grade,
                "strength": round(topic.strength, 3),
                "question": question[:60],
            }
        )
        await self._write(f"TOPIC-{topic.doc_id}", KIND_TOPIC, topic.as_payload(), f"复习结果 {grade}")
        await self.refresh()
        return topic

    async def ensure_topics(self, documents: list[dict]) -> None:
        changed = False
        for doc in documents:
            doc_id = str(doc.get("doc_id") or "")
            if not doc_id or f"TOPIC-{doc_id}" in self._entries:
                continue
            topic = TopicState(doc_id=doc_id, title=str(doc.get("title", doc_id)))
            topic.due = now().isoformat(timespec="seconds")
            await self._write(f"TOPIC-{doc_id}", KIND_TOPIC, topic.as_payload(), "登记新文献到复习计划")
            changed = True
        if changed:
            await self.refresh()

    # -- 提问历史 -----------------------------------------------------
    async def log_ask(self, question: str, citations: list[dict], doc_ids: list[str]) -> None:
        items = [item for item in self.state.ask_log if isinstance(item, dict)]
        sources: list[str] = []
        for citation in citations[:5]:
            title = str(citation.get("title") or "")
            if title and title not in sources:
                sources.append(title)
        items.insert(
            0,
            {
                "at": now().isoformat(timespec="seconds"),
                "question": question[:120],
                "doc_ids": doc_ids[:5],
                "sources": sources[:3],
            },
        )
        await self._write(ASKLOG_ID, KIND_ASKLOG, {"type": "ask-log", "items": items[:12]}, "记录提问历史")
        await self.refresh()

    # -- 版本历史（证据用） -------------------------------------------
    async def revision_history(self, entry_id: str, limit: int = 10) -> list[dict]:
        entry = self._entries.get(entry_id)
        if entry is None:
            return []
        try:
            page = await self.client.list_artifact_revisions(
                self.scope_id,
                FAMILY,
                entry.artifact_id,
                ListArtifactRevisionsRequest(limit=limit),
            )
        except Exception as exc:  # noqa: BLE001 - 版本历史不是主流程
            TRACER.record("powercontext.list_artifact_revisions", {"entry_id": entry_id, "error": str(exc)[:160]})
            return []
        history = []
        for revision in page.items:
            content = getattr(revision, "content", None) or {}
            text = content.get("text") if isinstance(content, dict) else None
            history.append(
                {
                    "entry_id": entry_id,
                    "revision": revision.revision,
                    "created_at": str(getattr(revision, "created_at", "")),
                    "text": (text or "")[:400],
                }
            )
        TRACER.record(
            "powercontext.list_artifact_revisions",
            {"entry_id": entry_id, "revisions": len(history)},
        )
        return history

    # -- 对外快照 -----------------------------------------------------
    def snapshot(self) -> dict:
        topics = []
        for topic in sorted(self.state.topics.values(), key=lambda t: t.strength):
            entry = self._entries.get(f"TOPIC-{topic.doc_id}")
            reviewed = topic.attempts > 0
            if not reviewed:
                status = "未复习"
            elif topic.is_weak():
                status = "薄弱"
            else:
                status = "已掌握"
            topics.append(
                {
                    **topic.as_payload(),
                    "weak": reviewed and topic.is_weak(),
                    "reviewed": reviewed,
                    "status": status,
                    "due_now": topic.is_due(),
                    "revision": entry.revision if entry else 0,
                }
            )
        return {
            "profile": self.state.profile,
            "topics": topics,
            "weak": self.state.weak_titles(),
            "ask_log": self.state.ask_log[:8],
            "entries": len(self._entries),
            "reads": self.reads,
            "writes": self.writes,
            "last_load_ms": round(self.last_load_ms, 2),
        }

    def entries_summary(self) -> list[dict]:
        return [
            {"entry_id": entry.entry_id, "kind": entry.kind, "artifact_id": entry.artifact_id, "revision": entry.revision}
            for entry in self._entries.values()
        ]


async def active_states(client: PowerContextClient, scope_id: str) -> list[str]:
    response = await client.list_atomic_memories(ListAtomicMemoryRequest(scope_id=scope_id))
    return [str(item.state) for item in response.items]


_ = AtomicMemoryState  # 保留导入，便于未来做「遗忘/恢复」操作
