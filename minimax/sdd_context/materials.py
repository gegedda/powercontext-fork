"""Turn specs, code symbols and tests into addressable material chunks."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import config

MAX_TEXT_BYTES = 8192


@dataclass(slots=True)
class Material:
    material_id: str
    kind: str
    title: str
    path: str
    symbol: str = ""
    start_line: int = 1
    end_line: int = 1
    tags: tuple[str, ...] = ()
    applies_to: str = ""
    status: str = "active"
    body: str = ""
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def text(self) -> str:
        header = [
            f"MATERIAL {self.material_id}",
            f"KIND {self.kind}",
            f"TITLE {self.title}",
            f"PATH {self.path}",
            f"SYMBOL {self.symbol}",
            f"LINES {self.start_line}-{self.end_line}",
            f"TAGS {','.join(self.tags)}",
            f"APPLIES_TO {self.applies_to}",
            f"STATUS {self.status}",
            "---",
            self.body.strip(),
        ]
        raw = "\n".join(header).encode("utf-8")
        if len(raw) <= MAX_TEXT_BYTES:
            return raw.decode("utf-8")
        clipped = raw[: MAX_TEXT_BYTES - 48].decode("utf-8", errors="ignore").rstrip()
        return clipped + "\n... [material truncated to 8 KiB]\n"

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    def citation(self) -> dict[str, object]:
        return {
            "material_id": self.material_id,
            "kind": self.kind,
            "path": self.path,
            "symbol": self.symbol,
            "start_line": self.start_line,
            "end_line": self.end_line,
        }


def _front_matter(text: str) -> tuple[dict[str, object], str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    raw = text[3:end].strip()
    body = text[end + 4 :].lstrip("\n")
    meta: dict[str, object] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip()
        if value.startswith("[") and value.endswith("]"):
            meta[key] = tuple(item.strip() for item in value[1:-1].split(",") if item.strip())
        else:
            meta[key] = value
    return meta, body


def _specs() -> list[Material]:
    materials: list[Material] = []
    for path in sorted((config.MATERIALS_DIR / "specs").glob("*.md")):
        meta, body = _front_matter(path.read_text(encoding="utf-8"))
        spec_id = str(meta.get("id", path.stem))
        tags = tuple(meta.get("tags", ()))
        full_text = path.read_text(encoding="utf-8")
        sections = re.split(r"(?m)^##\s+", body)
        preamble = sections[0].strip()
        chunks: list[tuple[str, str, str]] = []
        if preamble:
            chunks.append((spec_id, str(meta.get("title", path.stem)), preamble))
        for section in sections[1:]:
            heading, _, rest = section.partition("\n")
            section_id = heading.split()[0] if heading.split() else spec_id
            chunks.append((section_id, heading.strip(), f"## {heading}\n{rest.strip()}"))
        for section_id, title, chunk in chunks:
            start, end = _line_span(full_text, chunk)
            materials.append(
                Material(
                    material_id=section_id,
                    kind="spec",
                    title=title,
                    path=str(path.relative_to(config.REPO_ROOT)).replace("\\", "/"),
                    tags=tags,
                    applies_to=str(meta.get("applies_to", "")),
                    status=str(meta.get("status", "active")),
                    body=chunk,
                    start_line=start,
                    end_line=end,
                )
            )
    return materials


def _line_span(full_text: str, chunk: str) -> tuple[int, int]:
    probe = chunk.strip().splitlines()[0][:80] if chunk.strip() else ""
    index = full_text.find(probe) if probe else -1
    if index < 0:
        return 1, max(1, chunk.count("\n") + 1)
    start = full_text[:index].count("\n") + 1
    return start, start + chunk.count("\n")


def _symbols(path: Path, source: str) -> list[tuple[str, int, int, str]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    found: list[tuple[str, int, int, str]] = []

    def add(node: ast.AST, name: str) -> None:
        start = getattr(node, "lineno", 1)
        end = getattr(node, "end_lineno", start)
        found.append((name, start, end, ast.get_source_segment(source, node) or ""))

    def visit_body(nodes: list[ast.stmt], prefix: str = "") -> None:
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                add(node, f"{prefix}{node.name}")
            elif isinstance(node, ast.ClassDef):
                methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                decorators = [ast.unparse(decorator) for decorator in node.decorator_list]
                if not methods or any("dataclass" in decorator for decorator in decorators):
                    add(node, f"{prefix}{node.name}")
                for method in methods:
                    add(method, f"{node.name}.{method.name}")

    visit_body(tree.body)
    return found


def _code() -> list[Material]:
    materials: list[Material] = []
    for path in sorted((config.DEMO_DIR / "issuehub").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        rel = str(path.relative_to(config.REPO_ROOT)).replace("\\", "/")
        for name, start, end, snippet in _symbols(path, source):
            materials.append(
                Material(
                    material_id=f"CODE-{path.stem}-{name.replace('.', '-')}",
                    kind="code",
                    title=f"{path.stem}.{name}",
                    path=rel,
                    symbol=name,
                    start_line=start,
                    end_line=end,
                    tags=("code", path.stem),
                    body=snippet,
                )
            )
    return materials


def _tests() -> list[Material]:
    materials: list[Material] = []
    for path in sorted((config.DEMO_DIR / "tests").glob("test_*.py")):
        source = path.read_text(encoding="utf-8")
        rel = str(path.relative_to(config.REPO_ROOT)).replace("\\", "/")
        target = "target" if "filter" in path.stem else "regression"
        for name, start, end, snippet in _symbols(path, source):
            if not name.startswith("test_"):
                continue
            materials.append(
                Material(
                    material_id=f"TEST-{name}",
                    kind="test",
                    title=name,
                    path=rel,
                    symbol=name,
                    start_line=start,
                    end_line=end,
                    tags=(target, "test"),
                    body=snippet,
                )
            )
    return materials


def _task() -> list[Material]:
    materials: list[Material] = []
    for path in sorted((config.MATERIALS_DIR / "tasks").glob("*.md")):
        meta, body = _front_matter(path.read_text(encoding="utf-8"))
        materials.append(
            Material(
                material_id=str(meta.get("id", path.stem)),
                kind="task",
                title=str(meta.get("title", path.stem)),
                path=str(path.relative_to(config.REPO_ROOT)).replace("\\", "/"),
                tags=("task",),
                applies_to=str(meta.get("project", "")),
                status="active",
                body=body,
            )
        )
    return materials


def collect_materials() -> list[Material]:
    materials = _specs() + _code() + _tests() + _task()
    seen: set[str] = set()
    unique: list[Material] = []
    for material in materials:
        if material.material_id in seen:
            continue
        seen.add(material.material_id)
        unique.append(material)
    return unique


def parse_entry_text(text: str) -> dict[str, object]:
    """Parse the header written by :pyattr:`Material.text`."""

    lines = text.splitlines()
    meta: dict[str, object] = {}
    body_start = 0
    for index, line in enumerate(lines):
        if line.strip() == "---":
            body_start = index + 1
            break
        if " " in line:
            key, value = line.split(" ", 1)
            meta[key.lower()] = value
    start, _, end = str(meta.get("lines", "1-1")).partition("-")
    try:
        meta["start_line"] = int(start)
        meta["end_line"] = int(end)
    except ValueError:
        meta["start_line"] = 1
        meta["end_line"] = 1
    meta["tags"] = tuple(tag for tag in str(meta.get("tags", "")).split(",") if tag)
    meta["body"] = "\n".join(lines[body_start:]).strip()
    return meta


def task_text() -> str:
    path = config.MATERIALS_DIR / "tasks" / "TASK-001.md"
    _, body = _front_matter(path.read_text(encoding="utf-8"))
    return body.strip()


def context_as_json(context: dict[str, object]) -> str:
    return json.dumps(context, ensure_ascii=False, indent=2)
