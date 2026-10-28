"""Domain models for the small issue tracker used by the SDD demo."""

from __future__ import annotations

from dataclasses import dataclass

VALID_STATUSES = ("open", "in_progress", "closed")
VALID_PRIORITIES = ("low", "medium", "high")


@dataclass(frozen=True, slots=True)
class Issue:
    id: int
    title: str
    status: str = "open"
    priority: str = "medium"
    assignee: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "priority": self.priority,
            "assignee": self.assignee,
        }


DEFAULT_ISSUES = (
    Issue(1, "Login page returns 500", status="open", priority="high", assignee="alice"),
    Issue(2, "Add pagination to search", status="open", priority="low", assignee="bob"),
    Issue(3, "Fix typo in README", status="closed", priority="low", assignee="alice"),
    Issue(4, "Audit log retention", status="in_progress", priority="high", assignee="carol"),
    Issue(5, "Export CSV", status="open", priority="medium", assignee="bob"),
    Issue(6, "Slow dashboard query", status="in_progress", priority="medium", assignee=None),
)
