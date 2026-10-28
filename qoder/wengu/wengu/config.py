"""集中配置：全部来自环境变量，缺省值保证「开箱能跑」。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


@dataclass(slots=True)
class Settings:
    # 数据目录：seekdb 数据、上传文献、PowerContext 状态都放在这里
    data_dir: Path
    # 知识库后端：auto = 能用 seekdb 就用 seekdb，否则回退 sqlite
    store: str
    seekdb_path: Path
    sqlite_path: Path
    # 向量模型：onnx = 本地 bge-small-zh；hash = 无需模型的特征哈希；api = OpenAI 兼容接口
    embedder: str
    embed_model_dir: Path
    embed_dim: int
    embed_api_base: str
    embed_api_key: str
    embed_api_model: str
    # PowerContext：默认进程内起一个本地 Server（SQLite 存储），也可以连远端
    powercontext_url: str
    pc_db: str
    pc_data_dir: Path
    scope_title: str
    scope_summary: str
    scope_key: str
    # 复习策略
    daily_quota: int = 6
    hybrid_top_k: int = 8
    chunk_size: int = 360
    chunk_overlap: int = 60
    # 界面
    app_title: str = "温故 WenGu"
    trace_limit: int = 60
    extra: dict = field(default_factory=dict)

    @property
    def library_dir(self) -> Path:
        return self.data_dir / "library"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.library_dir, self.uploads_dir, self.embed_model_dir.parent):
            path.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    root = Path(_env("WENGU_DATA_DIR", str(PROJECT_ROOT / "data"))).expanduser()
    if not root.is_absolute():
        root = (PROJECT_ROOT / root).resolve()
    model_dir = Path(
        _env("WENGU_EMBED_MODEL_DIR", str(root / "models" / "bge-small-zh-v1.5"))
    ).expanduser()
    if not model_dir.is_absolute():
        model_dir = (PROJECT_ROOT / model_dir).resolve()
    settings = Settings(
        data_dir=root,
        store=_env("WENGU_STORE", "auto").lower(),
        seekdb_path=root / "seekdb",
        sqlite_path=root / "wengu.sqlite3",
        embedder=_env("WENGU_EMBEDDER", "auto").lower(),
        embed_model_dir=model_dir,
        embed_dim=_env_int("WENGU_EMBED_DIM", 512),
        embed_api_base=_env("WENGU_EMBED_API_BASE"),
        embed_api_key=_env("WENGU_EMBED_API_KEY"),
        embed_api_model=_env("WENGU_EMBED_API_MODEL", "text-embedding-3-small"),
        powercontext_url=_env("WENGU_POWERCONTEXT_URL"),
        pc_db=_env("WENGU_PC_DB", "sqlite").lower(),
        pc_data_dir=root / "powercontext",
        scope_title=_env("WENGU_SCOPE_TITLE", "温故 WenGu · 学习记忆"),
        scope_summary=_env(
            "WENGU_SCOPE_SUMMARY",
            "文献检索与复习教练的长期记忆：学习偏好、薄弱知识点、复习进度与提问历史。",
        ),
        scope_key=_env("WENGU_SCOPE_KEY", "wengu-default-scope"),
        daily_quota=_env_int("WENGU_DAILY_QUOTA", 6),
        hybrid_top_k=_env_int("WENGU_HYBRID_TOP_K", 8),
        chunk_size=_env_int("WENGU_CHUNK_SIZE", 360),
        chunk_overlap=_env_int("WENGU_CHUNK_OVERLAP", 60),
        trace_limit=_env_int("WENGU_TRACE_LIMIT", 60),
    )
    settings.ensure_dirs()
    return settings
