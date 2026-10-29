# 架构说明

## 1. 数据模型

### seekdb（知识库）

数据目录由 `WENGU_DATA_DIR` 决定，数据库名 `wengu`，两个集合：

| 集合 | 内容 | 说明 |
| --- | --- | --- |
| `wengu_docs` | 文献元数据（`title`、`kind`、`year`、`tags`、`n_chunks`、`chars`、`path`、`sha1`、`imported_at`） | 文档级元数据；向量字段只用于满足集合结构，不参与检索 |
| `wengu_chunks` | 片段正文 + 512 维向量（cosine）+ 元数据（`doc_id`、`title`、`section`、`page`、`index`、`kind`、`tags`、`year`） | 唯一被检索的集合 |

集合创建方式（`wengu/store/seekdb_backend.py`）：

```python
pyseekdb.Schema(
    vector_index=pyseekdb.VectorIndexConfig(
        hnsw=pyseekdb.HNSWConfiguration(dimension=512, distance="cosine", M=16, ef_construction=200),
        embedding_function=None,          # 向量由应用侧计算后显式写入
    ),
    fulltext_index=pyseekdb.FulltextIndexConfig(analyzer="ik"),   # 中文分词
)
```

写入流程：先按 `max(旧 n_chunks, 新 n_chunks)` 删除旧片段 ID（避免文档变短后残留），
再用新片段的 ID `upsert` 文档与片段，最后 `refresh_index()` 让新数据立即可检索。

### PowerContext（记忆）

每条记忆是一个 `atomic-memory` artifact，正文是 UTF-8 JSON（PowerContext 单条约 8 KB 上限，
超长时裁剪 `history`/`items`）：

| artifact | kind | 内容 |
| --- | --- | --- |
| `PROFILE-1` | `wengu-profile` | 昵称、目标、讲解风格、每日配额 |
| `TOPIC-<doc_id>` | `wengu-topic` | 掌握度 `strength`、复习次数、答对次数、间隔、下次到期、最近 6 次历史 |
| `ASKLOG-1` | `wengu-ask-log` | 最近 12 次提问（问题、时间、引用来源） |

更新语义：

```python
创建： client.create_artifact(scope_id, CreateArtifactRequest(
          root=CreateAtomicMemoryArtifactRequest(family="atomic-memory",
              content=AtomicMemoryWriteContent(kind=..., text=json))))
更新： client.replace_artifact(scope_id, "atomic-memory", artifact_id,
          ReplaceArtifactRequest(root=ReplaceAtomicMemoryArtifactRequest(
              content=AtomicMemoryWriteContent(kind=..., text=json))),
          expected_etag=f'"revision:{current_revision}"')
读取： client.list_atomic_memories(ListAtomicMemoryRequest(scope_id=scope_id))
```

`expected_etag` 让并发写入不会静默覆盖；`replace_artifact` 每次推进 revision，所以 UI 上能看到
「记忆版本 rev N」，也是「历史互动被保留」的证据。

## 2. 检索算法

```
query ──► 向量化（bge-small-zh，带查询前缀）
      ├──► seekdb 向量召回：query(query_embeddings, where, n_results=3k)    → 按余弦距离排序
      └──► seekdb 全文召回：hybrid_search(query={where_document:{$contains: q}}, rank=rrf) → 按全文相关度排序
                            │
                            ▼
                   RRF 融合 score = Σ 1/(60 + rank_i)
                            │
                            ▼
                   薄弱点加权 ×1.18（仅当问题与薄弱主题相关）
                            │
                            ▼
                  取 top_k → 回表取正文 → 摘录式回答 + 出处
```

- **为什么用 RRF**：向量分数是余弦相似度（≈0–1），全文分数是数据库内部相关度（量纲不同），
  用排名融合不需要归一化，且两种后端（seekdb / SQLite）语义一致。
- **为什么还要 seekdb 原生 `hybrid_search`**：每次检索会对同一问题再调一次数据库侧 RRF，
  把结果写进 `trace.fused[0].native_hybrid_preview`，用来交叉验证应用层融合没有跑偏；
  界面「技术追踪」里能看到这次调用的耗时。
- **标签过滤在应用层**：seekdb 的元数据过滤是精确匹配，而 tags 是多值字符串；年份 / 类型 / 文档 ID
  仍下推给 seekdb（`$in`、`$gte`、`$eq`），标签在召回后过滤。

## 3. 回答生成

无 API Key 的确定性实现（`compose_extractive_answer`）：

1. 把候选片段按句子切分；
2. 用「中文二元字组 + 英文单词」做特征，计算句子与问题的重叠密度；
3. 每段取密度最高的 2 句，拼成引用块；
4. 相关性门控：只保留自身内容与问题有 ≥2 个特征重叠的片段（或全局前二），避免 RRF 噪声挤进答案；
5. 汇总一句「最相关的内容在『标题』· 小节：…」，并给出 `语义第 N 名 / 关键词第 N 名`。

这样答案永远带出处，且不依赖外部模型；需要生成式改写时，可以在这一层之后接自建 LLM。

## 4. 复习调度

```
优先级 = (是否薄弱且到期, 掌握度) 的字典序
薄弱：strength < 0.33 且 attempts ≥ 1
调度：忘了 → strength-0.30，间隔 1 天
      模糊 → strength+0.12，间隔 ×1.5
      记得 → strength+0.35，间隔 ×2.2（上限 60 天）
```

题目来源：`sample_library/quizzes.json` 的人工考点优先；没有考点的文献用原文自动出题
（遮蔽关键术语的完形填空 / 要点复述）。每次评分都会 `replace_artifact` 更新对应 `TOPIC-<doc>`，
并立即 `refresh()` 回读，保证界面显示的掌握度就是记忆里的值。

## 5. 失败与降级

| 情况 | 行为 |
| --- | --- |
| 没有 `pylibseekdb`（Windows 等） | `WENGU_STORE=auto` 时回退 SQLite（numpy 全量余弦 + 自实现 BM25），界面标注后端为 `sqlite` |
| 没有 ONNX 模型 | 回退哈希向量（字符 n-gram + 子线性 TF），`embedder.fallback_notes` 里写明原因 |
| PowerContext 不可用 | 启动直接失败并打印原因（记忆是核心能力，不静默降级） |
| 单个文件解析失败 | 记入 `skipped`，不影响整批导入 |
| seekdb 原生混合检索失败 | 记 `seekdb.native_hybrid_error` 事件，主结果仍由应用层融合给出 |
| 记忆超过 8 KB | 自动裁剪 `history` / `items` 字段后重试 |
