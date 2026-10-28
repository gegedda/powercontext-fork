from __future__ import annotations

from sdd_context.materials import collect_materials, task_text
from sdd_context.select import select, tokenize


class Citation:
    def __init__(self, value: str) -> None:
        self.entry_id = value
        self.entry_version_id = value + "-v1"


class Entry:
    def __init__(self, text: str) -> None:
        self.text = text
        self.citation = Citation(text.splitlines()[0])


def _context() -> dict[str, object]:
    entries = [Entry(material.text) for material in collect_materials()]
    return select(entries, [], task_text())


def test_superseded_spec_is_not_selected() -> None:
    context = _context()
    ids = {item["material_id"] for item in context["specs"]}
    assert not any(str(material_id).startswith("SPEC-090") for material_id in ids)


def test_active_spec_documents_are_selected() -> None:
    context = _context()
    ids = {item["material_id"] for item in context["specs"]}
    assert {"SPEC-101.1", "SPEC-102.1", "SPEC-103.1"} <= ids


def test_code_and_tests_are_actionable() -> None:
    context = _context()
    symbols = {item["symbol"] for item in context["code"]}
    tests = {item["test"] for item in context["tests"]}
    assert "IssueService.list_issues" in symbols
    assert any(item["symbol"] == "Issue" for item in context["code"])
    assert "test_filter_by_priority" in tests
    assert "test_no_filters_returns_all_sorted" in tests


def test_tokenizer_expands_chinese_and_english_terms() -> None:
    terms = tokenize("增加 priority 和 assignee 过滤，非法值返回 400")
    assert "priority" in terms
    assert "assignee" in terms
    assert any("优先" in term for term in terms)
    assert "400" in terms
