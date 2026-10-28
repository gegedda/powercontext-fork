---
title: WAL 与 ARIES 恢复
year: 1992
tags: 存储引擎,恢复,WAL
source: Mohan et al., ARIES, SIGMOD 1992
---

# WAL 与 ARIES 恢复

## 定义

WAL（Write-Ahead Logging，预写日志）是事务持久化的基础规则：**日志必须先于数据页落盘**。ARIES 是 C. Mohan 等人在 1992 年 SIGMOD 论文《ARIES: A Transaction Recovery Method Supporting Fine-Granularity Locking and Partial Rollbacks Using Write-Ahead Logging》中提出的恢复算法，被 IBM DB2、SQL Server、MySQL InnoDB、PostgreSQL 等广泛借鉴。

## 关键概念

- **LSN（Log Sequence Number）**：日志记录的单调递增编号；每个数据页记录 `pageLSN`。
- **日志记录类型**：redo-only、undo-redo、CLR（Compensation Log Record，补偿日志）。
- **WAL 规则**：数据页落盘前，其 pageLSN 之前的日志必须已持久化（write-ahead）。
- **Steal / No-Force**：允许把未提交事务修改的页刷盘（steal），事务提交时不强制刷数据页（no-force），因此崩溃后既有 redo 也有 undo。
- **Fuzzy Checkpoint**：检查点不阻塞正常事务，只记录 `CheckpointLSN` 与脏页表（Dirty Page Table）和事务表（Transaction Table）。

## 三阶段恢复

1. **分析阶段（Analysis）**：从最近一次检查点开始扫描日志，重建脏页表和活跃事务表，确定 redo 起点。
2. **重做阶段（Redo）**：从 `RedoStartLSN` 重放所有已落盘可能不完整的历史，把数据库恢复到崩溃瞬间状态（repeating history）。
3. **撤销阶段（Undo）**：回滚崩溃时未提交的事务，写入 CLR 保证恢复过程本身可重入（恢复期间再次崩溃不会重复回滚）。

## 常见误区

- WAL 不等于 binlog：WAL 是物理/逻辑页级重做日志，binlog 是逻辑复制日志，二者用途不同。
- 检查点不是「把脏页全部刷完」，fuzzy checkpoint 允许脏页继续存在。
- 组提交（group commit）把多个事务的 fsync 合并，是提升写吞吐的关键，但不改变正确性语义。
