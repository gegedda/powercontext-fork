"""Application service for the issue tracker (pre-TASK-001 baseline)."""

from __future__ import annotations

from collections.abc import Iterable

from .models import DEFAULT_ISSUES, Issue


class InvalidPriority(ValueError):
    """Reserved for the TASK-001 validation path; unused in this baseline."""


class IssueService:
    def __init__(self, issues: Iterable[Issue] | None = None) -> None:
        self._issues = tuple(DEFAULT_ISSUES if issues is None else issues)

    def list_issues(self, *, status: str | None = None) -> list[Issue]:
        """Return issues matching the status filter, ordered by id."""

        selected = self._issues
        if status is not None:
            selected = tuple(issue for issue in selected if issue.status == status)
        return sorted(selected, key=lambda issue: issue.id)

    def get_issue(self, issue_id: int) -> Issue | None:
        return next((issue for issue in self._issues if issue.id == issue_id), None)
