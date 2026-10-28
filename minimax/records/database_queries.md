# 数据库使用记录

## 1. 存储后端

PowerContext Server 的 `database` 配置决定后端：

- 评测/Linux：`SDD_DB=seekdb`，嵌入式 `pylibseekdb`，数据目录 `.sdd/powercontext-seekdb`。
- 本地 Windows 开发：`SDD_DB=sqlite`，`aiosqlite`，数据目录 `.sdd/powercontext.db`。

`PowerContextRuntime` 不会在 `SDD_DB=seekdb` 时静默退回 SQLite；缺少 `pylibseekdb` 会直接报错。

## 2. 工程资料如何进入数据库

`sdd_context.ingest` 把 31 条资料写成 PowerContext Memory：

| 类型 | 数量 | 例子 |
| --- | ---: | --- |
| 规格章节 | 9 | `SPEC-101.1` … `SPEC-103.4` |
| 代码符号 | 12 | `CODE-service-IssueService-list_issues` |
| 测试函数 | 8 | `TEST-test_filter_by_priority` |
| 任务 | 1 | `TASK-001` |
| 任务状态 | 1 | `TASK-001-STATE` |

写入路径：

1. `list_memory_entries` 读取当前条目（按 `material_id` 去重）。
2. 新条目调用 `remember_memory`。
3. 内容变化的条目重新读取最新 citation，再调用 `revise_memory_entry`。

种子运行（seekdb）：`inserted=30`，`updated=0`，`unchanged=0`；`SPEC-103.4`
加入后为 `inserted=1`，`unchanged=30`。

## 3. 实际查询

`records/context.json` 的 `sources` 保存了每条被选中资料的：

- `material_id`
- `memory_entry_id`（例如 `mem_ent_...`）
- `entry_version_id`（例如 `mem_ver_...`）
- 真实文件路径、符号、行号

读取路径：

- `PowerContextClient.list_memory_entries(scope_id, include_inactive=False)` — 全量当前资料与状态。
- `PowerContextClient.search_memory(scope_id, query, limit=40)` — FTS/混合检索命中，作为选择层加分项。
- `PowerContextClient.get_scope(scope_id)` — 重启后校验同一 Scope。

## 4. SQL 轨迹

`SDD_SQL_ECHO=1` 时，SQLAlchemy 的 `sqlalchemy.engine` 日志写入 stderr。
[`database_queries.log`](database_queries.log) 是本地 SQLite 验证运行的 SQL 轨迹，
其中可见：

```sql
SELECT pc_artifact_heads.revision FROM pc_artifact_heads ...
INSERT INTO pc_artifacts (scope_id, family, artifact_id, revision, content, memory_citations) ...
```

Linux + seekdb 的 CI 轨迹保存在 `linux_seekdb_sql.log`，`demo_summary.json`
中的 `"backend": "seekdb"`、`"state_reused": true` 与
`"upsert": {"inserted": 30}` 对应同一次运行。参数因
`hide_parameters=True` 被隐藏，真实来源以 `context.json` 的 citation 为准。
