# 架构与数据流

## 组件

- `demo_project/issuehub`：业务工程。`models.py` 定义 issue，`service.py` 承载过滤规则，`api.py` 是 stdlib HTTP 适配层。
- `sdd_context`：上下文模块。CLI 入口是 `python -m sdd_context`。
- PowerContext Server：进程内启动（`create_server_app` + uvicorn），监听随机回环端口；客户端是 `PowerContextClient`。
- seekdb：PowerContext 的 `database.kind=seekdb`，由 `pylibseekdb` 在本地拉起，数据目录 `.sdd/powercontext-seekdb`。
- MiniMax：OpenAI 兼容 chat completions；返回 JSON `files`。

## 写入路径

```
collect_materials()
  ├─ _specs()  Markdown front matter + ## 章节
  ├─ _code()   ast.parse -> Class/Function -> 行号 + 源码
  ├─ _tests()  ast.parse -> test_* 函数
  └─ _task()   TASK-001
        │
        ▼
Material.text  (MATERIAL/KIND/PATH/SYMBOL/LINES/TAGS/STATUS + body)
        │
        ▼
PowerContextClient.list_memory_entries()  → 已有条目
        ├─ 新条目: remember_memory()
        └─ 变更:   revise_memory_entry()  (每次修订前重新取 citation)
```

## 读取路径

```
PowerContextClient.list_memory_entries()   # 全量当前资料
PowerContextClient.search_memory(query)    # FTS/混合检索命中
        │
        ▼
select(): 过滤 superseded -> 分词/同义词 -> 加权 -> 规格按文档分组
        │
        ▼
context.json / context.md
```

## 状态路径

```
TASK-001-STATE (kind=task-state, text=JSON)
        │  demo 写完状态
        ▼
Server stop/start（同一 seekdb 目录）
        │
        ▼
list_memory_entries() -> load_state() -> context.state
```

## 为什么不用自建表

PowerContext 已提供 Memory 的版本、引用、检索和重启持久化。自建表会重复实现版本与索引，且评测更关注“三项技术实际参与”。当前方案把 seekdb 作为 PowerContext 的后端，把工程资料和任务状态都放入 Memory；资料的 `material_id`、`path`、`symbol`、行号由我们自己的解析器保证。

## 失败与恢复

- `revise_memory_entry` 遇到 revision conflict：重新 `list_memory_entries` 取最新 citation，重试一次。
- Server 启动失败：60 秒超时后关闭 listener 并抛出非 0。
- 修改后测试失败：`demo` 返回非 0，不写 `verified` 状态。
- MiniMax 无 Key：明确报错，提示 `.env` 或 `--offline`；不会静默使用模板补丁。
