"""Start the real PowerContext Server in-process and own its lifecycle.

The Server is the supported integration surface (HTTP API + async client), and
the same database stores both the engineering materials and task state.  The
embedded seekdb backend is selected on Linux/macOS; SQLite keeps the Windows
development loop usable without pretending it is the graded backend.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from pathlib import Path

import uvicorn

from powercontext.builtin.persistence.seekdb import SeekDBConfig
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime.config import ExternalSkillsConfig, InferenceConfig, RuntimeConfig
from powercontext.client import PowerContextClient
from powercontext.http import CreateScopeRequest
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

from . import config


class PowerContextRuntime:
    def __init__(self, backend: str | None = None) -> None:
        self.backend = backend or config.database_backend()
        self.directory = config.data_dir()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.base_url = ""
        self.client: PowerContextClient | None = None
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._listener: socket.socket | None = None

    # -- lifecycle -----------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        database = self._database()
        if os.environ.get("SDD_SQL_ECHO") == "1":
            logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")
            logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)
        settings = ServerSettings(
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
        app = create_server_app(settings=settings, scheduler_path=self.directory / "scheduler.db")
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        self._listener = listener
        self.base_url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False, lifespan="on"))
        self._server = server
        self._thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 60
        while self._thread.is_alive() and not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        if not server.started:
            self.stop()
            raise RuntimeError("PowerContext Server failed to start")
        self.client = PowerContextClient(self.base_url, timeout=180)

    async def aclose(self) -> None:
        if self.client is not None:
            await self.client.aclose()
            self.client = None
        self.stop()

    async def arestart(self) -> None:
        await self.aclose()
        self.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=20)
            if self._thread.is_alive():
                raise RuntimeError("PowerContext Server did not stop within 20 seconds")
        if self._listener is not None:
            self._listener.close()
        self._server = None
        self._thread = None
        self._listener = None

    def restart(self) -> None:
        self.stop()
        self.start()

    # -- data ----------------------------------------------------------
    def _database(self):
        echo = os.environ.get("SDD_SQL_ECHO") == "1"
        if self.backend == "seekdb":
            return SeekDBConfig(path=self.directory / "powercontext-seekdb", echo=echo)
        return SQLiteConfig(url=f"sqlite+aiosqlite:///{self.directory / 'powercontext.db'}", echo=echo)

    async def ensure_scope(self) -> str:
        if self.client is None:
            raise RuntimeError("runtime is not started")
        scope_file = self.directory / "scope_id.txt"
        if scope_file.is_file():
            scope_id = scope_file.read_text(encoding="utf-8").strip()
            try:
                await self.client.get_scope(scope_id)
                return scope_id
            except Exception:
                pass
        scope = await self.client.create_scope(
            CreateScopeRequest(
                title="SDD issuehub context",
                summary="Engineering specs, code, tests and task state for the issuehub SDD demo.",
                idempotency_key=config.scope_key(),
            )
        )
        scope_file.write_text(scope.scope_id, encoding="utf-8")
        return scope.scope_id

    def describe(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "data_dir": str(self.directory),
            "base_url": self.base_url,
            "client": "powercontext.PowerContextClient",
            "server": "powercontext.server.factory.create_server_app",
        }
