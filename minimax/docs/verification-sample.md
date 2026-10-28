# 验证样例

## 任务

`TASK-001`：给 `issuehub` 的 `GET /issues` 增加 `priority` 和 `assignee` 过滤。

- `priority`：`low` / `medium` / `high`；其他值返回 HTTP 400，body 为 `{"error":"invalid_priority","allowed":["low","medium","high"]}`。
- `assignee`：精确匹配。
- 与已有 `status` 过滤按 AND 组合。
- 无过滤时仍返回全部 6 条，按 id 升序。
- 响应字段、`total`、`/issues/{id}`、404 行为不变。

## 初始数据

`demo_project/issuehub/models.py` 中 6 条 issue：

| id | status | priority | assignee |
| ---: | --- | --- | --- |
| 1 | open | high | alice |
| 2 | open | low | bob |
| 3 | closed | low | alice |
| 4 | in_progress | high | carol |
| 5 | open | medium | bob |
| 6 | in_progress | medium | null |

## 上下文必须包含

- 规格：`SPEC-101.1`、`SPEC-101.2`、`SPEC-101.3`、`SPEC-102.1`、`SPEC-102.2`、`SPEC-103.1`、`SPEC-103.2`、`SPEC-103.3`、`SPEC-103.4`。
- 不得包含：`SPEC-090`（`status: superseded`）。
- 代码：`IssueService.list_issues`、`make_handler`、`Issue`、`InvalidPriority`。
- 测试：`test_filter_by_priority`、`test_filter_by_assignee_and_priority`、`test_priority_combines_with_status`、`test_invalid_priority_returns_400`、`test_no_filters_returns_all_sorted`、`test_status_filter_still_works`。

## 操作步骤

```bash
cd minimax
cp .env.example .env                      # 填 MINIMAX_API_KEY；seekdb 需要 Linux
pip install -e ".[seekdb,test]"

SDD_DB=seekdb python -m sdd_context reset
SDD_DB=seekdb python -m sdd_context ingest
SDD_DB=seekdb python -m sdd_context context --format json > records/context.json
SDD_DB=seekdb python -m sdd_context demo
```

## 预期结果

1. `records/context.json` 的 `specs` 包含上述 8 个章节，`SPEC-090` 不出现；`code` 含 `list_issues`；`tests` 含 4 个目标测试和 2 个回归测试。
2. `records/before_target.log`：`4 failed`；`records/before_regression.log`：`4 passed`。
3. `records/after_target.log`：`4 passed`；`records/after_regression.log`：`4 passed`。
4. `records/state_reuse.json`：`same_task_status=true`、`context_uses_loaded_state=true`。
5. `records/code.diff`：只改 `service.py`、`api.py`，不改测试。
6. `python scripts/spec_update_check.py`：`passed=true`，新增 `SPEC-102.9` 后上下文出现该章节。

## 重置

```bash
SDD_DB=seekdb python -m sdd_context reset
git checkout -- demo_project/issuehub        # 恢复当前（修改后）版本
# 如需修改前版本：
cp demo_project/snapshots/before/issuehub/*.py demo_project/issuehub/
```

`reset` 只删除 `.sdd/`，不会删除仓库里的规格、代码或测试。

## 判定

同一组测试文件、同一组断言在修改前后执行；修改前失败的原因是目标行为未实现，不是依赖缺失或启动错误。修改后目标测试与回归测试全部通过。
