"""命令行入口：``wengu serve`` / ``wengu ingest`` / ``wengu ask`` / ``wengu demo`` ..."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .tracing import TRACER


def _print(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _service():
    from .service import WenGuService

    return WenGuService()


async def _run_ingest(args) -> int:
    service = _service()
    await service.start()
    try:
        if args.sample:
            result = await service.ingest_sample()
        else:
            paths = [Path(item) for item in args.paths]
            if not paths:
                print("请给出文件路径，或使用 --sample 导入示例文献", file=sys.stderr)
                return 2
            result = await service.ingest_paths(paths, copy_to_uploads=args.copy)
        _print({"ingest": result.as_dict(), "store": service.store.stats()})
        return 0
    finally:
        await service.aclose()


async def _run_ask(args) -> int:
    service = _service()
    await service.start()
    try:
        result = await service.ask(
            args.question,
            tags=args.tags or [],
            kind=args.kind or "",
            year_min=args.year,
            top_k=args.top_k,
        )
        output = {
            "question": result["question"],
            "answer": result["answer"],
            "citations": result["citations"],
            "weak_topics": result["weak_topics"],
            "timings_ms": result["trace"]["timings_ms"],
            "vector_top": result["trace"]["vector_hits"][:5],
            "fulltext_top": result["trace"]["fulltext_hits"][:5],
        }
        _print(output)
        return 0
    finally:
        await service.aclose()


async def _run_review(args) -> int:
    service = _service()
    await service.start()
    try:
        session = await service.review_session(quota=args.quota)
        _print({"items": session["items"], "weak": session["weak"]})
        return 0
    finally:
        await service.aclose()


async def _run_grade(args) -> int:
    service = _service()
    await service.start()
    try:
        result = await service.grade(args.doc_id, args.grade)
        _print(result)
        return 0
    finally:
        await service.aclose()


async def _run_demo(args) -> int:
    service = _service()
    await service.start()
    try:
        record = await service.run_demo(Path(args.out))
        _print(
            {
                "summary": str(Path(args.out) / "demo_summary.json"),
                "store": record.get("store"),
                "steps": [step["step"] for step in record["steps"]],
                "restart": [step for step in record["steps"] if step["step"] == "restart_and_reuse"],
            }
        )
        return 0
    finally:
        await service.aclose()


async def _run_doctor(args) -> int:
    service = _service()
    await service.start()
    try:
        _print(
            {
                "store": service.store.stats(),
                "embedder": service.embed_info,
                "powercontext": service.runtime.describe(),
                "memory_entries": len(service.memory.entries_summary()) if service.memory else 0,
                "documents": len(service.store.list_documents()),
                "events": TRACER.recent(10),
            }
        )
        return 0
    finally:
        await service.aclose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wengu", description="温故 WenGu：文献混合检索 + 复习教练")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="启动 Web 界面")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")

    ingest = sub.add_parser("ingest", help="导入文献")
    ingest.add_argument("paths", nargs="*")
    ingest.add_argument("--sample", action="store_true", help="导入 sample_library 里的示例文献")
    ingest.add_argument("--copy", action="store_true", help="先复制到 data/uploads")

    ask = sub.add_parser("ask", help="检索并给出带出处的回答")
    ask.add_argument("question")
    ask.add_argument("--tags", nargs="*", default=[])
    ask.add_argument("--kind", default="")
    ask.add_argument("--year", type=int, default=None)
    ask.add_argument("--top-k", type=int, default=8)

    review = sub.add_parser("review", help="生成今日复习题")
    review.add_argument("--quota", type=int, default=None)

    grade = sub.add_parser("grade", help="提交一次复习结果")
    grade.add_argument("doc_id")
    grade.add_argument("grade", choices=["forgot", "vague", "known"])

    demo = sub.add_parser("demo", help="端到端验证并写出 records")
    demo.add_argument("--out", default="records")

    sub.add_parser("doctor", help="自检：存储 / 向量模型 / PowerContext 状态")

    args = parser.parse_args(argv)
    if args.command == "serve":
        import uvicorn

        uvicorn.run("wengu.api:app", host=args.host, port=args.port, reload=args.reload)
        return 0
    handlers = {
        "ingest": _run_ingest,
        "ask": _run_ask,
        "review": _run_review,
        "grade": _run_grade,
        "demo": _run_demo,
        "doctor": _run_doctor,
    }
    return asyncio.run(handlers[args.command](args))


if __name__ == "__main__":
    raise SystemExit(main())
