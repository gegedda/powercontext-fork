"""Existing behaviour that TASK-001 must not change."""

from __future__ import annotations

from issuehub.testing import get_json


def test_no_filters_returns_all_sorted(api_base: str) -> None:
    status, payload = get_json(api_base, "/issues")

    assert status == 200
    assert [item["id"] for item in payload["items"]] == [1, 2, 3, 4, 5, 6]
    assert payload["total"] == 6


def test_status_filter_still_works(api_base: str) -> None:
    status, payload = get_json(api_base, "/issues?status=open")

    assert status == 200
    assert [item["id"] for item in payload["items"]] == [1, 2, 5]


def test_unknown_issue_returns_404(api_base: str) -> None:
    status, payload = get_json(api_base, "/issues/999")

    assert status == 404
    assert payload == {"error": "not_found"}


def test_issue_shape_is_unchanged(api_base: str) -> None:
    status, payload = get_json(api_base, "/issues/1")

    assert status == 200
    assert payload == {
        "id": 1,
        "title": "Login page returns 500",
        "status": "open",
        "priority": "high",
        "assignee": "alice",
    }
