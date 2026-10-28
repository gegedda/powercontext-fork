const api = async (path, options = {}) => {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (_) { data = { raw: text }; }
  if (!response.ok) {
    const message = (data && (data.detail || data.error)) || response.statusText;
    throw new Error(message);
  }
  return data;
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
));
const fmtTime = (iso) => {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("zh-CN", { hour12: false });
};

const state = {
  app: null,
  library: [],
  review: { items: [], index: 0, revealed: false, graded: [] },
  lastTrace: null,
  profile: null,
  topics: [],
  askLog: [],
};

/* ---------------- 通用渲染 ---------------- */

function renderStatus() {
  const app = state.app || {};
  const store = app.store || {};
  const embed = app.embedder || {};
  const memory = app.memory || {};
  $("#pill-store").textContent = `知识库：${store.backend || "?"} · ${store.chunks ?? 0} 片段`;
  $("#pill-store").className = `pill ${store.backend === "seekdb" ? "ok" : "warn"}`;
  $("#pill-embed").textContent = `向量：${embed.model || embed.provider || "?"} · ${embed.dim || "?"} 维`;
  $("#pill-embed").className = "pill ok";
  $("#pill-memory").textContent = `记忆：PowerContext · ${memory.entries ?? 0} 条`;
  $("#pill-memory").className = "pill ok";
}

function renderLibrary(documents, stats) {
  const container = $("#library-stats");
  container.innerHTML = `
    <div class="stat"><b>${stats.documents ?? documents.length}</b><span>文献</span></div>
    <div class="stat"><b>${stats.chunks ?? 0}</b><span>检索片段</span></div>
    <div class="stat"><b>${(stats.total_chars ?? 0).toLocaleString()}</b><span>正文字数</span></div>
    <div class="stat"><b>${state.topics.length || 0}</b><span>已建知识点</span></div>`;

  const list = $("#doc-list");
  if (!documents.length) {
    list.innerHTML = `<p class="hint">知识库还是空的，先导入示例文献或你自己的 PDF。</p>`;
    return;
  }
  const topicMap = Object.fromEntries((state.topics || []).map((t) => [t.doc_id, t]));
  list.innerHTML = documents.map((doc) => {
    const topic = topicMap[doc.doc_id];
    const strength = topic ? Math.round((topic.strength || 0) * 100) : 0;
    const tags = (doc.tags || []).map((tag) => `<span class="tag">${esc(tag)}</span>`).join("");
    const status = !topic || !topic.attempts ? "未复习" : (topic.weak ? "薄弱" : "已掌握");
    const statusClass = status === "薄弱" ? "tag warn" : "tag";
    return `
      <div class="doc">
        <div class="doc-head">
          <div class="doc-main">
            <div class="doc-title">${esc(doc.title)}</div>
            <div class="doc-meta">${esc(doc.kind)} · ${doc.n_chunks} 片段${doc.year ? " · " + doc.year : ""}</div>
            <div class="doc-tags">${tags}<span class="${statusClass}">${status}</span></div>
          </div>
          <div class="doc-actions">
            <span class="doc-meta">掌握度 ${strength}%</span>
            <button class="ghost" data-delete="${esc(doc.doc_id)}">移除</button>
          </div>
        </div>
        <div class="bar"><i style="width:${strength}%"></i></div>
      </div>`;
  }).join("");

  $$("[data-delete]").forEach((button) => {
    button.addEventListener("click", async () => {
      const docId = button.getAttribute("data-delete");
      if (!confirm(`确定从知识库移除 ${docId}？`)) return;
      await api(`/api/doc/${encodeURIComponent(docId)}`, { method: "DELETE" });
      await reloadAll();
    });
  });
}

function renderAsk(result) {
  const output = $("#ask-output");
  if (!result) { output.innerHTML = ""; return; }
  state.lastTrace = result.trace;
  const answer = result.answer || { blocks: [] };
  const blocks = (answer.blocks || []).map((block) => `
    <div class="quote">
      <div class="loc">「${esc(block.title)}」· ${esc(block.section || "正文")}${block.page ? " · 第 " + block.page + " 页" : ""} · 片段 ${esc(block.chunk_id)}</div>
      <div class="text">${esc(block.quote)}</div>
      <div class="why">
        ${(block.matched_by || []).map((why) => `<span>${esc(why)}</span>`).join("")}
        ${block.weak_topic ? '<span class="weak">薄弱点加权</span>' : ""}
      </div>
    </div>`).join("");

  const trace = result.trace || {};
  const timings = trace.timings_ms || {};
  const fusion = (trace.fused || []).slice(0, 6).map((item) => {
    const doc = item.chunk_id.split("#")[0];
    return `· ${item.chunk_id}  score=${Number(item.score).toFixed(5)}  vec#${item.vector_rank ?? "-"}  ft#${item.fulltext_rank ?? "-"}  boost=${item.weak_boost ?? 1}`;
  }).join("\n");

  output.innerHTML = `
    <div class="card answer-card">
      <h2>回答</h2>
      <p class="answer-summary">${esc(answer.summary || "")}</p>
      ${blocks}
      <details class="trace">
        <summary>技术追踪：这一问在 seekdb 里查了什么（${(timings.total ?? 0).toFixed(1)} ms）</summary>
        <pre class="trace">${esc(JSON.stringify({
          query: trace.query, backend: trace.backend, filters: trace.filters,
          embedder: trace.embedder, timings_ms: timings,
          vector_top: (trace.vector_hits || []).slice(0, 5),
          fulltext_top: (trace.fulltext_hits || []).slice(0, 5),
          weak_topics: trace.weak_topics, fused_top: fusion,
        }, null, 2))}</pre>
      </details>
    </div>`;
}

function renderReview() {
  const { items, index, revealed } = state.review;
  const body = $("#review-body");
  $("#review-progress").textContent = items.length ? `${Math.min(index + 1, items.length)} / ${items.length}` : "0 / 0";
  if (!items.length) {
    body.innerHTML = `<p class="hint">点击「开始今天的复习」，教练会按「到期 + 薄弱」排序出题。</p>
      <button class="primary" id="btn-start-review">开始今天的复习</button>`;
    bindReviewStart();
    return;
  }
  if (index >= items.length) {
    body.innerHTML = `<div class="review-card"><h3>今天的 ${items.length} 道题完成了 🎉</h3>
      <p class="hint">结果已经写进 PowerContext，下次打开会按新的掌握度和间隔安排复习。</p>
      <button class="primary" onclick="startReview()">再来一轮</button></div>`;
    return;
  }
  const item = items[index];
  body.innerHTML = `
    <div class="review-card">
      <div class="meta">
        <span>「${esc(item.title)}」· ${esc(item.section || "正文")}</span>
        <span>${esc(item.reason)}</span>
        <span>掌握度 ${Math.round((item.strength || 0) * 100)}%</span>
        <span>${item.source === "curated" ? "人工考点" : "原文自动出题"}</span>
      </div>
      <div class="q">${esc(item.question)}</div>
      ${revealed ? `<div class="a"><strong>参考答案</strong><br/>${esc(item.answer)}</div>
        <div class="grade-row">
          <button data-grade="forgot">忘了</button>
          <button data-grade="vague">模糊</button>
          <button data-grade="known">记得</button>
        </div>` : `<div class="grade-row"><button class="primary" id="btn-reveal">显示答案</button></div>`}
    </div>`;
  if (!revealed) {
    $("#btn-reveal").addEventListener("click", () => { state.review.revealed = true; renderReview(); });
  }
  $$("[data-grade]").forEach((button) => {
    button.addEventListener("click", async () => {
      const grade = button.getAttribute("data-grade");
      await api("/api/review/grade", {
        method: "POST",
        body: JSON.stringify({ item_id: item.item_id, doc_id: item.doc_id, grade, question: item.question }),
      });
      state.review.index += 1;
      state.review.revealed = false;
      await refreshMemory();
      renderReview();
    });
  });
}

function renderWeak() {
  const weak = state.topics.filter((topic) => topic.weak && topic.attempts > 0)
    .sort((a, b) => a.strength - b.strength);
  const container = $("#weak-list");
  if (!weak.length) {
    container.innerHTML = `<p class="hint">还没有薄弱点。做几道复习题，教练就会开始记录。</p>`;
    return;
  }
  container.innerHTML = weak.map((topic) => `
    <div class="weak-item">
      <div class="label"><span>${esc(topic.title || topic.doc_id)}</span><span>${Math.round(topic.strength * 100)}%</span></div>
      <div class="bar"><i style="width:${Math.round(topic.strength * 100)}%"></i></div>
    </div>`).join("");
}

function renderMemory() {
  const profile = state.profile || {};
  $("#p-nickname").value = profile.nickname || "";
  $("#p-goal").value = profile.goal || "";
  $("#p-style").value = profile.style || "要点优先";
  $("#p-quota").value = profile.daily_quota || 6;
  $("#quota-input").value = profile.daily_quota || 6;
  $("#memory-meta").textContent = `这些字段存在 PowerContext 的 scope ${state.app?.memory?.scope_id || ""} 中；服务重启后依然可以读回。`;

  const log = state.askLog || [];
  $("#ask-log").innerHTML = log.length
    ? log.map((item) => `<div class="item">${esc(item.question)}<br/><span>${fmtTime(item.at)} · ${(item.sources || []).map(esc).join("、")}</span></div>`).join("")
    : `<p class="hint">还没有提问记录。</p>`;

  const topics = (state.topics || []).slice().sort((a, b) => a.strength - b.strength);
  $("#topic-table").innerHTML = topics.length ? `
    <table class="topics"><thead><tr><th>知识点</th><th>掌握度</th><th>复习次数</th><th>答对</th><th>下次到期</th><th>记忆版本</th></tr></thead>
    <tbody>${topics.map((topic) => `
      <tr>
        <td>${esc(topic.title || topic.doc_id)}</td>
        <td class="meter"><div class="bar"><i style="width:${Math.round((topic.strength || 0) * 100)}%"></i></div><span>${Math.round((topic.strength || 0) * 100)}%</span></td>
        <td>${topic.attempts}</td>
        <td>${topic.correct}</td>
        <td>${topic.attempts ? fmtTime(topic.due) : "未复习"}</td>
        <td>${topic.revision ? "rev " + topic.revision : "—"}</td>
      </tr>`).join("")}</tbody></table>`
    : `<p class="hint">还没有知识点记录。</p>`;
}

function renderTech() {
  const app = state.app || {};
  const store = app.store || {};
  const embed = app.embedder || {};
  $("#tech-stats").innerHTML = `
    <div class="stat"><b>${esc(store.backend || "?")}</b><span>知识库后端</span></div>
    <div class="stat"><b>${store.documents ?? 0}</b><span>文档</span></div>
    <div class="stat"><b>${store.chunks ?? 0}</b><span>片段（可检索单元）</span></div>
    <div class="stat"><b>${embed.dim ?? "?"}</b><span>向量维度</span></div>`;
  $("#tech-where").textContent = `seekdb 数据目录：${store.path || "—"} · 向量模型：${embed.model || embed.provider}（${(embed.fallback_notes || []).join("；") || "直接可用"}）`;

  const memory = app.memory || {};
  const counters = memory.counters || {};
  const created = counters["powercontext.create_artifact"] || 0;
  const replaced = counters["powercontext.replace_artifact"] || 0;
  const listed = counters["powercontext.list_atomic_memories"] || 0;
  $("#tech-memory").innerHTML = `
    <div class="stat"><b>${memory.entries ?? 0}</b><span>Memory 条目</span></div>
    <div class="stat"><b>${created}</b><span>新建记忆</span></div>
    <div class="stat"><b>${replaced}</b><span>更新记忆（revision+1）</span></div>
    <div class="stat"><b>${listed}</b><span>读取记忆</span></div>`;
  $("#tech-memory-where").textContent = `PowerContext：${memory.base_url || "—"} · scope_id：${memory.scope_id || "—"}`;

  const events = app.events || [];
  $("#tech-events").innerHTML = `<thead><tr><th>时间</th><th>类型</th><th>参数摘要</th></tr></thead>
    <tbody>${events.map((event) => {
      const params = Object.entries(event).filter(([key]) => !["ts", "kind", "seq"].includes(key))
        .map(([key, value]) => `${key}=${typeof value === "object" ? JSON.stringify(value) : value}`).join(" · ");
      return `<tr><td>${fmtTime(event.ts)}</td><td class="kind">${esc(event.kind)}</td><td class="params">${esc(params)}</td></tr>`;
    }).join("")}</tbody>`;

  $("#tech-trace").textContent = state.lastTrace
    ? JSON.stringify(state.lastTrace, null, 2)
    : "还没有检索记录。到「带出处提问」里问一句再回来。";
}

/* ---------------- 数据刷新 ---------------- */

async function reloadAll() {
  const data = await api("/api/state");
  state.app = data;
  state.library = data.documents || [];
  state.topics = (data.memory && data.memory.topics) || [];
  state.profile = (data.memory && data.memory.profile) || {};
  state.askLog = (data.memory && data.memory.ask_log) || [];
  renderStatus();
  renderLibrary(state.library, data.store || {});
  renderWeak();
  renderMemory();
  renderReview();
  renderTech();
}

async function refreshMemory() {
  const data = await api("/api/memory");
  state.profile = data.profile || {};
  state.topics = data.topics || [];
  state.askLog = data.ask_log || [];
  renderWeak();
  renderMemory();
}

async function startReview() {
  const data = await api("/api/review");
  state.review = { items: data.items || [], index: 0, revealed: false, graded: [] };
  state.profile = data.profile || state.profile;
  state.topics = data.topics || state.topics;
  renderWeak();
  renderReview();
  renderMemory();
}

function bindReviewStart() {
  const button = $("#btn-start-review");
  if (button) button.addEventListener("click", startReview);
}

/* ---------------- 事件绑定 ---------------- */

function bindTabs() {
  $$("#tabs button").forEach((button) => {
    button.addEventListener("click", () => {
      $$("#tabs button").forEach((item) => item.classList.remove("active"));
      $$(".tab-panel").forEach((panel) => panel.classList.remove("active"));
      button.classList.add("active");
      $(`#panel-${button.getAttribute("data-tab")}`).classList.add("active");
      if (button.getAttribute("data-tab") === "tech") reloadAll();
    });
  });
}

async function ingestFiles(files) {
  if (!files || !files.length) return;
  const form = new FormData();
  Array.from(files).forEach((file) => form.append("files", file));
  $("#ingest-result").innerHTML = `<p class="skeleton"><span class="spinner"></span>正在解析、切分、向量化并写入知识库…</p>`;
  try {
    const response = await fetch("/api/ingest", { method: "POST", body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "导入失败");
    const imported = (data.imported || []).map((item) => `${item.title}（${item.chunks} 片段）`).join("；");
    $("#ingest-result").innerHTML = `<p class="ok">已导入：${esc(imported || "无")}</p>` +
      (data.skipped && data.skipped.length ? `<p class="hint">跳过：${esc(data.skipped.join("；"))}</p>` : "");
    await reloadAll();
  } catch (error) {
    $("#ingest-result").innerHTML = `<p class="err">导入失败：${esc(error.message)}</p>`;
  }
}

function bindLibrary() {
  $("#pick-file").addEventListener("click", () => $("#file-input").click());
  $("#file-input").addEventListener("change", (event) => ingestFiles(event.target.files));
  const dropzone = $("#dropzone");
  ["dragenter", "dragover"].forEach((name) => dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    dropzone.classList.add("drag");
  }));
  ["dragleave", "drop"].forEach((name) => dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    dropzone.classList.remove("drag");
  }));
  dropzone.addEventListener("drop", (event) => ingestFiles(event.dataTransfer.files));

  $("#btn-sample").addEventListener("click", async () => {
    $("#ingest-result").innerHTML = `<p class="skeleton"><span class="spinner"></span>正在导入示例文献…</p>`;
    try {
      const data = await api("/api/ingest/sample", { method: "POST" });
      $("#ingest-result").innerHTML = `<p class="ok">示例文献已就绪：${(data.imported || []).map((item) => esc(item.title)).join("、")}</p>`;
      await reloadAll();
      await startReview();
    } catch (error) {
      $("#ingest-result").innerHTML = `<p class="err">导入失败：${esc(error.message)}</p>`;
    }
  });

  $("#btn-reset").addEventListener("click", async () => {
    if (!confirm("清空知识库（同时重置复习记忆）？")) return;
    await api("/api/reset", { method: "POST" });
    $("#ingest-result").innerHTML = `<p class="hint">知识库已清空。</p>`;
    await reloadAll();
  });
}

function bindAsk() {
  const run = async () => {
    const question = $("#ask-input").value.trim();
    if (!question) return;
    const tags = $("#filter-tags").value.split(/[,，\s]+/).filter(Boolean);
    const kind = $("#filter-kind").value;
    const year = $("#filter-year").value;
    $("#ask-output").innerHTML = `<div class="card"><p class="skeleton"><span class="spinner"></span>正在 seekdb 里做混合检索…</p></div>`;
    try {
      const data = await api("/api/ask", {
        method: "POST",
        body: JSON.stringify({
          question,
          tags,
          kind,
          year_min: year ? Number(year) : null,
          top_k: 8,
        }),
      });
      renderAsk(data);
      await refreshMemory();
      renderTech();
    } catch (error) {
      $("#ask-output").innerHTML = `<div class="card"><p class="err">检索失败：${esc(error.message)}</p></div>`;
    }
  };
  $("#btn-ask").addEventListener("click", run);
  $("#ask-input").addEventListener("keydown", (event) => { if (event.key === "Enter") run(); });
  $$(".chip").forEach((chip) => chip.addEventListener("click", () => {
    $("#ask-input").value = chip.getAttribute("data-q");
    run();
  }));
  $("#btn-clear-filters").addEventListener("click", () => {
    $("#filter-tags").value = "";
    $("#filter-kind").value = "";
    $("#filter-year").value = "";
  });
}

function bindReviewAndMemory() {
  $("#btn-start-review").addEventListener("click", startReview);
  $("#btn-save-profile").addEventListener("click", async () => {
    await api("/api/profile", {
      method: "POST",
      body: JSON.stringify({
        nickname: $("#p-nickname").value,
        goal: $("#p-goal").value,
        style: $("#p-style").value,
        daily_quota: Number($("#p-quota").value) || 6,
      }),
    });
    await refreshMemory();
    alert("已写入 PowerContext，重启后仍然有效。");
  });
  $("#btn-save-quota").addEventListener("click", async () => {
    await api("/api/profile", {
      method: "POST",
      body: JSON.stringify({ daily_quota: Number($("#quota-input").value) || 6 }),
    });
    await refreshMemory();
  });
}

(async function boot() {
  bindTabs();
  bindLibrary();
  bindAsk();
  bindReviewAndMemory();
  try {
    await reloadAll();
  } catch (error) {
    $("#status").innerHTML = `<span class="pill warn">后端未就绪：${esc(error.message)}</span>`;
  }
})();
