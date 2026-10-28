"""文献解析与切分：MD / TXT / PDF -> 文档元数据 + 可检索片段。

设计目标：
- 切分边界尽量落在标题与小节上，保留「所属小节」作为片段前缀，检索命中后能给出处；
- 同一份文件重复导入时 doc_id 稳定（由文件名 + 内容哈希决定），便于增量更新；
- 不依赖任何外部服务，PDF 用 pypdf 纯 Python 解析。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt", ".pdf"}
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


@dataclass(slots=True)
class Chunk:
    chunk_id: str
    doc_id: str
    index: int
    text: str
    section: str
    page: int | None = None
    chars: int = 0

    def as_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "index": self.index,
            "section": self.section,
            "page": self.page,
            "chars": self.chars,
        }


@dataclass(slots=True)
class Document:
    doc_id: str
    title: str
    path: str
    kind: str
    sha1: str
    abstract: str
    tags: list[str] = field(default_factory=list)
    year: int | None = None
    chunks: list[Chunk] = field(default_factory=list)

    @property
    def n_chunks(self) -> int:
        return len(self.chunks)


def _slug(text: str) -> str:
    text = re.sub(r"\.[^.]+$", "", text.strip().lower())
    text = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "-", text)
    return text.strip("-") or "doc"


def _parse_front_matter(raw: str) -> tuple[dict[str, str], str]:
    match = _FRONT_MATTER_RE.match(raw)
    if not match:
        return {}, raw
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip().lower()] = value.strip().strip("'\"")
    return meta, raw[match.end() :]


def _split_sections(text: str) -> list[tuple[str, str]]:
    """按 Markdown 标题切小节，返回 [(小节标题, 正文)]。"""

    sections: list[tuple[str, list[str]]] = []
    current_title = "正文"
    current_lines: list[str] = []
    for line in text.splitlines():
        heading = _HEADING_RE.match(line)
        if heading:
            body = "\n".join(current_lines).strip()
            if body:
                sections.append((current_title, current_lines))
            current_title = heading.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)
    body = "\n".join(current_lines).strip()
    if body:
        sections.append((current_title, current_lines))
    return [(title, "\n".join(lines).strip()) for title, lines in sections if "\n".join(lines).strip()]


def _split_paragraphs(text: str) -> list[str]:
    parts = re.split(r"\n\s*\n", text)
    return [p.strip() for p in parts if p.strip()]


def chunk_text(
    text: str,
    *,
    doc_id: str,
    chunk_size: int = 360,
    overlap: int = 60,
    page: int | None = None,
    start_index: int = 0,
) -> tuple[list[Chunk], int]:
    """按小节 + 段落累积切块，超长段落再滑窗切分。"""

    chunks: list[Chunk] = []
    index = start_index
    for section_title, body in _split_sections(text):
        buffer = ""
        for paragraph in _split_paragraphs(body):
            paragraph = re.sub(r"[ \t]+", " ", paragraph).strip()
            if not paragraph:
                continue
            if len(buffer) + len(paragraph) + 1 <= chunk_size:
                buffer = f"{buffer}\n{paragraph}".strip()
                continue
            if buffer:
                chunks.append(_make_chunk(doc_id, index, buffer, section_title, page))
                index += 1
                buffer = ""
            if len(paragraph) <= chunk_size:
                buffer = paragraph
                continue
            step = max(chunk_size - overlap, 80)
            for start in range(0, len(paragraph), step):
                piece = paragraph[start : start + chunk_size].strip()
                if not piece:
                    continue
                chunks.append(_make_chunk(doc_id, index, piece, section_title, page))
                index += 1
                if start + chunk_size >= len(paragraph):
                    break
        if buffer:
            chunks.append(_make_chunk(doc_id, index, buffer, section_title, page))
            index += 1
    return chunks, index


def _make_chunk(doc_id: str, index: int, text: str, section: str, page: int | None) -> Chunk:
    # 小节标题作为上下文前缀参与向量化与全文检索，但正文保持原文，便于展示引用
    prefixed = f"【{section}】{text}" if section and section != "正文" else text
    return Chunk(
        chunk_id=f"{doc_id}#{index:03d}",
        doc_id=doc_id,
        index=index,
        text=prefixed,
        section=section,
        page=page,
        chars=len(text),
    )


def _extract_pdf(raw: bytes) -> str:
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw))
    pages = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 - 单页解析失败不应中断整篇
            text = ""
        if text.strip():
            pages.append(f"\n\n<!-- page: {number} -->\n\n{text.strip()}")
    return "".join(pages)


def _parse_sidecar(path: Path) -> dict[str, str]:
    """PDF 等格式自身没有 front matter，可用同名 ``<stem>.meta.json`` 补充元数据。"""

    sidecar = path.parent / f"{Path(path).stem}.meta.json"
    if not sidecar.is_file():
        return {}
    try:
        import json

        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    output: dict[str, str] = {}
    for key, value in data.items():
        if isinstance(value, (list, tuple)):
            output[str(key).lower()] = ",".join(str(item) for item in value)
        else:
            output[str(key).lower()] = str(value)
    return output


def _first_line_title(text: str, limit: int = 60) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip()
        if 2 <= len(stripped) <= limit:
            return stripped
    return ""


def parse_document(path: Path, *, settings) -> Document:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"不支持的文件类型：{suffix}（支持 {sorted(SUPPORTED_SUFFIXES)}）")
    raw_bytes = path.read_bytes()
    sha1 = hashlib.sha1(raw_bytes).hexdigest()
    doc_id = _slug(path.stem)

    if suffix == ".pdf":
        text = _extract_pdf(raw_bytes)
        kind = "pdf"
        meta: dict[str, str] = {}
    else:
        text = raw_bytes.decode("utf-8", errors="replace")
        kind = "md" if suffix in {".md", ".markdown"} else "txt"
        meta, text = _parse_front_matter(text)
    meta = {**_parse_sidecar(path), **meta}

    if suffix == ".pdf":
        title = meta.get("title") or _first_line_title(text) or path.stem
    else:
        title = meta.get("title") or _first_heading(text) or path.stem
    tags = [t for t in re.split(r"[,，\s]+", meta.get("tags", "")) if t]
    year = None
    if meta.get("year", "").strip().isdigit():
        year = int(meta["year"].strip())

    chunks: list[Chunk] = []
    if kind == "pdf":
        for page_no, page_text in _iter_pdf_pages(raw_bytes):
            page_chunks, next_index = chunk_text(
                page_text,
                doc_id=doc_id,
                chunk_size=settings.chunk_size,
                overlap=settings.chunk_overlap,
                page=page_no,
                start_index=len(chunks),
            )
            chunks.extend(page_chunks)
    else:
        chunks, _ = chunk_text(
            text,
            doc_id=doc_id,
            chunk_size=settings.chunk_size,
            overlap=settings.chunk_overlap,
        )

    abstract = re.sub(r"\s+", " ", text.strip())[:220]
    return Document(
        doc_id=doc_id,
        title=title,
        path=str(path),
        kind=kind,
        sha1=sha1,
        abstract=meta.get("abstract", "") or abstract,
        tags=tags,
        year=year,
        chunks=chunks,
    )


def _iter_pdf_pages(raw: bytes):
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw))
    for number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            text = ""
        if text.strip():
            yield number, text


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match and match.group(1) == "#":
            return match.group(2).strip()
    return ""
