"""Select the currently valid specs, code and tests for a development task."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .materials import parse_entry_text

STOPWORDS = {
    "a",
    "an",
    "and",
    "the",
    "to",
    "of",
    "in",
    "on",
    "for",
    "with",
    "is",
    "are",
    "be",
    "this",
    "that",
    "it",
    "as",
    "by",
    "or",
    "get",
    "http",
    "the",
    "和",
    "的",
    "了",
    "在",
    "与",
    "及",
}

SYNONYMS = {
    "priority": ("优先", "优先级", "priority"),
    "assignee": ("负责人", "指派", "assignee"),
    "filter": ("过滤", "筛选", "filter"),
    "invalid": ("非法", "无效", "validation", "400"),
    "compatibility": ("兼容", "回归", "regression"),
    "default": ("默认", "无过滤", "all"),
    "test": ("测试", "pytest", "test"),
    "spec": ("规格", "需求", "spec"),
}


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for chunk in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", text.lower()):
        if chunk[0].isascii():
            if chunk not in STOPWORDS and len(chunk) > 1:
                tokens.append(chunk)
            continue
        if chunk in STOPWORDS:
            continue
        tokens.append(chunk)
        if len(chunk) > 2:
            tokens.extend(chunk[index : index + 2] for index in range(len(chunk) - 1))
    expanded: list[str] = []
    for token in tokens:
        expanded.append(token)
        for canonical, variants in SYNONYMS.items():
            if token == canonical or token in variants:
                expanded.extend(variants)
                expanded.append(canonical)
    return list(dict.fromkeys(token for token in expanded if token and token not in STOPWORDS))


@dataclass(slots=True)
class Candidate:
    entry: object
    meta: dict[str, object]
    score: float
    matched: list[str]


def _candidate(entry) -> Candidate | None:
    meta = parse_entry_text(entry.text)
    if meta.get("status") == "superseded":
        return None
    if meta.get("kind") not in {"spec", "code", "test"}:
        return None
    return Candidate(entry=entry, meta=meta, score=0.0, matched=[])


def _score(candidate: Candidate, terms: list[str], task: str) -> None:
    meta = candidate.meta
    haystack = " ".join(
        str(meta.get(key, "")) for key in ("material", "title", "path", "symbol", "tags", "kind")
    ).lower()
    body = str(meta.get("body", "")).lower()
    score = 0.0
    matched: list[str] = []
    for term in terms:
        if term in haystack:
            score += 4.0
            matched.append(term)
        elif term in body:
            score += 1.2
            matched.append(term)
    if meta.get("kind") == "spec":
        score *= 1.25
    if meta.get("kind") == "test":
        score *= 1.1
    symbol = str(meta.get("symbol", ""))
    if symbol.endswith("list_issues"):
        score += 9.0
        matched.append("list_issues")
    if symbol == "Issue":
        score += 8.0
    if meta.get("kind") == "test":
        if "status" in symbol and "status" in task.lower():
            score += 12.0
        if ("no_filters" in symbol or "all" in symbol) and any(word in task.lower() for word in ("默认", "default", "all")):
            score += 5.0
        if "404" in symbol and "404" not in task:
            score -= 3.0
    if "issuehub" in str(meta.get("applies_to", "")).lower():
        score += 2.0
    if "priority" in task.lower() and symbol.endswith("list_issues"):
        score += 2.0
    if "assignee" in task.lower() and symbol.endswith("list_issues"):
        score += 1.0
    candidate.score = round(score, 3)
    candidate.matched = list(dict.fromkeys(matched))


def select(entries, hits, task: str) -> dict[str, object]:
    terms = tokenize(task)
    hit_ids = {hit.citation.entry_id for hit in hits}
    candidates: list[Candidate] = []
    for entry in entries:
        candidate = _candidate(entry)
        if candidate is None:
            continue
        _score(candidate, terms, task)
        if candidate.entry.citation.entry_id in hit_ids:
            candidate.score += 1.5
            candidate.matched.append("retrieval_hit")
        candidate.score = round(candidate.score, 3)
        candidates.append(candidate)

    spec_candidates = [c for c in candidates if c.meta.get("kind") == "spec"]
    groups: dict[str, list[Candidate]] = {}
    for candidate in spec_candidates:
        group = str(candidate.meta.get("material", "")).split(".")[0]
        groups.setdefault(group, []).append(candidate)
    ranked_groups = sorted(
        groups.items(),
        key=lambda item: (-max(candidate.score for candidate in item[1]), item[0]),
    )
    chosen_specs: list[Candidate] = []
    for _, sections in ranked_groups[:3]:
        chosen_specs.extend(sorted(sections, key=lambda candidate: str(candidate.meta.get("material"))))

    code = sorted(
        (c for c in candidates if c.meta.get("kind") == "code"),
        key=lambda c: (-c.score, str(c.meta.get("path")), int(c.meta.get("start_line", 0))),
    )
    tests = sorted((c for c in candidates if c.meta.get("kind") == "test"), key=lambda c: (-c.score, str(c.meta.get("title"))))

    target_tests = [c for c in tests if "target" in c.meta.get("tags", ())]
    regression_tests = [c for c in tests if "regression" in c.meta.get("tags", ())]
    chosen_tests = target_tests[:4] + regression_tests[:2]

    return {
        "specs": [_spec_view(c) for c in chosen_specs],
        "code": [_code_view(c) for c in code[:4]],
        "tests": [_test_view(c) for c in chosen_tests[:6]],
        "selection": {
            "query_terms": terms[:40],
            "candidate_count": len(candidates),
            "chosen_count": len(chosen_specs) + min(4, len(code)) + min(6, len(chosen_tests)),
        },
    }


def _spec_view(candidate: Candidate) -> dict[str, object]:
    return {
        "material_id": candidate.meta.get("material"),
        "title": candidate.meta.get("title"),
        "path": candidate.meta.get("path"),
        "lines": [candidate.meta.get("start_line"), candidate.meta.get("end_line")],
        "status": candidate.meta.get("status"),
        "tags": list(candidate.meta.get("tags", ())),
        "score": candidate.score,
        "matched": candidate.matched[:12],
        "text": candidate.meta.get("body"),
    }


def _code_view(candidate: Candidate) -> dict[str, object]:
    return {
        "material_id": candidate.meta.get("material"),
        "path": candidate.meta.get("path"),
        "symbol": candidate.meta.get("symbol"),
        "lines": [candidate.meta.get("start_line"), candidate.meta.get("end_line")],
        "score": candidate.score,
        "matched": candidate.matched[:12],
        "reason": "highest task overlap among currently valid code symbols",
        "text": candidate.meta.get("body"),
    }


def _test_view(candidate: Candidate) -> dict[str, object]:
    return {
        "material_id": candidate.meta.get("material"),
        "path": candidate.meta.get("path"),
        "test": candidate.meta.get("symbol"),
        "lines": [candidate.meta.get("start_line"), candidate.meta.get("end_line")],
        "tags": list(candidate.meta.get("tags", ())),
        "score": candidate.score,
        "matched": candidate.matched[:12],
        "command": "python -m pytest demo_project/tests -q",
        "text": candidate.meta.get("body"),
    }


def sources(context: dict[str, object], entries) -> list[dict[str, object]]:
    by_id = {entry.citation.entry_id: entry for entry in entries}
    seen: set[str] = set()
    rows: list[dict[str, object]] = []
    for section in ("specs", "code", "tests"):
        for item in context.get(section, []):
            material_id = str(item.get("material_id", ""))
            entry = next((e for e in by_id.values() if f"MATERIAL {material_id}" in e.text.splitlines()[0]), None)
            if entry is None or entry.citation.entry_id in seen:
                continue
            seen.add(entry.citation.entry_id)
            rows.append(
                {
                    "material_id": material_id,
                    "memory_entry_id": entry.citation.entry_id,
                    "entry_version_id": entry.citation.entry_version_id,
                    "path": item.get("path"),
                    "symbol": item.get("symbol") or item.get("test"),
                    "lines": item.get("lines"),
                }
            )
    return rows


def render_markdown(context: dict[str, object]) -> str:
    task = context["task"]
    lines = [
        f"# Development context — {task['id']}",
        "",
        f"**Task:** {task['title']}",
        "",
        task["text"],
        "",
        f"**Backend:** {context['runtime']['backend']}  ",
        f"**Scope:** `{context['scope_id']}`",
        "",
        "## Applicable specifications",
        "",
    ]
    for spec in context["specs"]:
        lines += [
            f"### {spec['material_id']} — {spec['title']}",
            f"Source: `{spec['path']}` lines {spec['lines'][0]}–{spec['lines'][1]}  ",
            f"Status: {spec['status']} · score {spec['score']}",
            "",
            str(spec["text"]),
            "",
        ]
    lines += ["## Code to change", ""]
    for item in context["code"]:
        lines += [
            f"### `{item['symbol']}` — `{item['path']}`",
            f"Lines {item['lines'][0]}–{item['lines'][1]} · score {item['score']}",
            "",
            "```python",
            str(item["text"]),
            "```",
            "",
        ]
    lines += ["## Verification tests", ""]
    for item in context["tests"]:
        lines += [
            f"- `{item['test']}` ({', '.join(item['tags'])}) — `{item['path']}` lines "
            f"{item['lines'][0]}–{item['lines'][1]}",
        ]
    lines += ["", f"Run: `{context['tests'][0]['command'] if context['tests'] else 'pytest'}`", ""]
    state = context.get("state") or {}
    lines += ["## Persisted task state", "", f"Status: **{state.get('status', 'not_started')}**", ""]
    if state.get("completed"):
        lines.append("Completed: " + "; ".join(str(item) for item in state["completed"]))
    if state.get("todo"):
        lines.append("Todo: " + "; ".join(str(item) for item in state["todo"]))
    if state.get("verification"):
        lines.append(f"Verification: `{state['verification']}`")
    lines += ["", "## Source citations", ""]
    for source in context["sources"]:
        lines.append(
            f"- `{source['material_id']}` → `{source['path']}` "
            f"(memory entry `{source['memory_entry_id']}`, version `{source['entry_version_id']}`)"
        )
    return "\n".join(lines).rstrip() + "\n"
