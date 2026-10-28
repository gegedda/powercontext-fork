# 规有所依：面向软件持续演进的 SDD 上下文管理系统

本题要求为一个已有 AI 开发助手实现工程上下文模块：从持续演进的规格、代码和测试中选出**当前有效**的资料，交给 MiniMax 完成一次真实代码修改，把任务状态写入 PowerContext，并在重启后继续使用。

本目录是完整交付物。它不修改 PowerContext 产品源码，只使用产品公开的 Server + Client 接口。

## 1. 一句话说明

`issuehub` 是一个可运行的 issue 跟踪 HTTP 服务；`TASK-001` 要求给 `GET /issues` 增加 `priority` / `assignee` 过滤并保持原有行为。`sdd_context` 从 PowerContext（seekdb 后端）中检索规格、代码符号和测试，生成开发上下文；MiniMax 根据上下文返回完整文件；随后同一组测试在修改前失败、修改后通过；任务状态写回 PowerContext，模块重启后重新读取并用于下一次上下文。

## 2. 架构与各项技术的分工

```
specs + code + tests
        │  ingest（解析 Markdown / Python AST）
        ▼
PowerContext Server  ── seekdb（嵌入式）──  Memory: 工程资料 + 任务状态
        │  list_memory_entries / search_memory（真实查询）
        ▼
sdd_context.select  ── 关键词 + 元数据 + 符号/测试加权（不是固定答案）
        │  context.json / context.md
        ▼
MiniMax（chat completions）── 返回完整文件 JSON
        │  apply
        ▼
issuehub code ── pytest 目标测试 + 回归测试
        │
        ▼
PowerContext Memory: TASK-001-STATE ── 重启后 load_state
```

| 技术 | 实际承担的作用 | 入口 |
| --- | --- | --- |
| MiniMax | 根据上下文生成 `service.py` / `api.py` 的完整替换文件 | `sdd_context/minimax_agent.py` |
| seekdb / OceanBase | 保存 31 个工程资料条目、检索结果和任务状态；嵌入式 seekdb 由 PowerContext 管理 | `PowerContextRuntime` + `SDD_DB=seekdb` |
| PowerContext | Server + `PowerContextClient` 提供 Memory 写入、查询、重启复用 | `sdd_context/store.py` |

## 3. 目录

```
minimax/
├── demo_project/                 # 可运行业务工程
│   ├── issuehub/                 # models.py / service.py / api.py
│   ├── tests/                    # 4 个目标测试 + 4 个回归测试
│   └── snapshots/before/         # 修改前快照（用于证明修改前失败）
├── materials/
│   ├── specs/                    # SPEC-101/102/103，以及已失效的 SPEC-090
│   └── tasks/TASK-001.md
├── sdd_context/
│   ├── materials.py              # Markdown / AST -> 可检索资料
│   ├── store.py                  # PowerContext Memory 读写
│   ├── select.py                 # 上下文选择
│   ├── context.py                # 输出组装
│   ├── minimax_agent.py          # MiniMax 调用与文件应用
│   ├── powercontext_runtime.py   # 进程内启动真实 Server
│   ├── verify.py                 # 修改前/后测试
│   └── demo.py                   # 端到端流程
├── scripts/spec_update_check.py  # 规格更新后上下文变化的证明
├── records/                      # 测试日志、上下文、状态复用记录
├── docs/                         # 一页技术说明、验证样例
├── tests/                        # 模块自身的单元测试（可选）
├── .env.example
└── README.md
```

## 4. 环境与安装

- Python 3.11+。
- 评测 seekdb 路径要求 **Linux x86_64**（`pylibseekdb` 的 wheel 限制）。
- Windows / macOS 本地开发可退回 SQLite；代码路径与 seekdb 相同，只是存储后端不同。提交的验收命令默认显式使用 `SDD_DB=seekdb`，不会在评测机上静默退回 SQLite。

在 `minimax/` 内执行：

```bash
python -m venv .venv
. .venv/bin/activate                      # Windows: .venv\Scripts\activate
pip install -e ".[seekdb,test]"
```

如果当前 checkout 就是 PowerContext 产品仓库，也可以先安装本地产品代码：

```bash
pip install -e "..[server,seekdb]"
pip install -e . --no-deps
```

依赖版本：`powercontext[server,seekdb]>=1.2.0,<2`；本次记录使用 `powercontext 1.2.0`、`pylibseekdb 1.4.x`、`pytest 9.x`。

## 5. 配置

```bash
cp .env.example .env
```

`.env` 关键项：

```dotenv
SDD_DB=seekdb
MINIMAX_API_KEY=<你的 Key>
MINIMAX_MODEL=MiniMax-M3.1-Flash
SDD_SQL_ECHO=0
```

MiniMax API Key 申请：登录 <https://platform.minimax.cn>，完成账户信息，在「接口密钥」创建按量付费 Key，或在「订阅管理 > M Plan」查看比赛发放的订阅 Key。不要把 Key 提交到仓库。

## 6. 初始化与调用入口

```bash
# 1) 清空本地状态（可选，用于复现）
SDD_DB=seekdb python -m sdd_context reset

# 2) 导入规格、代码、测试（写入 PowerContext / seekdb）
SDD_DB=seekdb python -m sdd_context ingest

# 3) 只看本次上下文（JSON 或 Markdown）
SDD_DB=seekdb python -m sdd_context context --format markdown

# 4) 完整流程：上下文 -> MiniMax -> 应用 -> 测试 -> 状态 -> 重启复用
SDD_DB=seekdb python -m sdd_context demo
```

没有 Key 时，可用 `--skip-minimax` 验证上下文/数据库/状态链路：

```bash
SDD_DB=seekdb python -m sdd_context demo --skip-minimax
```

`demo` 的输入与输出：

- 输入：`materials/tasks/TASK-001.md` 的任务描述。
- 输出：`records/context.json`、`records/context.md`、`records/minimax_run.json`、`records/test_results.json`、`records/state_reuse.json`、`records/demo_summary.json`。
- 退出码：任一步失败即为非 0。

## 7. 验证样例

**要改什么**：`GET /issues` 新增 `priority`（low/medium/high）和 `assignee`（精确匹配）参数；非法 priority 返回 400 `invalid_priority`。

**哪些原有行为必须保持**：

- 无过滤时返回全部 6 条并按 id 升序。
- `status` 过滤不变。
- 响应字段和 `total` 含义不变。
- `/issues/{id}` 与 404 行为不变。

**上下文必须包含的来源**：

- 规格：`SPEC-101.1/2/3`、`SPEC-102.1/2`、`SPEC-103.1/2/3/4`；`SPEC-090`（已失效）不得出现。
- 代码：`IssueService.list_issues`、`make_handler`、`Issue`、`InvalidPriority`。
- 测试：4 个目标测试 + `test_no_filters_returns_all_sorted`、`test_status_filter_still_works`。

**修改前**：`snapshots/before` 覆盖 `issuehub` 后，4 个目标测试失败，4 个回归测试通过。

**修改后**：当前 `issuehub` 下，8 个测试全部通过。

**重置**：`python -m sdd_context reset` 只删除 `.sdd/`；如需恢复代码，用 `demo_project/snapshots/before/issuehub/*.py` 覆盖，当前版本可从 git 恢复。

## 8. 验证命令与证据

```bash
python -m pytest demo_project/tests -q       # 8 passed（修改后）
python -m sdd_context verify                 # 修改前 4 失败 / 修改后 8 通过
python scripts/spec_update_check.py          # 规格新增章节后，上下文出现 SPEC-102.9
```

产物：

- `records/before_target.log`：4 failed。
- `records/before_regression.log`：4 passed。
- `records/after_target.log` / `records/after_regression.log`：全通过。
- `records/test_results.json`：退出码与计数。
- `records/spec_update_proof.json`：更新规格后上下文发生变化。
- `records/state_reuse.json`：重启前后的 scope、写入状态、读取状态。
- `records/database_queries.log`：`SDD_SQL_ECHO=1` 时的 SQL 语句记录。
- `records/code.diff`：修改前后代码差异。

## 9. MiniMax 开发记录

本次真实运行：

- 模型：`MiniMax-M3.1-Flash`
- 接口：`POST https://api.minimaxi.com/v1/chat/completions`（OpenAI 兼容）
- 两次调用，分别生成 `service.py` 和 `api.py`；合计 15,462 tokens（其中 reasoning 6,354）
- 应用后 4 个目标测试 + 4 个回归测试全部通过

`records/minimax_run.json` 记录模型、上下文、两次响应、usage 和应用的文件；`records/minimax_development.md` 是人工可读摘要；`records/code.diff` 与提交代码对应。`--offline` 只回放已经落盘的 `records/minimax_recorded.json`，不会伪造在线调用。

## 10. 数据与状态

- 所有资料和状态都在 PowerContext 的同一个 Memory 中，存储后端为 seekdb；`material_id` 写在每条 Memory 文本第一行，便于重新导入时定位并修订。
- 每次 `ingest` 先 `list_memory_entries` 读取当前条目；内容变化时 `revise_memory_entry`，新增时 `remember_memory`。
- 任务状态是 `TASK-001-STATE` 条目，`demo` 在重启 Server 后重新读取并放入 `context.state`；`records/state_reuse.json` 的 `same_task_status` 与 `context_uses_loaded_state` 均为 `true`。

## 11. 已知限制

- 嵌入式 seekdb 的 `pylibseekdb` 只提供 Linux/macOS wheel；Windows 本地开发使用 SQLite 回退，无法在 Windows 上证明 seekdb 路径。
- MiniMax 调用需要有效 Key；没有 Key 时只能跑 `--skip-minimax`。
- 本题只要求模块重启后复用状态，不恢复完整 Agent 会话。
- 代码符号按 Python AST 提取；当前业务工程是 Python，其他语言需要扩展解析器。

## 12. 必做项对照

| 验收项 | 本交付物 |
| --- | --- |
| 能够运行 | `ingest` / `context` / `demo` / `verify` 均有明确入口，数据可重建 |
| MiniMax 实际参与 | `minimax_agent.py` 调用 chat completions，记录与 diff 对应 |
| 上下文正确 | 输出含规定来源；`spec_update_check.py` 证明更新后使用新内容 |
| 数据库实际参与 | seekdb 通过 PowerContext 持久化 31 个资料条目与状态；`SDD_SQL_ECHO=1` 可出 SQL 日志 |
| 状态能够复用 | 重启 Server 后 `state_reuse.json` 显示读取成功并进入上下文 |
| 代码修改有效 | 同一组测试：before 4 失败、after 8 通过，回归不变 |
