from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from .service import InvalidPriority, IssueService


def _json_response(
    handler: BaseHTTPRequestHandler, status: int, payload: dict[str, object]
) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _first(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name)
    if values:
        return values[0]
    return None


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
            priority = _first(query, "priority")
            assignee = _first(query, "assignee")
            try:
                issues = service.list_issues(
                    status=status, priority=priority, assignee=assignee
                )
            except InvalidPriority:
                _json_response(
                    self,
                    400,
                    {
                        "error": "invalid_priority",
                        "allowed": ["low", "medium", "high"],
                    },
                )
                return
            _json_response(
                self,
                200,
                {"items": [issue.as_dict() for issue in issues], "total": len(issues)},
            )

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

    return Handler
