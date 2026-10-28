---
title: 向量索引：HNSW 与 IVF-PQ
year: 2018
tags: 向量检索,ANN,索引
source: Malkov & Yashunin, HNSW, 2018
---

# 向量索引：HNSW 与 IVF-PQ

## 为什么需要向量索引

向量检索是「找出与查询向量最近的 k 个向量」。精确检索需要全量扫描，复杂度 O(N·d)；近似最近邻（ANN）用少量召回率换取数量级的延迟下降。HNSW 与 IVF 系列是两代主流方案。

## HNSW（Hierarchical Navigable Small World）

- 由 Yu. A. Malkov 与 D. A. Yashunin 在 2018 年论文《Efficient and Robust Approximate Nearest Neighbor Search Using Hierarchical Navigable Small World Graphs》中系统描述。
- 结构是多层图：上层稀疏用于快速跳转，最底层包含所有向量。
- 建图参数 **M**（每个节点的最大出边数，常用 16–64）与 **efConstruction**（建图时的候选队列长度，常用 100–200）。
- 查询参数 **ef**（search width，常取 64–256），ef 越大召回率越高、延迟越大。
- 插入时随机决定节点最高层级，逐层贪心下降，在最底层用启发式邻居选择与剪枝。
- 优点：高召回、低延迟；缺点：内存占用大（图结构常驻内存），删除与更新需要 tombstone 或重建。

## IVF 与 PQ

- **IVF（Inverted File）**：先用 k-means 把向量空间划分成 nlist 个簇，查询只探测最近的 nprobe 个簇。
- **PQ（Product Quantization）**：把 d 维向量切成 m 段，每段用 256 个聚类中心编码为 1 字节，压缩比为 d/m 倍。
- IVF-PQ（Jégou 等人的 FAISS 方案）用 PQ 距离表加速簇内重排，内存极省，适合十亿级向量，但召回率通常低于 HNSW。

## 过滤检索：pre-filter 与 post-filter

带业务条件（年份、标签、作者）的向量检索有两条路：

- **pre-filter**：先用标量索引筛出候选集，再在其中做向量检索。结果准确但可能破坏图/倒排结构，候选过少时性能骤降。
- **post-filter**：先向量召回 top-k，再按条件过滤；实现简单，但过滤后可能不足 k 条。

seekdb 支持向量、全文与标量条件组合的混合检索，可在同一条查询里表达「语义相似 + 关键词命中 + 元数据过滤」。

## 常见误区

- ANN 的「召回率」是相对精确检索定义的，必须和 ground truth 一起报告，否则数字没有意义。
- HNSW 参数 M 增大提升召回但内存线性增长，不是越大越好。
- 维度越高，PQ 压缩损失越大；768 维以上通常需要 OPQ 旋转优化。
