# 开发记录（过程、提示词与验证）

本文件记录这个项目是**怎样一步步做出来的**：每个阶段的目标、当时给智能体平台的需求描述、
产出的文件，以及用什么命令验证。评审可以用它对照代码与 `records/` 里的真实输出。

> **提交前需要补充的部分**：本赛题要求「项目主要开发工作必须在 Qoder 中完成」，并在提交材料里
> 附 **Qoder 对话截图/录屏 + Qoder 账号 UID**。下面每一阶段都给出了可直接粘贴进 Qoder 的需求
> 描述与验收标准，按顺序在 Qoder 中执行并保留截图即可形成完整的 Qoder 开发记录。
> 当前仓库里的代码与记录来自同一套需求与验收步骤，功能与验证结果一一对应。

---

## 阶段 0：选题与约束

**需求描述**

> 做一个提升学习/科研效率的项目。真实痛点：读文献时找不到原文出处，复习时记不住自己在哪薄弱。
> 必须用 seekdb 或 PowerContext 中的至少一种，并让它在功能中真正起作用。

**决策**

- 同时使用两者，职责分开：seekdb 存「文献知识」，PowerContext 存「关于你的记忆」。
- 零 API Key 可运行：向量用本地 ONNX 小模型，回答用摘录式生成。
- Windows 也能跑：seekdb 不可用时回退 SQLite，但提交记录必须来自 Linux + seekdb。

**产出**：`README.md` 第 1–3 节；`docs/architecture.md`。

---

## 阶段 1：知识库写入（seekdb）

**需求描述**

> 把 PDF/Markdown/TXT 解析成片段：按 Markdown 标题切小节，PDF 按页解析，段落累加到约 360 字、
> 重叠 60 字；每个片段带上文档、小节、页码、年份、标签等元数据。写入 seekdb：HNSW cosine 向量
> 索引 + IK 中文全文索引，集合用 Schema 显式声明 `embedding_function=None`，向量由应用侧写入。
> 重复导入要幂等（按 doc_id 覆盖，且清掉旧片段）。

**关键取舍**

- 片段文本带 `【小节】` 前缀参与向量化与全文检索，展示时再用正则去掉，保证「检索带上下文、展示干净」。
- 删除旧片段时按 `max(旧 n_chunks, 新 n_chunks)` 生成 ID，避免文档变短后残留旧片段。

**产出**：`wengu/library.py`、`wengu/store/seekdb_backend.py`、`wengu/store/sqlite_backend.py`。

**验证**：`python -m wengu.cli ingest --sample` → 7 篇、34 段（含 1 篇 PDF 3 段）。

---

## 阶段 2：混合检索与出处

**需求描述**

> 提问时同时做向量召回与全文召回，用 RRF 融合；支持按标签、类型、年份过滤；结果要能指出
> 「语义第几名 / 关键词第几名」，并给出「标题 · 小节 · 页码 · 片段 ID」。回答摘要不能编造。

**遇到的问题与修复**

1. 长句问题用 `$contains` 直接查全文时噪声大 → 保留数据库全文召回，但在应用层做相关性门控：
   只保留与问题有 ≥2 个特征重叠的片段（或全局前二）。
2. 摘要最初按「包含任一词」选句，选了不相干的句子 → 改为「中文二元字组 + 英文单词」特征密度排序。
3. 薄弱点加权最初对所有薄弱文档生效，导致无关文献被抬高 → 改为只对「标题/标签与问题有特征重叠」
   的薄弱文档加权。

**产出**：`wengu/retrieval.py`、`wengu/service.py` 的 `ask()`。

**验证**：`python -m wengu.cli ask "Raft 里一条日志什么时候算已提交？" --top-k 5`
→ 首选「Raft 共识算法 · 日志复制」，摘录含「多数派持久化后 Leader 提交」。

---

## 阶段 3：长期记忆（PowerContext）

**需求描述**

> 用 PowerContext 保存学习偏好、每个知识点的掌握度与复习进度、提问历史；服务重启后能读回，
> 并且每次更新都能看到版本变化（artifact revision）。

**遇到的问题与修复**

1. PowerContext 1.4.1 里 `revise_memory_entry` / `retire_memory_entry` 对 `memory` 家族返回
   `legacy_memory_operation_unsupported` → 改用 artifact 契约：`create_artifact` 新建、
   `replace_artifact` 更新（`expected_etag = "revision:N"`）。
2. 单条记忆有 8 KB 上限 → 写入前裁剪 `history` / 未超限则不裁剪，必要时再压 `items`。
3. 进程内启动 Server 需要等待就绪 → 用随机端口 + `server.started` 轮询，90 秒超时给出明确错误。

**产出**：`wengu/memory.py`、`wengu/runtime.py`、`wengu/state.py`。

**验证**：`python -m wengu.cli grade raft forgot`，`doctor` 事件中出现
`powercontext.replace_artifact from_revision=1 to_revision=2`；`demo` 重启后
`state_reused = true`，并在重启后针对薄弱文献提问，`weak_boosted` 非空。

---

## 阶段 4：复习教练

**需求描述**

> 按「到期 + 薄弱」排序组卷，人工考点优先，缺失时从原文自动出题（完形填空/要点复述）；
> 自评三档更新掌握度与下次到期；每日配额写进记忆，下次打开仍然生效。

**产出**：`wengu/coach.py`、`sample_library/quizzes.json`（6 篇 × 5 个考点）。

**验证**：`python -m wengu.cli review` → 6 道题，`reason` 与优先级符合预期；评分后再组卷，
判为「忘了 / 模糊」的文献排到最前，`reason` 变为「这里一直薄弱，多练一次」。
`tests/test_coach.py` 覆盖优先级、人工考点优先、自动出题、评分。

---

## 阶段 5：界面与技术证据

**需求描述**

> 单页界面（不引入前端构建）：文库、带出处提问、今日复习、它记住了什么、技术证据五个页面；
> 技术证据页要能看到 seekdb 的集合/维度/分词器、每次查询与记忆读写的参数和耗时。

**产出**：`wengu/static/`（index.html + style.css + app.js）、`wengu/api.py`、`wengu/tracing.py`。

**验证**：浏览器打开 `http://<host>:8000`，依次走完导入 → 提问 → 复习 → 记忆 → 技术证据。

---

## 阶段 6：可复现性与交付

**需求描述**

> 一条命令完成验证；Windows 无 seekdb 也能跑通；文档写清 Linux/Windows 两种路径与已知限制；
> 生成 `records/` 作为本次提交的证据。

**产出**：`scripts/verify.sh`、`Makefile`、`tests/`（16 个用例）、`docs/verification-sample.md`、
`records/*`。

**验证**：`./scripts/verify.sh`；`pytest -q` → 16 passed；`records/demo_summary.json` 中
`state_reused = true`。

---

## 最终验证清单（提交前对照）

| 项 | 做法 | 结果 |
| --- | --- | --- |
| 项目能跑 | `pip install -e ".[seekdb]"`（Linux）→ `wengu serve` | 8000 端口界面可用 |
| seekdb 生效 | `records/tech.json` 的 `store`、`records/ask.json` 的 `trace` | 集合 2 个、34 片段、HNSW + IK |
| PowerContext 生效 | `records/tech.json` 的 `powercontext.create_artifact / replace_artifact` | revision 递增，重启后读回 |
| 越用越懂你 | `grade` 后 `review` 的排序/原因变化；提问出现「薄弱点加权」 | 见 `records/review.json`、`ask_after_restart.json` |
| 单元测试 | `python -m pytest -q` | 16 passed |

---

## 附：Qoder 对话截图

以下截图取自 2026-10-29 的实际 Qoder 会话「阅读记录并完成项目」，按时间顺序排列。
截图中的账号 UID 已打码；完整会话可在提交账号的 Qoder 历史记录中核对。

### 1. 说明 Qoder CN 账号 UID 与阿里云账号的关系

![Qoder 对话：UID 说明（已打码）](screenshots/01-uid-qa.png)

### 2. 发布 Qoder Site 并确认代码仓库

![Qoder 对话：发布会话](screenshots/02-publish-site.png)

站点已公开发布，仓库推送到 `qoder/wengu` 分支，`SUBMISSION.md` 同步更新。

### 3. 读取开发记录并完成收尾

![Qoder 对话：收尾与验证](screenshots/03-development-summary.png)

本轮修复了重复导入的片段 ID 错位、重拍五张界面截图、对齐 `records/` 证据，并在 Linux 评测机跑通 16 项测试。
