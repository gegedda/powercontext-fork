"""FastAPI 应用：界面、JSON 接口、静态资源。"""

from __future__ import annotations

import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import PROJECT_ROOT
from .service import WenGuService

STATIC_DIR = Path(__file__).parent / "static"


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    tags: list[str] = Field(default_factory=list)
    kind: str = ""
    year_min: int | None = None
    top_k: int = 8


class GradeRequest(BaseModel):
    doc_id: str
    grade: str
    question: str = ""


class ProfileRequest(BaseModel):
    nickname: str | None = None
    goal: str | None = None
    style: str | None = None
    daily_quota: int | None = Field(default=None, ge=1, le=20)


@asynccontextmanager
async def lifespan(app: FastAPI):
    service = WenGuService()
    await service.start()
    app.state.service = service
    try:
        yield
    finally:
        await service.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="温故 WenGu", version="0.1.0", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def service() -> WenGuService:
        return app.state.service

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/health")
    async def health() -> dict:
        svc = service()
        return {"ok": True, "store": svc.store.name, "started": svc.started}

    @app.get("/api/state")
    async def state() -> dict:
        return service().state()

    @app.get("/api/memory")
    async def memory() -> dict:
        return service().memory_snapshot()

    @app.get("/api/tech")
    async def tech() -> dict:
        return service().tech_snapshot()

    @app.post("/api/ingest")
    async def ingest(files: list[UploadFile] = File(...)) -> dict:
        svc = service()
        paths: list[Path] = []
        cleanup: list[Path] = []
        for upload in files:
            suffix = Path(upload.filename or "upload.txt").suffix or ".txt"
            handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            handle.write(await upload.read())
            handle.close()
            path = Path(handle.name)
            # 保留原始文件名，doc_id 才能稳定
            target = svc.settings.uploads_dir / f"{Path(upload.filename or 'upload').stem}{suffix}"
            target.write_bytes(path.read_bytes())
            path.unlink(missing_ok=True)
            paths.append(target)
            cleanup.append(target)
        result = await svc.ingest_paths(paths)
        return {**result.as_dict(), "stats": svc.store.stats()}

    @app.post("/api/ingest/sample")
    async def ingest_sample() -> dict:
        svc = service()
        result = await svc.ingest_sample()
        return {**result.as_dict(), "stats": svc.store.stats()}

    @app.delete("/api/doc/{doc_id}")
    async def delete_doc(doc_id: str) -> dict:
        await service().delete_document(doc_id)
        return {"deleted": doc_id}

    @app.post("/api/ask")
    async def ask(request: AskRequest) -> dict:
        svc = service()
        try:
            return await svc.ask(
                request.question,
                tags=request.tags,
                kind=request.kind,
                year_min=request.year_min,
                top_k=request.top_k,
            )
        except Exception as exc:  # noqa: BLE001 - 让前端看到可读错误
            raise HTTPException(status_code=500, detail=f"检索失败：{exc}") from exc

    @app.get("/api/review")
    async def review() -> dict:
        return await service().review_session()

    @app.post("/api/review/grade")
    async def grade(request: GradeRequest) -> dict:
        return await service().grade(request.doc_id, request.grade, request.question)

    @app.post("/api/profile")
    async def profile(request: ProfileRequest) -> dict:
        return await service().update_profile(**request.model_dump(exclude_none=True))

    @app.post("/api/reset")
    async def reset() -> dict:
        return await service().reset()

    return app


app = create_app()

_ = PROJECT_ROOT  # 保留项目根目录导入，便于包内其它模块复用
