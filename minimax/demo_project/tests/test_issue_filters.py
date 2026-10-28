"""Target behaviour for the TASK-001 change: add priority and assignee filters."""

from __future__ import annotations

from issuehub.testing import get_json


def test_filter_by_priority(api_base: str) -> None:
    status, payload = get_json(api_base, "/issues?priority=high")

    assert status == 200
    assert [item["id"] for item in payload["items"]] == [1, 4]
    assert payload["total"] == 2


def test_filter_by_assignee_and_priority(api_base: str) -> None:
    status, payload = get_json(api_base, "/issues?assignee=alice&priority=high")

    assert status == 200
    assert [item["id"] for item in payload["items"]] == [1]


def test_priority_combines_with_status(api_base: str) -> None:
    status, payload = get_json(api_base, "/issues?status=open&priority=low")

    assert status == 200
    assert [item["id"] for item in payload["items"]] == [2]


def test_invalid_priority_returns_400(api_base: str) -> None:
    status, payload = get_json(api_base, "/issues?priority=urgent")

    assert status == 400
    assert payload == {"error": "invalid_priority", "allowed": ["low", "medium", "high"]}
