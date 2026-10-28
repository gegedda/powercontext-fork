from __future__ import annotations

from pathlib import Path

from wengu.library import chunk_text, parse_document


class _Settings:
    chunk_size = 240
    chunk_overlap = 40


def test_parse_markdown_with_front_matter(tmp_path: Path) -> None:
    path = tmp_path / "raft-note.md"
    path.write_text(
        "---\ntitle: Raft 笔记\nyear: 2014\ntags: 分布式,共识\n---\n\n"
        "# Raft\n\n## 日志复制\n\nLeader 把日志发给 Follower，多数派确认后提交。\n\n"
        "## 选举\n\n任期号更大的节点会迫使其他人转为 Follower。\n",
        encoding="utf-8",
    )
    document = parse_document(path, settings=_Settings())
    assert document.title == "Raft 笔记"
    assert document.year == 2014
    assert document.tags == ["分布式", "共识"]
    assert document.kind == "md"
    assert document.n_chunks >= 2
    assert {chunk.section for chunk in document.chunks} == {"日志复制", "选举"}


def test_chunk_text_keeps_section_and_ids() -> None:
    text = "## 第一节\n\n" + "内容甲。" * 60 + "\n\n## 第二节\n\n内容乙。"
    chunks, next_index = chunk_text(text, doc_id="demo", chunk_size=120, overlap=20)
    assert chunks
    assert all(chunk.chunk_id.startswith("demo#") for chunk in chunks)
    assert {chunk.section for chunk in chunks} == {"第一节", "第二节"}
    assert next_index == len(chunks)


def test_unsupported_suffix(tmp_path: Path) -> None:
    path = tmp_path / "data.csv"
    path.write_text("a,b")
    try:
        parse_document(path, settings=_Settings())
    except ValueError as exc:
        assert "不支持" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("应当拒绝不支持的格式")
