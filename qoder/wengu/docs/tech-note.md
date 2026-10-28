# 一页技术说明

**项目**：温故 WenGu —— 文献混合检索 + 越用越懂的复习教练
**赛题**：Qoder × OceanBase「Build with Qoder」
**指定技术**：seekdb（嵌入式）、PowerContext 1.4.1

## 解决什么问题

学生/研究者有两件重复劳动：读文献时在几十篇里找一句话、复习时想不起自己在哪薄弱。
通用检索工具只给链接，通用笔记工具不安排复习。

## 核心链路

```
PDF/笔记 → 切分小节 → 本地 bge-small-zh 向量 + 元数据 → seekdb（HNSW + IK 全文）
问题 → 向量召回 + 全文召回 → RRF 融合 → 薄弱点加权 → 带出处的原文摘录
复习 → PowerContext 读取掌握度/到期 → 按优先级组卷 → 自评 → 写回 artifact（revision+1）
```

## 三项技术各自证明了什么

| 技术 | 可核对的证据 |
| --- | --- |
| seekdb | `records/tech.json`：`database=wengu`、`collections=[wengu_chunks, wengu_docs]`、`dimension=512`、`vector_index=HNSW(cosine)`、`fulltext_analyzer=ik`；`records/ask.json`：每次提问的 `vector_hits`（余弦分数）与 `fulltext_hits`（全文相关度）两路原始输出 |
| PowerContext | `records/tech.json`：`powercontext.create_artifact` / `replace_artifact`（artifact_id、from_revision → to_revision）；`memory_after_restart.json`：重启后 `list_atomic_memories` 读回的同一批知识点 |
| 应用逻辑 | `records/review.json`：组卷原因与评分；`records/ask_after_restart.json`：`weak_boosted` 片段说明记忆真的反过来影响检索 |

## 量化结果（本次 Linux 实测）

| 指标 | 数值 |
| --- | --- |
| 示例语料 | 7 篇（6 Markdown + 1 PDF），34 个检索片段，约 6 000 字 |
| 导入耗时 | 6.4 s（含 34 段文本的 ONNX 向量化与 seekdb 索引刷新） |
| 单次检索 | 10–25 ms（`embed 3–10 ms + 向量 1–4 ms + 全文 2–12 ms + 回表 <1 ms`） |
| 端到端 demo | 16 s（导入 + 3 次提问 + 组卷 + 4 次评分 + 重启 Server + 记忆复用 + 再提问） |
| 记忆规模 | 8 条 artifact（1 档案 + 6 知识点 + 1 提问历史），单条 0.4–1.7 KB |
| 测试 | 15 个单元测试全部通过 |

## 与「只用向量库」或「只用聊天记录」的差别

- 只用向量库：能检索，但不知道你是谁、下一步该复习什么；
- 只用 PowerContext：记得住你，但文献正文没有可检索的向量与全文索引；
- 本项目的记忆是**结构化且带版本**的（掌握度、到期时间、历史），不是一段自然语言摘要，
  因此可以直接驱动排序与排期，改动可追溯到 rev N。

## 已知边界

回答是摘录式而非生成式（避免无出处幻觉）；调度是简化版 SM-2；嵌入式 seekdb 仅 Linux/macOS
arm64 可用，Windows 自动回退 SQLite 但仍完整可用。
