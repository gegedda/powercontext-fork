from __future__ import annotations

import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer

import pytest

from issuehub.api import make_handler
from issuehub.service import IssueService


@pytest.fixture()
def api_base() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(IssueService()))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
