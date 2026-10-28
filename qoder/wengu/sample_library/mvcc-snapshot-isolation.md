---
title: MVCC 与快照隔离
year: 2020
tags: 事务,并发控制,MVCC
source: Mohan et al., ARIES 与 InnoDB MVCC 实现笔记
---

# MVCC 与快照隔离

## 定义

MVCC（Multi-Version Concurrency Control，多版本并发控制）让读操作不阻塞写、写操作不阻塞读：每个事务看到的是数据库在某一时刻的一致性快照，而不是被别的事务修改到一半的状态。主流实现分两类：基于 undo 日志的回滚段（OceanBase、Oracle、MySQL InnoDB）和基于多版本链的追加式存储（PostgreSQL 的 heap tuple + xmin/xmax）。

## InnoDB 的实现

- 每行记录带两个隐藏列：`DB_TRX_ID`（最后修改它的事务 ID）和 `DB_ROLL_PTR`（指向 undo log 的回滚指针）。
- 事务开始时生成 **Read View**，记录当时活跃事务列表（`m_ids`）、最小活跃事务 ID（`min_trx_id`）和下一个未分配事务 ID（`max_trx_id`）。
- 判断可见性：若行的 `DB_TRX_ID` 小于 `min_trx_id`，可见；若大于等于 `max_trx_id`，不可见；否则看它是否在 `m_ids` 中，在则不可见。
- **可重复读（RR）** 在整个事务里复用同一个 Read View；**读已提交（RC）** 每条语句新建 Read View。

## 快照隔离的异常

快照隔离避免了脏读、不可重复读、幻读（部分实现），但没有避免 **写偏斜（write skew）**：两个事务读取重叠的数据集，各自写入不相交的数据，结果违反业务约束。经典例子是「至少一名医生值班」：两个事务同时读到两名医生在岗，然后各自把自己改成离岗。

解决手段是串行化快照隔离（SSI，PostgreSQL 9.1 起支持）或显式加锁。

## 关键判断

- MVCC 的代价是版本清理：InnoDB 由 purge 线程回收 undo，长事务会阻塞回收，导致 undo 表空间膨胀。
- 「MVCC 等于无锁」是错的：写写冲突仍需行锁，`SELECT ... FOR UPDATE` 需要加锁读。
- OceanBase 的 MVCC 基于多版本 memtable 与 SSTable，结合全局时间戳服务（GTS）生成快照读版本。
