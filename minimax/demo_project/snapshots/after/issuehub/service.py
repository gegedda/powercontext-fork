"""Application service for the issue tracker.

The HTTP layer stays thin: query parsing belongs to ``api.py`` and all filtering
rules live here so that they can be unit tested without a server.
"""

from __future__ import annotations

from collections.abc import Iterable

from .models import DEFAULT_ISSUES, Issue


class InvalidPriority(ValueError):
    """Raised when a caller asks for a priority outside the supported set."""


class IssueService:
    def __init__(self, issues: Iterable[Issue] | None = None) -> None:
        self._issues = tuple(DEFAULT_ISSUES if issues is None else issues)

    def list_issues(
        self,
        *,
        status: str | None = None,
        priority: str | None = None,
        assignee: str | None = None,
    ) -> list[Issue]:
        """Return issues matching the supplied filters.

        Filters are combined with AND. The result is always ordered by id so
        that callers can rely on a stable response.
        """

        if priority is not None and priority not in ("low", "medium", "high"):
            raise InvalidPriority(priority)

        selected = self._issues
        if status is not None:
            selected = tuple(issue for issue in selected if issue.status == status)
        if priority is not None:
            selected = tuple(issue for issue in selected if issue.priority == priority)
        if assignee is not None:
            selected = tuple(issue for issue in selected if issue.assignee == assignee)
        return sorted(selected, key=lambda issue: issue.id)

    def get_issue(self, issue_id: int) -> Issue | None:
        return next((issue for issue in self._issues if issue.id == issue_id), None)
