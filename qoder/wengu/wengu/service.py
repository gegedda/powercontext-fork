"""业务编排：把「知识库（seekdb）+ 记忆（PowerContext）+ 复习教练」串起来。

界面、CLI、验证脚本都只调用这里，保证三条入口行为一致。
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from .coach import GRADE_LABELS, build_session, load_curated, score_answer
from .config import PROJECT_ROOT, Settings, load_settings
from .embedding import build_embedder
from .library import SUPPORTED_SUFFIXES, parse_document
from .memory import LearningMemory
from .retrieval import citations, citations_from_blocks, compose_extractive_answer, features, hybrid_search
from .runtime import PowerContextRuntime
from .state import TopicState
from .store import build_store
from .store.base import Filters
from .tracing import TRACER


@dataclass(slots=True)
class IngestResult:
    imported: list[dict]
    skipped: list[str]
    elapsed_ms: float

    def as_dict(self) -> dict:
        return {"imported": self.imported, "skipped": self.skipped, "elapsed_ms": round(self.elapsed_ms, 1)}


class WenGuService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()
        self.settings.ensure_dirs()
        self.embedder, self.embed_info = build_embedder(self.settings)
        dimension = int(getattr(self.embedder, "dim", self.settings.embed_dim))
        self.dimension = dimension
        self.store, self.store_info = build_store(self.settings, dimension)
        self.runtime = PowerContextRuntime(self.settings)
        self.memory: LearningMemory | None = None
        self.started = False
        self.started_at = ""
        self._lock = asyncio.Lock()
        self.curated = load_curated(PROJECT_ROOT / "sample_library" / "quizzes.json")

    # -- 生命周期 -----------------------------------------------------
    async def start(self) -> None:
        if self.started:
            return
        scope_id = await self.runtime.ensure_scope()
        self.memory = LearningMemory(self.runtime.client, scope_id, quota=self.settings.daily_quota)
        await self.memory.refresh()
        await self.memory.ensure_topics(self.store.list_documents())
        self.started = True
        self.started_at = time.strftime("%Y-%m-%d %H:%M:%S")
        TRACER.record(
            "wengu.ready",
            {
                "store": self.store.name,
                "embedder": self.embed_info.get("provider"),
                "scope_id": scope_id,
                "documents": self.store.stats().get("documents"),
            },
        )

    async def aclose(self) -> None:
        self.runtime.stop()
        close = getattr(self.store, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001 - 退出阶段不再抛错
                pass

    # -- 导入 ---------------------------------------------------------
    async def ingest_paths(self, paths: list[Path], *, copy_to_uploads: bool = False) -> IngestResult:
        started = time.perf_counter()
        imported: list[dict] = []
        skipped: list[str] = []
        for path in paths:
            path = Path(path)
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                skipped.append(f"{path.name}：不支持的格式")
                continue
            target = path
            if copy_to_uploads:
                target = self.settings.uploads_dir / path.name
                shutil.copy2(path, target)
            try:
                document = parse_document(target, settings=self.settings)
            except Exception as exc:  # noqa: BLE001 - 单个文件失败不影响整批
                skipped.append(f"{path.name}：{exc}")
                continue
            if not document.chunks:
                skipped.append(f"{path.name}：没有解析出正文")
                continue
            vectors = self.embedder.encode_documents([chunk.text for chunk in document.chunks])
            self.store.upsert_document(document, vectors)
            TRACER.record(
                "seekdb.upsert_document" if self.store.name == "seekdb" else "sqlite.upsert_document",
                {
                    "doc_id": document.doc_id,
                    "chunks": document.n_chunks,
                    "chars": sum(chunk.chars for chunk in document.chunks),
                    "vector_dim": int(vectors.shape[1]) if getattr(vectors, "ndim", 0) == 2 else self.dimension,
                },
            )
            imported.append(
                {
                    "doc_id": document.doc_id,
                    "title": document.title,
                    "kind": document.kind,
                    "chunks": document.n_chunks,
                    "tags": document.tags,
                    "year": document.year,
                }
            )
        if self.memory is not None and imported:
            await self.memory.ensure_topics(self.store.list_documents())
        return IngestResult(imported=imported, skipped=skipped, elapsed_ms=(time.perf_counter() - started) * 1000)

    async def ingest_sample(self) -> IngestResult:
        sample_dir = PROJECT_ROOT / "sample_library"
        paths = sorted(
            path for path in sample_dir.iterdir() if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
        )
        return await self.ingest_paths(paths)

    async def delete_document(self, doc_id: str) -> None:
        self.store.delete_document(doc_id)
        TRACER.record("seekdb.delete_document" if self.store.name == "seekdb" else "sqlite.delete_document", {"doc_id": doc_id})
        if self.memory is not None:
            await self.memory.refresh()

    async def reset(self) -> dict:
        self.store.reset()
        # 记忆通过新建 scope 重置：旧 scope 的数据仍然保留，方便回看历史
        self.runtime.scope_key = f"{self.settings.scope_key}-{int(time.time())}"
        scope_file = self.runtime.scope_file
        if scope_file.is_file():
            scope_file.unlink()
        scope_id = await self.runtime.ensure_scope()
        self.memory = LearningMemory(self.runtime.client, scope_id, quota=self.settings.daily_quota)
        await self.memory.refresh()
        TRACER.record("wengu.reset", {"new_scope": scope_id})
        return {"scope_id": scope_id, "store": self.store.stats()}

    # -- 检索问答 -----------------------------------------------------
    async def ask(
        self,
        question: str,
        *,
        tags: list[str] | None = None,
        kind: str = "",
        year_min: int | None = None,
        top_k: int = 8,
    ) -> dict:
        if self.memory is None:
            await self.start()
        assert self.memory is not None
        started = time.perf_counter()
        filters = Filters(tags=tags or [], kind=kind or "", year_min=year_min)
        documents = self.store.list_documents()
        doc_meta = {str(doc.get("doc_id")): {"tags": doc.get("tags") or [], "title": doc.get("title")} for doc in documents}
        # 只有「和当前问题相关」的薄弱点才参与加权，避免把无关的薄弱文档硬塞进结果
        question_features = features(question)
        weak_docs: set[str] = set()
        weak_tags: set[str] = set()
        for weak in self.memory.state.weak_titles():
            doc_id = weak["doc_id"]
            meta = doc_meta.get(doc_id, {})
            haystack = f"{weak['title']} {' '.join(meta.get('tags') or [])}"
            if question_features & features(haystack):
                weak_docs.add(doc_id)
                weak_tags.update(meta.get("tags") or [])
        results, search_trace = hybrid_search(
            self.store,
            self.embedder,
            question,
            filters=filters,
            top_k=top_k,
            weak_docs=weak_docs,
            weak_tags=weak_tags,
            doc_meta=doc_meta,
        )
        # 标签过滤在应用层做（seekdb 的元数据过滤是精确匹配，标签是多值字符串）
        if tags:
            wanted = {tag.lower() for tag in tags}
            results = [item for item in results if wanted & {tag.lower() for tag in doc_meta.get(item.doc_id, {}).get("tags", [])}]
        if self.store.name == "seekdb" and hasattr(self.store, "native_hybrid") and results:
            try:
                t0 = time.perf_counter()
                preview = self.store.native_hybrid(
                    question,
                    self.embedder.encode_query(question),
                    max(top_k, 5),
                    filters,
                )
                search_trace.timings_ms["native_hybrid"] = (time.perf_counter() - t0) * 1000
                search_trace.fused[0]["native_hybrid_preview"] = preview[:5]
            except Exception as exc:  # noqa: BLE001 - 交叉验证失败不影响主结果
                TRACER.record("seekdb.native_hybrid_error", {"error": str(exc)[:200]})
        answer = compose_extractive_answer(question, results, limit=3)
        cites = citations_from_blocks(answer.get("blocks") or []) or citations(results)
        await self.memory.log_ask(question, cites, [item.doc_id for item in results])
        TRACER.record(
            "retrieval.hybrid",
            {
                "query": question,
                "backend": self.store.name,
                "filters": filters.as_dict(),
                "hits": len(results),
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "vector_ms": round(search_trace.timings_ms.get("vector", 0.0), 2),
                "fulltext_ms": round(search_trace.timings_ms.get("fulltext", 0.0), 2),
            },
        )
        return {
            "question": question,
            "answer": answer,
            "results": [item.as_dict() for item in results],
            "citations": cites,
            "trace": search_trace.as_dict(),
            "weak_topics": self.memory.state.weak_titles(),
            "timing_ms": round((time.perf_counter() - started) * 1000, 2),
        }

    # -- 复习 ---------------------------------------------------------
    async def review_session(self, quota: int | None = None) -> dict:
        if self.memory is None:
            await self.start()
        assert self.memory is not None
        await self.memory.refresh()
        documents = self.store.list_documents()
        quota = quota or int(self.memory.state.profile.get("daily_quota") or self.settings.daily_quota)
        items = build_session(
            self.memory.state,
            self.store,
            documents,
            quota=quota,
            curated=self.curated,
        )
        TRACER.record(
            "coach.build_session",
            {"items": len(items), "quota": quota, "weak_topics": len(self.memory.state.weak_docs)},
        )
        return {
            "items": [item.as_dict() for item in items],
            "quota": quota,
            "profile": self.memory.state.profile,
            "topics": self.memory.snapshot()["topics"],
            "weak": self.memory.state.weak_titles(),
        }

    async def grade(self, doc_id: str, grade: str, question: str = "") -> dict:
        if self.memory is None:
            await self.start()
        assert self.memory is not None
        topic = self.memory.state.topics.get(doc_id)
        if topic is None:
            title = doc_id
            for doc in self.store.list_documents():
                if str(doc.get("doc_id")) == doc_id:
                    title = str(doc.get("title", doc_id))
                    break
            topic = TopicState(doc_id=doc_id, title=title)
        updated = await self.memory.record_review(topic, grade, question)
        TRACER.record(
            "coach.grade",
            {"doc_id": doc_id, "grade": grade, "strength": round(updated.strength, 3), "due": updated.due},
        )
        return {
            "topic": updated.as_payload(),
            "label": GRADE_LABELS.get(grade, grade),
            "weak": updated.is_weak(),
            "due": updated.due,
        }

    async def update_profile(self, **updates) -> dict:
        if self.memory is None:
            await self.start()
        assert self.memory is not None
        profile = await self.memory.save_profile(**updates)
        return {"profile": profile}

    # -- 状态 ---------------------------------------------------------
    def state(self) -> dict:
        store_stats = self.store.stats()
        return {
            "app": "温故 WenGu",
            "version": "0.1.0",
            "started_at": self.started_at,
            "data_dir": str(self.settings.data_dir),
            "store": store_stats,
            "embedder": self.embed_info,
            "memory": {
                **(self.memory.snapshot() if self.memory else {}),
                "counters": TRACER.counters(),
                **(self.runtime.describe()),
            },
            "documents": self.store.list_documents(),
            "events": TRACER.recent(30),
            "quota": self.settings.daily_quota,
        }

    def memory_snapshot(self) -> dict:
        if self.memory is None:
            return {}
        return self.memory.snapshot()

    def tech_snapshot(self) -> dict:
        return {
            "store": self.store.stats(),
            "embedder": self.embed_info,
            "memory": {
                **(self.memory.snapshot() if self.memory else {}),
                **(self.runtime.describe()),
            },
            "counters": TRACER.counters(),
            "events": TRACER.recent(self.settings.trace_limit),
        }

    # -- 验证 ---------------------------------------------------------
    async def run_demo(self, out_dir: Path) -> dict:
        """端到端验证：导入 -> 检索 -> 复习 -> 记忆复用（含服务重启）。"""

        out_dir.mkdir(parents=True, exist_ok=True)
        record: dict = {"started_at": time.strftime("%Y-%m-%d %H:%M:%S"), "steps": []}
        ingest = await self.ingest_sample()
        record["steps"].append({"step": "ingest_sample", **ingest.as_dict()})
        (out_dir / "ingest.json").write_text(
            json.dumps(ingest.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

        stats = self.store.stats()
        record["steps"].append({"step": "store_stats", **{k: v for k, v in stats.items() if k != "checked_at"}})

        questions = [
            "Raft 里一条日志什么时候算已提交？",
            "快照隔离为什么会出现写偏斜？",
            "HNSW 的 ef 参数控制什么？",
        ]
        ask_records = []
        for question in questions:
            result = await self.ask(question, top_k=5)
            ask_records.append(
                {
                    "question": question,
                    "answer_summary": result["answer"]["summary"],
                    "citations": result["citations"][:3],
                    "results": [item for item in result["results"][:5]],
                    "trace": result["trace"],
                }
            )
        (out_dir / "ask.json").write_text(json.dumps(ask_records, ensure_ascii=False, indent=2), encoding="utf-8")
        record["steps"].append({"step": "ask", "questions": len(ask_records)})

        session = await self.review_session()
        assert self.memory is not None
        grades = ["forgot", "vague", "known", "forgot"]
        graded = []
        for index, item in enumerate(session["items"][: len(grades)]):
            result = await self.grade(item["doc_id"], grades[index], item["question"])
            graded.append({"item": item["item_id"], "doc_id": item["doc_id"], "grade": grades[index], **result})
        (out_dir / "review.json").write_text(
            json.dumps({"session": session, "graded": graded}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        record["steps"].append({"step": "review", "items": len(session["items"]), "graded": len(graded)})

        before = self.memory.snapshot()
        history = await self.memory.revision_history(f"TOPIC-{graded[0]['doc_id']}") if graded else []
        (out_dir / "memory_before_restart.json").write_text(
            json.dumps({"snapshot": before, "history": history}, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 重启 PowerContext Server，验证记忆不依赖进程内状态
        scope_before = self.runtime.scope_id
        self.runtime.stop()
        await asyncio.sleep(0.5)
        self.runtime.client = None
        await self.runtime.ensure_scope()
        self.memory = LearningMemory(self.runtime.client, self.runtime.scope_id, quota=self.settings.daily_quota)
        await self.memory.refresh()
        after = self.memory.snapshot()
        same_scope = self.runtime.scope_id == scope_before
        state_reused = len(after["topics"]) >= len(before["topics"]) and bool(after["weak"] or after["topics"])
        record["steps"].append(
            {
                "step": "restart_and_reuse",
                "scope_id": self.runtime.scope_id,
                "topics_before": len(before["topics"]),
                "topics_after": len(after["topics"]),
                "weak_after": [item["doc_id"] for item in after["weak"]],
                "state_reused": state_reused,
                "same_scope": same_scope,
            }
        )
        (out_dir / "memory_after_restart.json").write_text(
            json.dumps({"snapshot": after}, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 重启后再问一次，并用薄弱点加权影响检索
        followup = await self.ask("写偏斜和 MVCC 的关系是什么？", top_k=5)
        record["steps"].append(
            {
                "step": "ask_after_restart",
                "question": followup["question"],
                "weak_boosted": [item["chunk_id"] for item in followup["results"] if item.get("weak_boost", 1.0) > 1.0],
                "citations": followup["citations"][:3],
            }
        )
        (out_dir / "ask_after_restart.json").write_text(
            json.dumps(followup, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        tech = self.tech_snapshot()
        (out_dir / "tech.json").write_text(json.dumps(tech, ensure_ascii=False, indent=2), encoding="utf-8")
        record["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        record["store"] = stats.get("backend")
        record["embedder"] = self.embed_info
        record["score_answer_demo"] = score_answer(
            ["写偏斜", "快照隔离"], "快照隔离不能避免写偏斜，两个事务会各自读到对方没改的数据"
        )
        (out_dir / "demo_summary.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return record
