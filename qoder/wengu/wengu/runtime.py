"""PowerContext 运行时：默认在本进程里起一个真实的 Server，也可以连已有服务。

- 默认（``WENGU_POWERCONTEXT_URL`` 为空）：``create_server_app`` + uvicorn，随机端口，SQLite 存储；
- ``WENGU_PC_DB=seekdb``：PowerContext 自己的记忆也落到 seekdb（Linux 可用时）；
- 配了 ``WENGU_POWERCONTEXT_URL``：不启动进程，直接作为客户端连过去。

无论哪种方式，应用只通过公开的 ``PowerContextClient`` HTTP 客户端读写记忆，
不存在「偷偷改本地文件」的捷径。
"""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import uvicorn

from powercontext.client import PowerContextClient
from powercontext.http import CreateScopeRequest


class PowerContextRuntime:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.directory = Path(settings.pc_data_dir)
        self.external_url = settings.powercontext_url
        self.backend = settings.pc_db
        self.base_url = ""
        self.client: PowerContextClient | None = None
        self.scope_id = ""
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._listener: socket.socket | None = None
        self.scope_file = self.directory / "scope_id.txt"
        self.scope_key = settings.scope_key

    # -- 生命周期 -----------------------------------------------------
    def start(self) -> None:
        if self._thread is not None or self.external_url:
            return
        import os

        self.directory.mkdir(parents=True, exist_ok=True)
        delete_on_close = self.backend != "seekdb"
        from powercontext.builtin.persistence.seekdb import SeekDBConfig
        from powercontext.builtin.persistence.sqlite import SQLiteConfig
        from powercontext.builtin.runtime.config import ExternalSkillsConfig, InferenceConfig, RuntimeConfig
        from powercontext.server.factory import create_server_app
        from powercontext.server.settings import (
            AccessControlConfig,
            BearerAuthConfig,
            HttpConfig,
            McpConfig,
            MetricsConfig,
            ServerSettings,
            TracingConfig,
        )

        if self.backend == "seekdb":
            database = SeekDBConfig(path=self.directory / "powercontext-seekdb", echo=False)
        else:
            database = SQLiteConfig(url=f"sqlite+aiosqlite:///{self.directory / 'powercontext.db'}", echo=False)

        server_settings = ServerSettings(
            workspace=self.directory,
            database=database,
            http=HttpConfig(host="127.0.0.1"),
            auth=BearerAuthConfig(enabled=False),
            access=AccessControlConfig(mode="disabled"),
            inference=InferenceConfig(),
            runtime=RuntimeConfig(schedule_seconds=None, experience_schedule_seconds=None),
            external_skills=ExternalSkillsConfig(),
            mcp=McpConfig(enabled=False),
            metrics=MetricsConfig(enabled=False),
            tracing=TracingConfig(enabled=False),
        )
        os.environ.setdefault("POWERCONTEXT_DISABLE_SCHEDULER", "1")
        app = create_server_app(settings=server_settings, scheduler_path=self.directory / "scheduler.db")

        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        self._listener = listener
        self.base_url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False, lifespan="on"))
        self._server = server
        self._thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 90
        while self._thread.is_alive() and not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        if not server.started:
            self.stop()
            raise RuntimeError("PowerContext Server 启动失败（90 秒内未就绪）")
        self.client = PowerContextClient(self.base_url, timeout=120)
        _ = delete_on_close

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=30)
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass
        if self.client is not None:
            try:
                self.client.close()
            except Exception:  # noqa: BLE001 - 关闭阶段不再抛错
                pass
        self._server = None
        self._thread = None
        self._listener = None
        self.client = None

    def restart(self) -> None:
        self.stop()
        self.start()
        if not self.external_url:
            self.client = PowerContextClient(self.base_url, timeout=120)

    def connect(self) -> PowerContextClient:
        if self.client is not None:
            return self.client
        url = self.external_url
        if not url:
            self.start()
            url = self.base_url
        self.base_url = url
        self.client = PowerContextClient(url, timeout=120)
        return self.client

    # -- Scope --------------------------------------------------------
    async def ensure_scope(self) -> str:
        client = self.connect()
        if self.scope_file.is_file():
            cached = self.scope_file.read_text(encoding="utf-8").strip()
            if cached:
                try:
                    await client.get_scope(cached)
                    self.scope_id = cached
                    return cached
                except Exception:  # noqa: BLE001 - 数据被清掉时重新建
                    pass
        scope = await client.create_scope(
            CreateScopeRequest(
                title=self.settings.scope_title,
                summary=self.settings.scope_summary,
                idempotency_key=self.scope_key,
            )
        )
        self.scope_id = str(scope.scope_id)
        self.scope_file.write_text(self.scope_id, encoding="utf-8")
        return self.scope_id

    def describe(self) -> dict:
        return {
            "base_url": self.base_url or self.external_url,
            "mode": "external" if self.external_url else "in-process",
            "storage": self.backend,
            "scope_id": self.scope_id,
            "data_dir": str(self.directory),
            "server": "powercontext.server.factory.create_server_app",
            "client": "powercontext.client.PowerContextClient",
        }
