# 一页技术说明

## 问题

软件持续演进时，AI 助手需要同时回答三个问题：当前必须遵守哪些规格、应该改哪些代码、如何证明没有破坏原有行为。资料分散、规格过期、会话中断会让它遗漏约束或重复劳动。

## 模块结构

`sdd_context` 分为四层：

1. **资料层**（`materials.py`）：Markdown 规格按 `##` 章节切分；Python 代码按 AST 提取类、函数、方法；测试按 `test_*` 函数提取。每条资料有稳定的 `material_id`、真实路径、起止行、状态（active / superseded）。
2. **存储层**（`store.py`）：通过 PowerContext Server 的 Memory API 写入、列出、检索、修订；所有资料与任务状态都在同一个 Memory Scope 中。1.2 使用 `MemoryEntry.citation` + `revise_memory_entry`；1.4 使用 `AtomicMemoryRecord` / `AtomicMemorySearchHit`，更新为追加新记录、读取时按 material_id 取最新 revision。选择层不依赖 `citation` 字段。
3. **选择层**（`select.py`）：对任务文本做中英文分词和同义词扩展，按元数据命中（id、title、path、symbol、tag）、正文命中、符号名（`list_issues`）和测试类型（target / regression）加权；过滤 `superseded` 规格；按 spec 文档分组，取前三组及其全部有效章节。
4. **执行层**（`minimax_agent.py` + `verify.py`）：把上下文交给 MiniMax，要求返回完整文件 JSON；应用到 `demo_project/issuehub`；运行同一组目标测试和回归测试；把状态写回 PowerContext，重启后再读。

## 上下文选择方式

`select` 不是固定答案：

- 输入是任务文本，以及从数据库实时读出的全部当前资料。
- 规格按 `material_id` 前缀分组，避免同一文档的多个章节互相挤占名额。
- `status=superseded` 的条目被排除；`SPEC-090` 因此永远不会进入上下文。
- 代码符号和测试函数由 AST 实时提取，行号来自当前文件；规格更新后重新导入，`revise_memory_entry` 会替换条目内容。
- `scripts/spec_update_check.py` 在隔离副本里新增 `SPEC-102.9`，重新导入后上下文出现该章节，证明输出不是缓存或固定答案。

## 三项技术的分工

| 技术 | 分工 | 证据 |
| --- | --- | --- |
| MiniMax | 根据上下文生成 `service.py` / `api.py` 的完整替换文件 | `records/minimax_run.json`、`records/code.diff` |
| seekdb | PowerContext 的持久化后端，保存 30 个资料条目、任务状态和检索索引 | `SDD_DB=seekdb`、`records/database_queries.log` |
| PowerContext | Server + Client；Memory 写入/检索；重启后 `load_state` | `records/state_reuse.json` |

## 结果

- 修改前：4 个目标测试失败（过滤未实现、非法 priority 返回 200），4 个回归测试通过。
- 修改后：4 个目标测试 + 4 个回归测试全部通过。
- 模块重启后读到 `status=verified`，并把该状态放入新上下文。
- 规格更新后重新导入，新章节被选中。

## 取舍

- 用 Memory 而不是自建表：PowerContext 已经提供版本、检索、重启持久化，避免重复实现；`kind` + `material_id` 提供足够的资料分类。
- 用章节/符号级切分而不是整文件：上下文更小，能精确给出行号，也便于规格单独修订。
- 用完整文件返回而不是 diff：降低模型输出格式错误导致补丁失败的概率；diff 由仓库快照生成，便于评审核对。
- Windows 本地用 SQLite 仅作为开发回退；评测命令显式 `SDD_DB=seekdb`，不会静默降级。
