# 温故 WenGu

> 把读过的文献变成记得住的知识。
> 知识库用 **seekdb** 做「向量 + 全文 + 标量过滤」的混合检索，记忆用 **PowerContext** 保存
> 你的薄弱点、复习进度和提问历史，于是它越用越懂你。

「温故」解决的是学生和研究者每天都在重复的两件事：**翻几十篇论文找一句话**，和**复习时找不到
上学期记过什么**。它把 PDF / Markdown / TXT 笔记切分入知识库，提问时给出**带出处**的原文片段；
再把每次复习的结果写进 PowerContext，按掌握度与遗忘间隔安排下一次复习。

本目录是本赛题的完整交付物（项目网站通过 Qoder Sites 发布，见 `website/`）。

---

## 1. 它到底能做什么

| 页面 | 能力 | 用到的技术 |
| --- | --- | --- |
| **文库** | 拖入 PDF / MD / TXT，自动切分小节、向量化、登记知识点 | seekdb（写入 + HNSW + IK 全文索引） |
| **带出处提问** | 语义检索 + 关键词检索 + 元数据过滤，结果给出「语义第 N 名 / 关键词第 N 名」和出处 | seekdb 混合检索、本地 bge-small-zh 向量 |
| **今日复习** | 按「到期 + 薄弱」组卷，人工考点优先、缺失时用原文自动出题，自评后更新掌握度与下次到期 | PowerContext（读写复习状态）、SM-2 式调度 |
| **它记住了什么** | 学习档案、知识点掌握度、记忆版本、跨会话提问历史 | PowerContext（create/replace artifact） |
| **技术证据** | 存储统计、每次 seekdb 查询与 PowerContext 记忆读写的参数与耗时 | 应用内追踪 |

**「越用越懂你」具体体现在三处**：

1. 复习排期：薄弱且到期的知识点排在前面，答「忘了」会缩短间隔，答「记得」会拉长；
2. 检索重排：问题与你的薄弱点相关时，命中该主题的片段会被加权（`weak_boost = 1.18`），
   UI 上标出「薄弱点加权」；
3. 跨会话复用：换一个进程、重启 Server、甚至换一个 Agent，`list_atomic_memories` 读回同样的档案与进度。

---

## 2. 技术分工（为什么两个都要用）

| 技术 | 在本项目里的实际作用 | 代码位置 |
| --- | --- | --- |
| **seekdb（嵌入式）** | 知识库主存储：`wengu_chunks` 存 512 维向量 + 正文 + 元数据，`wengu_docs` 存文献元数据；向量检索走 HNSW（cosine），关键词检索走 IK 分词全文索引，`where` 下推文档/年份/类型过滤；同一查询还会用 seekdb 原生 `hybrid_search`（数据库侧 RRF）做交叉验证 | `wengu/store/seekdb_backend.py` |
| **PowerContext 1.4.1** | 长期记忆：每条记忆是一个 `atomic-memory` Artifact，新建用 `create_artifact`，更新用 `replace_artifact`（带 `expected_etag`），因此每次复习/改偏好都会推进 revision；启动时 `list_atomic_memories` 恢复全部状态 | `wengu/memory.py`、`wengu/runtime.py` |
| bge-small-zh-v1.5（ONNX） | 本地中文向量模型，无需任何云 API Key；缺模型时自动降级为字符 n-gram 哈希向量，功能不中断 | `wengu/embedding.py` |

**两者没有互相替代**：seekdb 只存「文献知识」，PowerContext 只存「关于你的记忆」。删除知识库不会
删掉学习记录（记忆通过新建 scope 重置），清空记忆也不影响文献检索。

---

## 3. 架构

```
        PDF / MD / TXT
              │  解析（pypdf / Markdown 标题）
              ▼
        切分小节 + 512 维向量（bge-small-zh / ONNX）
              │
              ▼
   ┌──────────────────────────┐        ┌─────────────────────────────┐
   │ seekdb（嵌入式）          │        │ PowerContext Server（进程内） │
   │  wengu_docs  文献元数据   │        │  scope: 学习记忆              │
   │  wengu_chunks 片段+向量   │        │  · PROFILE-1   学习偏好       │
   │  HNSW(cosine) + IK 全文   │        │  · TOPIC-<doc> 掌握度/到期     │
   └────────────┬─────────────┘        │  · ASKLOG-1    提问历史       │
                │                       └──────────────┬──────────────┘
        向量召回 + 全文召回                            │ 读写记忆（artifact revision）
                │                                       │
                ▼                                       ▼
        RRF 融合 + 薄弱点加权 ────────────────── 复习调度 / 个性化排序
                │
                ▼
        带出处的摘录式回答（FastAPI + 单页界面，无需前端构建）
```

关键实现选择：

- **应用侧提供向量**：集合用 `Schema(vector_index=VectorIndexConfig(hnsw=..., embedding_function=None),
  fulltext_index=FulltextIndexConfig(analyzer="ik"))` 创建，向量始终由本项目计算后显式写入，
  不依赖 seekdb 自带模型（避免模型下载与版本漂移）。
- **两路召回、应用层 RRF**：向量与全文各召回 `3 × top_k`，用 RRF（k=60）融合，保证两种后端
  （seekdb / SQLite）排序语义一致，也便于单独验证任意一路。
- **记忆即 Artifact**：`PROFILE-1`、`TOPIC-<doc_id>`、`ASKLOG-1` 各自是一个 artifact，
  UI 的「记忆版本」列直接显示当前 revision。

---

## 4. 快速开始

### 4.1 环境要求

| 场景 | 要求 |
| --- | --- |
| **推荐（完整能力）** | Linux x86_64 / macOS arm64，Python 3.11+，能 `pip install pyseekdb`（嵌入式 seekdb 的 `pylibseekdb` 只发布这两个平台的 wheel） |
| **仅体验界面与记忆** | Windows / 任意平台，Python 3.11+，知识库自动回退到 SQLite 后端 |

不需要任何 API Key：向量模型是本地 ONNX 小模型。

### 4.2 安装

```bash
cd qoder/wengu
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[seekdb]"      # 没有 seekdb 的平台：pip install -e .
```

向量模型（可选，30 MB 左右；不装会自动降级为哈希向量）：

```bash
mkdir -p data/models/bge-small-zh-v1.5
cd data/models/bge-small-zh-v1.5
for f in onnx/model_quantized.onnx tokenizer.json config.json; do
  curl -L -o "$(basename $f)" "https://hf-mirror.com/Xenova/bge-small-zh-v1.5/resolve/main/$f"
done
cd -
```

> 也可以用 `WENGU_EMBEDDER=api` + `WENGU_EMBED_API_BASE/KEY/MODEL` 换成任意 OpenAI 兼容
> embedding 服务；`WENGU_EMBEDDER=hash` 则强制使用离线哈希向量。

### 4.3 启动

```bash
wengu serve --host 0.0.0.0 --port 8000
# 或： python -m uvicorn wengu.api:app --host 0.0.0.0 --port 8000
```

浏览器打开 `http://<机器地址>:8000`。首次启动会自动：建 seekdb 库与集合 → 起一个进程内的
PowerContext Server（SQLite 存储）→ 建 scope → 载入记忆。

### 4.4 配置项（全部有默认值）

复制 `.env.example` 为 `.env` 后按需修改，或直接导出环境变量：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `WENGU_DATA_DIR` | `./data` | seekdb 数据、PowerContext 状态、上传文件、模型都放这里 |
| `WENGU_STORE` | `auto` | `auto` / `seekdb` / `sqlite` |
| `WENGU_EMBEDDER` | `auto` | `auto` / `onnx` / `hash` / `api` |
| `WENGU_PC_DB` | `sqlite` | PowerContext 自身的存储：`sqlite` 或 `seekdb` |
| `WENGU_POWERCONTEXT_URL` | 空 | 指向已有 PowerContext Server；为空则进程内自启 |
| `WENGU_DAILY_QUOTA` | `6` | 每日复习题量默认值（界面里可改，会写进记忆） |

---

## 5. 验证样例（评审按这 6 步即可复现）

以下命令都在 `qoder/wengu/` 下执行，`records/` 里是本次提交对应的真实输出。

```bash
# 0) 自检：存储后端、向量维度、PowerContext 地址与 scope
python -m wengu.cli doctor

# 1) 导入示例语料：6 篇数据库笔记 + 1 篇 PDF（OceanBase TPC-C 论文精读）
python -m wengu.cli ingest --sample

# 2) 带出处提问：看 citations 与 vector_top / fulltext_top
python -m wengu.cli ask "Raft 里一条日志什么时候算已提交？" --top-k 5

# 3) 生成今日复习题（按到期+薄弱排序，人工考点优先）
python -m wengu.cli review

# 4) 提交一次复习结果（写入 PowerContext，推进 artifact revision）
python -m wengu.cli grade raft forgot

# 5) 端到端验证：导入→提问→复习→重启 PowerContext→记忆复用→再提问
python -m wengu.cli demo --out records

# 6) 单元测试
python -m pytest -q
```

**预期结果**

| 步骤 | 预期 |
| --- | --- |
| 0 | `"store": {"backend": "seekdb", "chunks": 34, "dimension": 512, "fulltext_analyzer": "ik"}`，`embedder.provider = onnx-bge-small-zh-v1.5` |
| 1 | `imported` 7 篇（6 md + 1 pdf），`skipped` 为空 |
| 2 | 第一条引用是「Raft 共识算法 · 日志复制」，摘录包含「多数派确认持久化后，Leader 提交」；`timings_ms.total` 为几十毫秒 |
| 3 | 返回 6 道题，`reason` 形如「到期复习，而且上次掌握度偏低」 |
| 4 | `strength` 下降、`due` 变成次日，`records`/`doctor` 的事件里出现 `powercontext.replace_artifact`（`from_revision → to_revision`） |
| 5 | `records/demo_summary.json` 中 `restart_and_reuse.state_reused = true`、`topics_after = 6`；`records/tech.json` 含 `seekdb.*` 与 `powercontext.create_artifact / replace_artifact` 事件 |
| 6 | `15 passed` |

**技术生效的证据在哪里看**

- seekdb：`records/tech.json` 的 `store`（集合、维度、索引、分词器）、`records/ask.json` 的
  `trace.vector_hits / fulltext_hits / fused`；界面「技术证据」页的「最近一次检索追踪」。
- PowerContext：`records/tech.json` 的 `powercontext.create_artifact`、`powercontext.replace_artifact`
  （含 artifact_id 与 revision 变化）、`records/memory_before_restart.json` / `memory_after_restart.json`；
  界面「它记住了什么」页的「记忆版本」列。

---

## 6. 目录结构

```
qoder/wengu/
├── wengu/
│   ├── config.py          # 环境变量与默认值
│   ├── library.py         # PDF/MD/TXT 解析与按小节切分
│   ├── embedding.py       # ONNX bge / 哈希 / API 三种向量化后端
│   ├── store/             # 知识库后端：seekdb 与 SQLite 两套实现
│   ├── retrieval.py       # 双路召回 + RRF 融合 + 薄弱点加权 + 摘录式回答
│   ├── memory.py          # PowerContext 记忆层（artifact 创建/更新/版本）
│   ├── runtime.py         # 进程内启动 PowerContext Server
│   ├── coach.py           # 组卷、自动出题、评分
│   ├── service.py         # 业务编排（界面/CLI/验证脚本共用）
│   ├── api.py             # FastAPI 接口
│   ├── cli.py             # wengu serve/ingest/ask/review/grade/demo/doctor
│   └── static/            # 单页界面（无构建步骤）
├── sample_library/        # 示例语料（6 md + 1 pdf + 人工考点 quizzes.json）
├── scripts/               # 生成示例 PDF、一键验证脚本
├── docs/                  # 架构、验证样例、技术说明、Qoder 开发记录
├── website/               # Qoder Sites 站点源码（可直接发布）
├── records/               # 本次提交对应的真实验证输出
├── tests/                 # 15 个单元测试
├── .env.example
└── README.md
```

---

## 7. 已知限制（如实说明）

1. **嵌入式 seekdb 只支持 Linux x86_64 / macOS arm64**（上游 wheel 限制）。Windows 上会自动回退
   SQLite 后端，功能完整但「seekdb 参与」这一项需要在 Linux/评测机验证；本次提交的记录全部来自
   Linux（openEuler 24.03 LTS + Python 3.11 + pyseekdb 1.4.0.post1）。
2. **同一个 `WENGU_DATA_DIR` 下的嵌入式 seekdb 同一时间只能被一个进程打开**（与 SQLite 类似）。
   跑 CLI 验证前请先停掉 `wengu serve`，或者给 CLI 换一个数据目录，例如：
   `WENGU_DATA_DIR=$PWD/data-cli python -m wengu.cli demo --out records`。
   否则会看到 `seekdb_open failed`；把该数据目录删掉重新导入即可恢复。
3. 回答是**摘录式**（原文句子 + 出处），不是大模型生成的自由文本；这样做的目的是避免无出处幻觉，
   也保证零 API Key 可运行。需要生成式回答时可在 `retrieval.compose_extractive_answer` 后接自建 LLM。
4. 复习调度是简化的 SM-2（三档自评 + 间隔倍率），没有实现完整的难度因子与题库难度校准。
5. 自动出题靠原文句子与关键术语，质量不如人工考点；示例语料因此附带了 `quizzes.json`。
6. 向量模型首次运行需要下载（约 24 MB，放到 `$WENGU_DATA_DIR/models/bge-small-zh-v1.5/`），
   离线环境会自动降级为哈希向量，此时语义检索能力下降（`doctor` 的 `embedder.fallback_notes` 会说明原因）。
7. 单用户、单 scope 设计；多用户需要按 `scope_id` 扩展路由。

---

## 8. 数据与隐私

- 所有数据都在 `WENGU_DATA_DIR` 下：seekdb 数据目录、PowerContext 的 SQLite 文件、上传的原始文件。
- 不向任何外部服务发送文献内容；唯一的外部访问是可选地下载向量模型。
- 示例语料为公开论文的阅读笔记，非论文原文。
