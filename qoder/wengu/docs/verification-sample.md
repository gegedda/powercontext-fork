# 验证样例（Step by Step）

> 环境：openEuler 24.03 LTS SP4（x86_64）、Python 3.11.6、pyseekdb 1.4.0.post1、
> pylibseekdb 1.4.0.post2、powercontext 1.4.1、onnxruntime 1.31.1。
> 目录：`qoder/wengu/`，数据目录 `/root/wengu-data`（`WENGU_DATA_DIR`）。

## 0. 准备

```bash
cd qoder/wengu
python -m venv .venv && . .venv/bin/activate
pip install -e ".[seekdb]"
# 可选：放置本地向量模型（不放置则自动降级为哈希向量）
ls data/models/bge-small-zh-v1.5/    # model_quantized.onnx  tokenizer.json  config.json
export WENGU_DATA_DIR=$PWD/data
export WENGU_STORE=seekdb
```

## 1. 自检

```bash
python -m wengu.cli doctor
```

关注输出：

```json
{
  "store": {"backend": "seekdb", "collections": ["wengu_chunks", "wengu_docs"],
            "dimension": 512, "vector_index": "HNSW(cosine)", "fulltext_analyzer": "ik"},
  "embedder": {"provider": "onnx-bge-small-zh-v1.5", "dim": 512},
  "powercontext": {"mode": "in-process", "storage": "sqlite", "scope_id": "scp_..."}
}
```

## 2. 导入示例语料

```bash
python -m wengu.cli ingest --sample
```

预期：`imported` 7 篇（`lsm-tree`、`mvcc-snapshot-isolation`、`raft`、`wal-aries`、
`vector-index`、`query-optimizer`、`oceanbase-tpcc-notes`），`skipped` 为空，
`store.chunks` 从 0 变成 34（PDF 3 段 + Markdown 31 段）。

## 3. 带出处提问

```bash
python -m wengu.cli ask "Raft 里一条日志什么时候算已提交？" --top-k 5
```

预期：

- `answer.summary` 指向「Raft 共识算法 · 日志复制」；
- 摘录含「当日志被多数派持久化后，Leader 提交并把结果返回客户端」；
- `citations[0] = {doc_id: "raft", section: "日志复制"}`；
- `timings_ms` 中 `embed ≈ 3–10ms`、`vector ≈ 1–4ms`、`fulltext ≈ 2–12ms`、`total ≈ 10–25ms`；
- `trace.vector_hits[0].chunk_id = "raft#002"`，说明向量路命中正确。

再验证过滤：`--tags 事务` 或 `--kind pdf --year 2022`。

## 4. 复习与记忆写入

```bash
python -m wengu.cli review
python -m wengu.cli grade raft forgot
```

预期：`review` 返回 6 道题，`reason` 形如「到期复习，而且上次掌握度偏低」；
`grade` 返回 `strength` 从 0 起变化、`due` 为次日，并且 `doctor` 的 `events` 里出现：

```json
{"kind": "powercontext.replace_artifact",
 "entry_id": "TOPIC-raft", "artifact_id": "art_...",
 "from_revision": 1, "to_revision": 2, "reason": "复习结果 forgot"}
```

## 5. 端到端验证（含重启）

```bash
python -m wengu.cli demo --out records
```

依次执行：导入 → 3 次带出处提问 → 组卷 + 4 次评分 → **停止并重启 PowerContext Server** →
`list_atomic_memories` 读回记忆 → 再提一个问题（此时薄弱点参与加权）。

预期关键字段（`records/demo_summary.json`）：

```json
{"restart_and_reuse": {"scope_id": "scp_...", "topics_before": 6, "topics_after": 6,
                       "weak_after": ["raft", "query-optimizer", "mvcc-snapshot-isolation"],
                       "state_reused": true, "same_scope": true}}
```

## 6. 单元测试

```bash
python -m pytest -q      # 15 passed
```

## 证据清单（本次提交的 `records/`）

| 文件 | 内容 |
| --- | --- |
| `records/demo_summary.json` | 端到端每一步的摘要，含重启后记忆复用结论 |
| `records/ingest.json` | 导入结果（7 篇、34 段、耗时） |
| `records/ask.json` | 3 个问题的回答、引用、向量/全文召回明细与耗时 |
| `records/ask_after_restart.json` | 重启后再次提问，含 `weak_boosted` 片段 |
| `records/review.json` | 组卷结果与 4 次评分明细 |
| `records/memory_before_restart.json` / `memory_after_restart.json` | 重启前后的记忆快照与某条记忆的 revision 历史 |
| `records/tech.json` | 存储统计、向量化配置、事件流（seekdb 写入/查询、PowerContext 创建/更新） |

## 常见问题

**Q：Windows 上跑 `WENGU_STORE=seekdb` 报 `pylibseekdb` 不可用？**
A：嵌入式 seekdb 只发布 Linux x86_64 / macOS arm64 wheel。Windows 请用默认 `auto`（回退 SQLite），
或按 README 在 Linux 上验证。

**Q：`doctor` 显示 `embedder.provider = hash-char-ngram`？**
A：没有找到 `data/models/bge-small-zh-v1.5/*.onnx`，按 README 4.2 下载即可；哈希向量也能跑通全流程。

**Q：端口被占用启动失败？**
A：PowerContext Server 使用随机端口；只有 Web 界面占用 8000，换 `--port` 即可。
