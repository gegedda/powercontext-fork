"""A tiny stdlib HTTP API around :class:`IssueService` (pre-TASK-001 baseline)."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .service import IssueService


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def make_handler(service: IssueService) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
            parsed = urlparse(self.path)
            if parsed.path == "/issues":
                self._list_issues(parsed.query)
                return
            if parsed.path.startswith("/issues/"):
                suffix = parsed.path.removeprefix("/issues/")
                if suffix.isdigit():
                    issue = service.get_issue(int(suffix))
                    if issue is None:
                        _json_response(self, 404, {"error": "not_found"})
                    else:
                        _json_response(self, 200, issue.as_dict())
                    return
            _json_response(self, 404, {"error": "not_found"})

        def _list_issues(self, raw_query: str) -> None:
            query = parse_qs(raw_query, keep_blank_values=False)
            status = _first(query, "status")
            issues = service.list_issues(status=status)
            _json_response(self, 200, {"items": [issue.as_dict() for issue in issues], "total": len(issues)})

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

    return Handler


def _first(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name)
    return values[0] if values else None


def run_server(host: str = "127.0.0.1", port: int = 8766, service: IssueService | None = None) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(service or IssueService()))
    try:
        server.serve_forever()
    finally:
        server.server_close()
