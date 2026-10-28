from __future__ import annotations

from .models import DEFAULT_ISSUES, Issue

ALLOWED_PRIORITIES = ("low", "medium", "high")


class InvalidPriority(ValueError):
    """Raised when a requested priority is not supported."""

    allowed = ["low", "medium", "high"]


class IssueService:
    def __init__(self, issues: tuple[Issue, ...] | None = None) -> None:
        self._issues = issues if issues is not None else DEFAULT_ISSUES

    def list_issues(
        self,
        *,
        status: str | None = None,
        priority: str | None = None,
        assignee: str | None = None,
    ) -> list[Issue]:
        """Return issues matching all supplied filters, ordered by id."""

        if priority is not None and priority not in ALLOWED_PRIORITIES:
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
        for issue in self._issues:
            if issue.id == issue_id:
                return issue
        return None
